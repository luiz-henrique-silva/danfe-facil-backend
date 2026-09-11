import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.subscription import (
    SubscriptionOut,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
)

router = APIRouter(prefix="/api/subscription", tags=["subscription"])

settings = get_settings()

PLANS = {
    "pro": {"name": "Pro", "price": settings.STRIPE_PRICE_PRO},
    "business": {"name": "Business", "price": settings.STRIPE_PRICE_BUSINESS},
}

PROCESS_LIMITS = {
    "free": settings.FREE_PROCESS_LIMIT,
    "pro": 1500,
    "business": 100000,  # "ilimitado"
}


def stripe_enabled() -> bool:
    return bool(
        settings.STRIPE_SECRET_KEY
        and settings.STRIPE_PRICE_PRO
        and settings.STRIPE_PRICE_BUSINESS
    )


@router.get("/status", response_model=SubscriptionOut)
async def get_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()

    if not sub:
        sub = Subscription(user_id=user.id, plan="free", status="free")
        db.add(sub)
        await db.commit()
        await db.refresh(sub)

    return SubscriptionOut(
        plan=sub.plan,
        status=sub.status,
        current_period_end=sub.current_period_end,
        process_limit=PROCESS_LIMITS.get(sub.plan, PROCESS_LIMITS["free"]),
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(data: CheckoutRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not stripe_enabled():
        raise HTTPException(status_code=503, detail="Pagamentos indisponíveis no momento")

    if data.plan not in PLANS:
        raise HTTPException(status_code=400, detail="Plano inválido")

    price_id = data.price_id or PLANS[data.plan]["price"]
    if not price_id:
        raise HTTPException(status_code=503, detail="Preço não configurado para este plano")

    # Garante que o usuário tenha stripe_customer_id
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()

    if not sub:
        sub = Subscription(user_id=user.id, plan="free", status="free")
        db.add(sub)
        await db.flush()

    if not sub.stripe_customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            name=user.name or "",
            metadata={"user_id": user.id},
        )
        sub.stripe_customer_id = customer.id
        await db.commit()

    payment_methods = ["card"]
    if settings.STRIPE_ENABLE_PIX:
        payment_methods.append("pix")

    session = stripe.checkout.Session.create(
        customer=sub.stripe_customer_id,
        payment_method_types=payment_methods,
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.APP_URL}/dashboard?checkout=success",
        cancel_url=f"{settings.APP_URL}/dashboard?checkout=cancel",
        client_reference_id=user.id,
        metadata={"user_id": user.id, "plan": data.plan},
    )

    return CheckoutResponse(url=session.url)


@router.post("/portal", response_model=PortalResponse)
async def customer_portal(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not stripe_enabled():
        raise HTTPException(status_code=503, detail="Pagamentos indisponíveis no momento")

    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()

    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Nenhuma assinatura ativa")

    portal = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{settings.APP_URL}/dashboard/assinatura",
    )

    return PortalResponse(url=portal.url)
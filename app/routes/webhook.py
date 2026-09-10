import stripe
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.database import get_db
from app.models.subscription import Subscription, SubStatus, PlanType
from app.models.user import User

router = APIRouter(prefix="/api/webhook", tags=["webhook"])
settings = get_settings()


@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook não configurado")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Payload inválido")
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Assinatura inválida")

    handler_map = {
        "checkout.session.completed": _handle_checkout_completed,
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.payment_failed": _handle_payment_failed,
    }

    handler = handler_map.get(event["type"])
    if handler:
        await handler(event["data"]["object"], db)

    return {"received": True}


async def _handle_checkout_completed(session, db: AsyncSession):
    user_id = session.get("client_reference_id") or session["metadata"].get("user_id")
    if not user_id:
        return

    sub = (await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )).scalar_one_or_none()

    if not sub:
        user_row = await db.execute(select(User.id).where(User.id == user_id))
        if not user_row.scalar_one_or_none():
            return
        sub = Subscription(user_id=user_id)
        db.add(sub)
        await db.flush()

    subscription = session.get("subscription")
    if subscription:
        sub.stripe_subscription_id = subscription
    sub.stripe_customer_id = session.get("customer") or sub.stripe_customer_id
    sub.plan = session["metadata"].get("plan", PlanType.pro.value)
    sub.status = SubStatus.active.value

    await db.commit()


async def _handle_subscription_updated(subscription, db: AsyncSession):
    await db.execute(
        update(Subscription)
        .where(Subscription.stripe_subscription_id == subscription["id"])
        .values(
            status=subscription["status"],
            current_period_end=datetime.fromtimestamp(
                subscription["current_period_end"], tz=timezone.utc
            ) if subscription.get("current_period_end") else None,
            stripe_price_id=subscription["items"]["data"][0]["price"]["id"],
        )
    )
    await db.commit()


async def _handle_subscription_deleted(subscription, db: AsyncSession):
    await db.execute(
        update(Subscription)
        .where(Subscription.stripe_subscription_id == subscription["id"])
        .values(status=SubStatus.canceled.value, plan=PlanType.free.value)
    )
    await db.commit()


async def _handle_payment_failed(invoice, db: AsyncSession):
    sub_id = invoice.get("subscription")
    if not sub_id:
        return
    await db.execute(
        update(Subscription)
        .where(Subscription.stripe_subscription_id == sub_id)
        .values(status=SubStatus.past_due.value)
    )
    await db.commit()
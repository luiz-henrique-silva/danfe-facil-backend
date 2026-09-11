import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.subscription import Subscription
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pix", tags=["pix"])

settings = get_settings()

PIX_PRICES = {
    "basico": "MERCADOPAGO_PIX_BASICO",
    "pro": "MERCADOPAGO_PIX_PRO",
    "business": "MERCADOPAGO_PIX_BUSINESS",
}

MP_API = "https://api.mercadopago.com"


def _mp_headers() -> dict:
    return {"Authorization": f"Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}"}


def _mp_enabled() -> bool:
    return bool(settings.MERCADOPAGO_ACCESS_TOKEN)


@router.post("/checkout")
async def create_pix_checkout(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _mp_enabled():
        raise HTTPException(status_code=503, detail="PIX indisponível no momento")

    body = await request.json()
    plan = body.get("plan")
    if plan not in PIX_PRICES:
        raise HTTPException(status_code=400, detail="Plano inválido")

    amount = getattr(settings, PIX_PRICES[plan])
    if not amount or amount <= 0:
        raise HTTPException(status_code=503, detail="Preço PIX não configurado")

    desc = {
        "pro": "UniDANFE - Assinatura Pro (1 mês)",
        "business": "UniDANFE - Assinatura Business (1 mês)",
    }[plan]

    exref = f"{user.id}|{plan}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{MP_API}/v1/payments",
            headers=_mp_headers(),
            json={
                "transaction_amount": float(amount),
                "description": desc,
                "payment_method_id": "pix",
                "payer": {"email": user.email, "first_name": user.name or ""},
                "external_reference": exref,
                "notification_url": f"{settings.APP_URL}/api/pix/webhook",
            },
        )

    if resp.status_code >= 400:
        logger.error("MP create pix failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="Falha ao gerar o QR code PIX")

    data = resp.json()
    pay_id = data.get("id")
    txn = (data.get("point_of_interaction") or {}).get("transaction_data") or {}

    return {
        "payment_id": pay_id,
        "qr_code_base64": txn.get("qr_code_base64"),
        "qr_code": txn.get("qr_code"),
        "payment_method_id": data.get("payment_method_id"),
        "status": data.get("status"),
    }


@router.get("/checkout/{payment_id}")
async def get_pix_status(
    payment_id: str,
    user: User = Depends(get_current_user),
):
    if not _mp_enabled():
        raise HTTPException(status_code=503, detail="PIX indisponível no momento")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{MP_API}/v1/payments/{payment_id}",
            headers=_mp_headers(),
        )

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail="Falha ao consultar o pagamento")

    data = resp.json()
    return {
        "payment_id": data.get("id"),
        "status": data.get("status"),
        "status_detail": data.get("status_detail"),
    }


@router.post("/webhook")
async def pix_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    pay_id = ((body.get("data") or {}).get("id"))
    if not pay_id:
        return {"received": True}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{MP_API}/v1/payments/{pay_id}",
            headers=_mp_headers(),
        )
    if resp.status_code >= 400:
        logger.error("MP webhook lookup failed: %s %s", resp.status_code, resp.text)
        return {"received": True, "lookup_failed": True}

    data = resp.json()
    if data.get("status") != "approved":
        return {"received": True, "status": data.get("status")}

    exref = data.get("external_reference") or ""
    if "|" not in exref:
        return {"received": True, "status": "no_exref"}

    user_id, plan = exref.split("|", 1)
    if plan not in PIX_PRICES:
        return {"received": True, "status": "bad_plan"}

    sub = (
        await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    ).scalar_one_or_none()
    if not sub:
        sub = Subscription(user_id=user_id)
        db.add(sub)

    sub.plan = plan
    sub.status = "active"
    sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=31)
    await db.commit()

    return {"received": True, "status": "activated"}
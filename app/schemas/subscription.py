from pydantic import BaseModel
from datetime import datetime


class SubscriptionOut(BaseModel):
    plan: str
    status: str
    current_period_end: datetime | None = None
    process_month: int | None = None
    process_limit: int | None = None


class CheckoutRequest(BaseModel):
    price_id: str | None = None  # se vazio, usa price do plano padrão
    plan: str  # 'pro' | 'business'


class CheckoutResponse(BaseModel):
    url: str


class PortalResponse(BaseModel):
    url: str
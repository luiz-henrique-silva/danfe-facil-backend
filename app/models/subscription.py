import uuid
from datetime import datetime
from sqlalchemy import String, Enum as SAEnum, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
import enum


class SubStatus(str, enum.Enum):
    active = "active"
    trialing = "trialing"
    canceled = "canceled"
    past_due = "past_due"
    free = "free"


class PlanType(str, enum.Enum):
    free = "free"
    basico = "basico"
    pro = "pro"
    business = "business"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), unique=True, nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        SAEnum("active", "trialing", "canceled", "past_due", "free", name="sub_status"),
        default="free"
    )
    plan: Mapped[str] = mapped_column(
        SAEnum("free", "basico", "pro", "business", name="plan_type"),
        default="free"
    )
    unlimited: Mapped[bool] = mapped_column(default=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

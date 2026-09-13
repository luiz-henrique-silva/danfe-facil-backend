import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ProcessHistory(Base):
    __tablename__ = "process_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="success")  # success | error
    error_message: Mapped[str | None] = mapped_column(String(500))
    result_size: Mapped[int | None] = mapped_column(default=0)  # bytes do PDF gerado
    pages_generated: Mapped[int | None] = mapped_column(default=0)  # páginas de saída geradas
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
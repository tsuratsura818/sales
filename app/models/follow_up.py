from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class FollowUpStep(Base):
    __tablename__ = "follow_up_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    # pending / generating / ready / sent / cancelled / error

    email_subject: Mapped[str | None] = mapped_column(String, nullable=True)
    email_body: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    lead: Mapped["Lead"] = relationship("Lead", back_populates="follow_up_steps")  # noqa: F821

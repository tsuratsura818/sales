import uuid
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def _make_tracking_id() -> str:
    return uuid.uuid4().hex


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False)
    to_address: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outlook_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    follow_up_step_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("follow_up_steps.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # トラッキング (Phase 6)
    tracking_id: Mapped[str | None] = mapped_column(String, unique=True, default=_make_tracking_id, nullable=True, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 初回開封
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 初回クリック
    click_count: Mapped[int] = mapped_column(Integer, default=0)

    lead: Mapped["Lead"] = relationship("Lead", back_populates="email_logs")  # noqa: F821


class EmailOpen(Base):
    """個別の開封イベント記録"""
    __tablename__ = "email_opens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_log_id: Mapped[int] = mapped_column(Integer, ForeignKey("email_logs.id"), nullable=False, index=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class LinkClick(Base):
    """個別のクリックイベント記録"""
    __tablename__ = "link_clicks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_log_id: Mapped[int] = mapped_column(Integer, ForeignKey("email_logs.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    clicked_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

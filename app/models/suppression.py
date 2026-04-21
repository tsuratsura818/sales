"""配信停止リスト (バウンス/オプトアウト/手動)"""
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SuppressionEntry(Base):
    __tablename__ = "suppression_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    # bounced_hard / bounced_soft / optout / manual
    reason: Mapped[str] = mapped_column(String, default="manual")
    # gmail_imap / webhook / mailforge / manual
    source: Mapped[str] = mapped_column(String, default="manual")
    detail: Mapped[str | None] = mapped_column(String, nullable=True)  # バウンス理由の生テキスト等
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

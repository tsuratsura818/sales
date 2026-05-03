from datetime import datetime

from sqlalchemy import Integer, String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Heartbeat(Base):
    """ローカル実行のバッチ等の最終生存確認用。name 毎に1行で upsert"""
    __tablename__ = "heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    last_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

from datetime import datetime

from sqlalchemy import Integer, DateTime, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSettings(Base):
    """アプリ全体の設定（単一行方式）"""
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 日次プラン自動送信
    daily_plan_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_plan_hour_jst: Mapped[int] = mapped_column(Integer, default=8)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

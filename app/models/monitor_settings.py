from datetime import datetime

from sqlalchemy import Integer, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MonitorSettings(Base):
    """案件モニターの設定（単一行方式）"""
    __tablename__ = "monitor_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # マッチング閾値（0-100）
    match_threshold: Mapped[int] = mapped_column(Integer, default=70)

    # モニター間隔（分）
    monitor_interval_minutes: Mapped[int] = mapped_column(Integer, default=120)

    # ユーザープロフィール文
    user_profile_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 対象カテゴリ JSON: {"crowdworks": [6,7,28], "lancers": [80,90,100]}
    search_categories: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 評価基準（スコアリングのシステムプロンプト）
    evaluate_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

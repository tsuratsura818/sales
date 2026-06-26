from datetime import datetime

from sqlalchemy import Integer, DateTime, Boolean, Text, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AppSettings(Base):
    """アプリ全体の設定（単一行方式）"""
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 日次プラン自動送信
    daily_plan_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_plan_hour_jst: Mapped[int] = mapped_column(Integer, default=8)

    # タスク期限リマインド（Notionタスクの当日期日/期限切れをLINE通知）
    task_reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    task_reminder_hour_jst: Mapped[int] = mapped_column(Integer, default=8)

    # 進行中タスクの残リマインド（毎朝9:05等に「進行中」のままのタスクをLINE通知）
    wip_reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    wip_reminder_hour_jst: Mapped[int] = mapped_column(Integer, default=9)
    wip_reminder_minute_jst: Mapped[int] = mapped_column(Integer, default=5)
    wip_reminder_last_sent: Mapped[str] = mapped_column(String(10), nullable=True)

    # 週次自動アウトリーチ（毎週: 企業検索→リスト化→メール文面下書き→LINE通知。送信はレビュー後に手動）
    weekly_outreach_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    weekly_outreach_weekday: Mapped[int] = mapped_column(Integer, default=0)  # 0=月 .. 6=日
    weekly_outreach_hour_jst: Mapped[int] = mapped_column(Integer, default=9)
    weekly_outreach_send_cap: Mapped[int] = mapped_column(Integer, default=50)  # 週あたり送信上限の目安
    weekly_outreach_last_week: Mapped[str] = mapped_column(String(10), nullable=True)  # 例 2026-W26

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

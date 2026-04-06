"""目標管理モデル

goals: 期間ごとの目標（週次/月次/四半期）
goal_snapshots: 日次スナップショット（進捗トラッキング）
"""
from datetime import datetime
from sqlalchemy import Integer, String, Float, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 期間タイプ: weekly / monthly / quarterly
    period_type: Mapped[str] = mapped_column(String, nullable=False)
    # 期間キー: "2026-W15", "2026-04", "2026-Q2" など
    period_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    # 目標値
    target_leads: Mapped[int] = mapped_column(Integer, default=0)
    target_sent: Mapped[int] = mapped_column(Integer, default=0)
    target_replies: Mapped[int] = mapped_column(Integer, default=0)
    target_meetings: Mapped[int] = mapped_column(Integer, default=0)
    target_closed: Mapped[int] = mapped_column(Integer, default=0)
    target_revenue: Mapped[int] = mapped_column(Integer, default=0)

    # 実績値（自動集計で更新）
    actual_leads: Mapped[int] = mapped_column(Integer, default=0)
    actual_sent: Mapped[int] = mapped_column(Integer, default=0)
    actual_replies: Mapped[int] = mapped_column(Integer, default=0)
    actual_meetings: Mapped[int] = mapped_column(Integer, default=0)
    actual_closed: Mapped[int] = mapped_column(Integer, default=0)
    actual_revenue: Mapped[int] = mapped_column(Integer, default=0)

    # メモ
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)


class GoalSnapshot(Base):
    __tablename__ = "goal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # スナップショット日付 "2026-04-06"
    snapshot_date: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)

    # その日時点の累積実績
    total_leads: Mapped[int] = mapped_column(Integer, default=0)
    total_sent: Mapped[int] = mapped_column(Integer, default=0)
    total_replies: Mapped[int] = mapped_column(Integer, default=0)
    total_meetings: Mapped[int] = mapped_column(Integer, default=0)
    total_closed: Mapped[int] = mapped_column(Integer, default=0)
    total_revenue: Mapped[int] = mapped_column(Integer, default=0)

    # 当日増分
    daily_leads: Mapped[int] = mapped_column(Integer, default=0)
    daily_sent: Mapped[int] = mapped_column(Integer, default=0)
    daily_replies: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

"""毎週のタスク（曜日指定）テンプレート。

指定曜日になると Notion タスクを status=進行中 で自動作成する。
weekday は Python の date.weekday() 準拠（月=0 ... 日=6、水曜=2）。
"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.database import Base


class RecurringTask(Base):
    __tablename__ = "recurring_tasks"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False, default="")
    # 頻度: weekly=毎週(曜日指定) / monthly=毎月(日付指定)
    freq = Column(String(10), nullable=False, default="weekly")
    weekday = Column(Integer, nullable=False, default=2)          # 月=0..日=6（水=2）weekly時
    day_of_month = Column(Integer, nullable=False, default=0)     # monthly時: 0=末日, 1-31=指定日
    priority = Column(String(10), nullable=False, default="中")
    project_id = Column(String(100), nullable=True)               # NotionプロジェクトID（任意）
    project_name = Column(String(200), nullable=True)             # 表示用キャッシュ
    create_status = Column(String(20), nullable=False, default="進行中")
    enabled = Column(Boolean, nullable=False, default=True)
    last_created_week = Column(String(10), nullable=True)         # 重複防止(週次): "2026-W26"
    last_created_month = Column(String(7), nullable=True)         # 重複防止(月次): "2026-06"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

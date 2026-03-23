"""メモモデル - Simplenote風メモ + Notion案件自動紐付け"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, String, DateTime
from app.database import Base


class Memo(Base):
    __tablename__ = "memos"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False, default="")
    title = Column(String(200), nullable=False, default="")
    notion_project_id = Column(String(100), nullable=True)
    notion_project_name = Column(String(200), nullable=True)
    classification_status = Column(
        String(20), nullable=False, default="pending"
    )  # pending / classified / unlinked / manual
    synced_to_notion = Column(Integer, nullable=False, default=0)  # 0=未同期, 1=同期済み
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

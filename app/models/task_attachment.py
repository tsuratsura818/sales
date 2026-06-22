"""タスク添付ファイル - Notionタスク(task_id)に紐づくPDF/画像をDB(BYTEA)に保存"""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, LargeBinary
from app.database import Base


class TaskAttachment(Base):
    __tablename__ = "task_attachments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(100), nullable=False, index=True)  # NotionタスクページID
    filename = Column(String(300), nullable=False, default="")
    content_type = Column(String(150), nullable=False, default="application/octet-stream")
    size = Column(Integer, nullable=False, default=0)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

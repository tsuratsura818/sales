from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomerActivity(Base):
    """取引先の対応履歴。Across デスクトップから「承認済みの要約1行」を受け取って貯める。

    Across 側の設計(docs/02_feature_customer_timeline.md §C1)により、生のメッセージ本文は
    送られてこない。ここに来るのは人がレビューした要約テキストと、取引先・チャネル・時刻のみ。
    """

    __tablename__ = "customer_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 取引先の紐付け。統一マスターが無いため leads / client_sites の両対応(どちらか一方)。
    lead_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("leads.id"), nullable=True, index=True
    )
    client_site_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("client_sites.id"), nullable=True, index=True
    )

    channel: Mapped[str] = mapped_column(String, nullable=False)  # chatwork/lineworks/slack/gmail
    summary: Mapped[str] = mapped_column(Text, nullable=False)  # 承認済みの1行(マスク済み)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String, default="across")

    # Across outbox.id 等での冪等化(同じ承認を二重に受け取らない)。
    external_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)

    # Phase 5: Notion 案件へ昇格(追記)した場合の案件ID。未昇格は NULL。
    notion_project_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

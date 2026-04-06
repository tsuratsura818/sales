"""インバウンドリードモデル

WordPress (soreiine) からのWebhook経由で受け取るリード
"""
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class InboundLead(Base):
    __tablename__ = "inbound_leads"
    __table_args__ = (
        UniqueConstraint("email", "source", name="uq_inbound_email_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # リード情報
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(String, nullable=True)

    # ソース情報
    source: Mapped[str] = mapped_column(String, default="wordpress")  # wordpress / diagnostic / landing_page
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)  # 流入元ページURL
    utm_source: Mapped[str | None] = mapped_column(String, nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String, nullable=True)

    # ステータス: new / contacted / qualified / converted / lost
    status: Mapped[str] = mapped_column(String, default="new", index=True)

    # 診断ツール結果（JSON文字列）
    diagnostic_result: Mapped[str | None] = mapped_column(String, nullable=True)

    # LINE通知済み
    notified: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

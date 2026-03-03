from datetime import datetime
from sqlalchemy import Integer, String, Float, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class JobListing(Base):
    __tablename__ = "job_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # プラットフォーム識別
    platform: Mapped[str] = mapped_column(String, nullable=False)  # crowdworks / lancers
    external_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String, nullable=False)

    # 案件情報
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    # web_development / seo_marketing / ec_site

    # 予算
    budget_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_type: Mapped[str | None] = mapped_column(String, nullable=True)  # fixed / hourly

    # 期限・クライアント情報
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String, nullable=True)
    client_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    client_review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ステータス
    status: Mapped[str] = mapped_column(String, default="new")
    # new / analyzing / notified / approved / applying / applied / skipped / expired / error

    # AIマッチング
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LINE通知追跡
    line_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # タイムスタンプ
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # リレーション
    application: Mapped["JobApplication"] = relationship(
        "JobApplication", back_populates="job_listing", uselist=False, lazy="select"
    )

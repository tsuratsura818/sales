from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class JobApplication(Base):
    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_listing_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_listings.id"), nullable=False, unique=True
    )

    # 提案内容
    proposal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_deadline: Mapped[str | None] = mapped_column(String, nullable=True)

    # 応募追跡
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_status: Mapped[str] = mapped_column(String, default="pending")
    # pending / submitted / replied / won / lost / withdrawn

    # 返信・受注追跡（ファネル可視化用）
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    won_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    won_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 受注金額（円）

    # エラー追跡
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # リレーション
    job_listing: Mapped["JobListing"] = relationship(
        "JobListing", back_populates="application"
    )

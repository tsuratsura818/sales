from datetime import datetime
from sqlalchemy import Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class SearchJob(Base):
    __tablename__ = "search_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String, nullable=False)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    num_results: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String, default="pending")
    total_urls: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 表示フィルター設定
    filter_http_only: Mapped[bool] = mapped_column(Boolean, default=False)
    filter_no_mobile: Mapped[bool] = mapped_column(Boolean, default=False)
    filter_cms_list: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON list

    # 検索方法: "serpapi" or "local"
    search_method: Mapped[str] = mapped_column(String, default="serpapi")

    # コスト追跡
    serpapi_calls_used: Mapped[int] = mapped_column(Integer, default=0)

    # ローカル Claude Code で提案文を自動生成するか
    auto_generate_proposal: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_proposal_min_score: Mapped[int] = mapped_column(Integer, default=50)

    leads: Mapped[list] = relationship("Lead", back_populates="search_job", lazy="select")

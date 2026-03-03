from datetime import datetime
from sqlalchemy import Integer, String, Boolean, Float, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("search_jobs.id"), nullable=False)

    # 基本情報
    url: Mapped[str] = mapped_column(String, nullable=False)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="new")
    # new / analyzing / analyzed / email_generated / sent / replied / meeting / closed / error / excluded

    # 分析結果
    is_https: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ssl_expiry_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    domain_age_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    copyright_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_viewport: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_flash: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cms_type: Mapped[str | None] = mapped_column(String, nullable=True)
    cms_version: Mapped[str | None] = mapped_column(String, nullable=True)
    pagespeed_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 1 追加: デザイン系
    has_og_image: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_favicon: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_table_layout: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    missing_alt_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Phase 1 追加: EC系
    is_ec_site: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ec_platform: Mapped[str | None] = mapped_column(String, nullable=True)
    has_site_search: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_product_schema: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Phase 1 追加: SEO系
    has_structured_data: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_breadcrumb: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_sitemap: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_robots_txt: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # 連絡先
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_page_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Phase 5: スマートスコアリング
    has_contact_form: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    form_field_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_file_upload: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    estimated_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    company_size_estimate: Mapped[str | None] = mapped_column(String, nullable=True)  # small/medium/mid_large/large
    industry_category: Mapped[str | None] = mapped_column(String, nullable=True)
    conversion_rank: Mapped[str | None] = mapped_column(String, nullable=True)  # S/A/B/C

    # スコア
    score: Mapped[int] = mapped_column(Integer, default=0)
    score_breakdown: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON

    # 生成メール
    generated_email_subject: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_email_body: Mapped[str | None] = mapped_column(String, nullable=True)

    # エラー
    analysis_error: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)

    # フォローアップ
    followup_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # None / active / paused / completed / stopped

    # Phase 6: 商談・成約追跡
    meeting_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deal_closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deal_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 成約金額（円）

    search_job: Mapped["SearchJob"] = relationship("SearchJob", back_populates="leads")  # noqa: F821
    email_logs: Mapped[list] = relationship("EmailLog", back_populates="lead", lazy="select")
    follow_up_steps: Mapped[list] = relationship("FollowUpStep", back_populates="lead", lazy="select")
    competitor_analyses: Mapped[list] = relationship("CompetitorAnalysis", back_populates="lead", lazy="select")

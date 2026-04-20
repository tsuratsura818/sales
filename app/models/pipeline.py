"""パイプライン実行モデル

PipelineRun: 実行履歴
PipelineResult: 収集リード結果
"""
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 実行設定
    sources: Mapped[str] = mapped_column(String, nullable=False)  # JSON: ["yahoo","rakuten","google"]
    keywords_count: Mapped[int] = mapped_column(Integer, default=0)
    skip_mx: Mapped[int] = mapped_column(Integer, default=1)  # 0=チェック, 1=スキップ
    # モード: ec (関西EC特化) / category (全国カテゴリ) / both
    mode: Mapped[str] = mapped_column(String, default="ec")
    # カテゴリモード用のオプション設定（JSON: {"categories": ["A","B"], "prefectures": [...], "max_queries": 100}）
    category_config: Mapped[str | None] = mapped_column(String, nullable=True)

    # ステータス: pending / running / completed / failed
    status: Mapped[str] = mapped_column(String, default="pending")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(String, nullable=True)

    # 実行結果
    total_found: Mapped[int] = mapped_column(Integer, default=0)
    total_imported: Mapped[int] = mapped_column(Integer, default=0)  # MailForgeインポート件数
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    # ソース別内訳（JSON: {"yahoo": 10, "rakuten": 15}）
    source_breakdown: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    results: Mapped[list] = relationship("PipelineResult", back_populates="run", lazy="select")


class PipelineResult(Base):
    __tablename__ = "pipeline_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("pipeline_runs.id"), nullable=False, index=True)

    # リード情報
    email: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    platform: Mapped[str | None] = mapped_column(String, nullable=True)
    ec_status: Mapped[str | None] = mapped_column(String, nullable=True)
    proposal: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)  # yahoo / rakuten / google / duckduckgo / category
    shop_code: Mapped[str | None] = mapped_column(String, nullable=True)

    # スコアリング
    rank: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # S / A / B / C
    score: Mapped[int] = mapped_column(Integer, default=0)
    # カテゴリ分類（全国カテゴリモード用）
    category: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # A / B / C / D
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 個別化済み提案文（ローカル生成）
    personalized_subject: Mapped[str | None] = mapped_column(String, nullable=True)
    personalized_body: Mapped[str | None] = mapped_column(String, nullable=True)
    # サイト分析結果（JSON）
    site_analysis: Mapped[str | None] = mapped_column(String, nullable=True)

    # MailForge連携
    imported_to_mailforge: Mapped[int] = mapped_column(Integer, default=0)  # 0/1

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="results")

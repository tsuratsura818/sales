"""パイプライン検索キーワードモデル

WebUIから追加・編集・削除可能な検索キーワード管理
"""
from datetime import datetime
from sqlalchemy import Integer, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class PipelineKeyword(Base):
    __tablename__ = "pipeline_keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 検索キーワード（例: "和菓子 大阪 老舗"）
    keyword: Mapped[str] = mapped_column(String, nullable=False)

    # 業種カテゴリ（例: "食品メーカー（和菓子）"）
    industry: Mapped[str] = mapped_column(String, nullable=False)

    # 対象ソース: all / yahoo / rakuten / google
    source: Mapped[str] = mapped_column(String, default="all")

    # 有効/無効
    enabled: Mapped[int] = mapped_column(Integer, default=1)

    # 管理用メモ
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

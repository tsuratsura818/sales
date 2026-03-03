from datetime import datetime
from sqlalchemy import Integer, String, Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)  # 実績タイトル
    client_name: Mapped[str | None] = mapped_column(String, nullable=True)  # クライアント名（匿名可）
    url: Mapped[str | None] = mapped_column(String, nullable=True)  # 実績サイトURL
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 改善内容の説明
    industry_category: Mapped[str] = mapped_column(String, nullable=False)  # 業種カテゴリ
    service_type: Mapped[str] = mapped_column(String, default="web_renewal")
    # web_renewal / ec / seo / design / other
    result_summary: Mapped[str | None] = mapped_column(String, nullable=True)  # 成果要約
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

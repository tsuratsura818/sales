from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Text, Boolean, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ClientSite(Base):
    """既存クライアントのサイト。月次健康診断の対象"""
    __tablename__ = "client_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)  # 会社名/サイト名
    url: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)  # 業種
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)  # ok / warning / critical

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)


class HealthCheckResult(Base):
    """月次健康診断の検査結果"""
    __tablename__ = "health_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_site_id: Mapped[int] = mapped_column(Integer, ForeignKey("client_sites.id"), nullable=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # 結果
    status: Mapped[str] = mapped_column(String, default="ok")  # ok / warning / critical
    ssl_days_left: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pagespeed_mobile: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pagespeed_desktop: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_form: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cms: Mapped[str | None] = mapped_column(String, nullable=True)
    cms_version: Mapped[str | None] = mapped_column(String, nullable=True)
    is_https: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # 検出した問題（JSON文字列）
    issues_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 通知済みフラグ
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

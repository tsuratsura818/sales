from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class CompetitorAnalysis(Base):
    __tablename__ = "competitor_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), nullable=False)
    search_query: Mapped[str | None] = mapped_column(String, nullable=True)
    competitor_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_data: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON
    comparison_summary: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON
    status: Mapped[str] = mapped_column(String, default="pending")
    # pending / analyzing / completed / error
    serpapi_calls_used: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    lead: Mapped["Lead"] = relationship("Lead", back_populates="competitor_analyses")  # noqa: F821

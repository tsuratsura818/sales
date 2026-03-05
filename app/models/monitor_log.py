from datetime import datetime
from sqlalchemy import Integer, String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class MonitorLog(Base):
    __tablename__ = "monitor_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    status: Mapped[str] = mapped_column(String, nullable=False)  # success / error / skipped
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cw_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lc_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notified_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Integer, nullable=True)

"""着地予測サービス

営業日ベースの進捗率 × 日次平均実績で月末/期末の着地を予測
"""
import logging
from datetime import datetime, timedelta, date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.models.email_log import EmailLog
from app.models.goal import GoalSnapshot
from app.models.job_listing import JobListing

logger = logging.getLogger(__name__)

SENT_STATUSES = ("sent", "replied", "meeting", "closed")
REPLIED_STATUSES = ("replied", "meeting", "closed")


def _business_days_in_month(year: int, month: int) -> int:
    """月内の営業日数（土日除外）"""
    d = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    count = 0
    while d < end:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def _business_days_elapsed(year: int, month: int) -> int:
    """月初から今日までの営業日数"""
    d = date(year, month, 1)
    today = date.today()
    if today.month != month or today.year != year:
        return _business_days_in_month(year, month)
    count = 0
    while d <= today:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def get_monthly_forecast(db: Session) -> dict:
    """今月の着地予測を計算"""
    now = datetime.now()
    year, month = now.year, now.month

    # 今月の期間
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end = datetime(year + 1, 1, 1)
    else:
        month_end = datetime(year, month + 1, 1)

    # 営業日
    biz_total = _business_days_in_month(year, month)
    biz_elapsed = _business_days_elapsed(year, month)
    progress_rate = biz_elapsed / biz_total if biz_total > 0 else 0

    # 今月の実績
    actual_leads = db.query(func.count(Lead.id)).filter(
        Lead.created_at >= month_start,
        Lead.created_at < month_end,
        Lead.status != "excluded",
    ).scalar() or 0

    actual_sent = db.query(func.count(EmailLog.id)).filter(
        EmailLog.sent_at >= month_start,
        EmailLog.sent_at < month_end,
        EmailLog.sent_at.isnot(None),
    ).scalar() or 0

    actual_replies = db.query(func.count(Lead.id)).filter(
        Lead.updated_at >= month_start,
        Lead.updated_at < month_end,
        Lead.status.in_(REPLIED_STATUSES),
    ).scalar() or 0

    actual_meetings = db.query(func.count(Lead.id)).filter(
        Lead.meeting_scheduled_at >= month_start,
        Lead.meeting_scheduled_at < month_end,
    ).scalar() or 0

    actual_closed = db.query(func.count(Lead.id)).filter(
        Lead.deal_closed_at >= month_start,
        Lead.deal_closed_at < month_end,
    ).scalar() or 0

    actual_revenue = db.query(func.sum(Lead.deal_amount)).filter(
        Lead.deal_closed_at >= month_start,
        Lead.deal_closed_at < month_end,
        Lead.deal_amount.isnot(None),
    ).scalar() or 0

    # 日次平均（営業日ベース）
    daily_avg_leads = actual_leads / biz_elapsed if biz_elapsed > 0 else 0
    daily_avg_sent = actual_sent / biz_elapsed if biz_elapsed > 0 else 0
    daily_avg_replies = actual_replies / biz_elapsed if biz_elapsed > 0 else 0

    # 着地予測 = 日次平均 × 営業日数合計
    forecast_leads = round(daily_avg_leads * biz_total)
    forecast_sent = round(daily_avg_sent * biz_total)
    forecast_replies = round(daily_avg_replies * biz_total)

    # 着地予測（ペース維持の場合）= 実績 / 進捗率
    pace_leads = round(actual_leads / progress_rate) if progress_rate > 0 else 0
    pace_sent = round(actual_sent / progress_rate) if progress_rate > 0 else 0
    pace_replies = round(actual_replies / progress_rate) if progress_rate > 0 else 0

    return {
        "month": f"{year}-{month:02d}",
        "business_days_total": biz_total,
        "business_days_elapsed": biz_elapsed,
        "progress_rate": round(progress_rate * 100, 1),
        "actual": {
            "leads": actual_leads,
            "sent": actual_sent,
            "replies": actual_replies,
            "meetings": actual_meetings,
            "closed": actual_closed,
            "revenue": actual_revenue,
        },
        "daily_avg": {
            "leads": round(daily_avg_leads, 1),
            "sent": round(daily_avg_sent, 1),
            "replies": round(daily_avg_replies, 1),
        },
        "forecast": {
            "leads": forecast_leads,
            "sent": forecast_sent,
            "replies": forecast_replies,
        },
        "pace": {
            "leads": pace_leads,
            "sent": pace_sent,
            "replies": pace_replies,
        },
    }


def get_weekly_comparison(db: Session) -> dict:
    """今週 vs 先週の比較データ（週次レポート用）"""
    now = datetime.now()
    # 今週（月曜始まり）
    this_monday = now - timedelta(days=now.weekday())
    this_monday = this_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    this_sunday = this_monday + timedelta(days=7)

    # 先週
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday

    def _count_period(start: datetime, end: datetime) -> dict:
        leads = db.query(func.count(Lead.id)).filter(
            Lead.created_at >= start, Lead.created_at < end, Lead.status != "excluded"
        ).scalar() or 0

        sent = db.query(func.count(EmailLog.id)).filter(
            EmailLog.sent_at >= start, EmailLog.sent_at < end, EmailLog.sent_at.isnot(None)
        ).scalar() or 0

        replies = db.query(func.count(Lead.id)).filter(
            Lead.updated_at >= start, Lead.updated_at < end, Lead.status.in_(REPLIED_STATUSES)
        ).scalar() or 0

        meetings = db.query(func.count(Lead.id)).filter(
            Lead.meeting_scheduled_at >= start, Lead.meeting_scheduled_at < end
        ).scalar() or 0

        closed = db.query(func.count(Lead.id)).filter(
            Lead.deal_closed_at >= start, Lead.deal_closed_at < end
        ).scalar() or 0

        return {"leads": leads, "sent": sent, "replies": replies, "meetings": meetings, "closed": closed}

    this_week = _count_period(this_monday, this_sunday)
    last_week = _count_period(last_monday, last_sunday)

    reply_rate = round(this_week["replies"] / this_week["sent"] * 100, 1) if this_week["sent"] > 0 else 0

    # CW/Lancers 案件取得ファネル（今週）
    def _job_count(start: datetime, end: datetime, platform: str) -> dict:
        base = db.query(func.count(JobListing.id)).filter(
            JobListing.created_at >= start, JobListing.created_at < end, JobListing.platform == platform
        )
        detected = base.scalar() or 0
        review = db.query(func.count(JobListing.id)).filter(
            JobListing.created_at >= start, JobListing.created_at < end,
            JobListing.platform == platform, JobListing.status == "review",
        ).scalar() or 0
        applied = db.query(func.count(JobListing.id)).filter(
            JobListing.created_at >= start, JobListing.created_at < end,
            JobListing.platform == platform, JobListing.status == "applied",
        ).scalar() or 0
        avg_score = db.query(func.avg(JobListing.match_score)).filter(
            JobListing.created_at >= start, JobListing.created_at < end,
            JobListing.platform == platform, JobListing.match_score.isnot(None),
        ).scalar()
        return {
            "detected": detected,
            "review": review,
            "applied": applied,
            "avg_score": round(float(avg_score), 1) if avg_score else 0,
        }

    cw_this = _job_count(this_monday, this_sunday, "crowdworks")
    lc_this = _job_count(this_monday, this_sunday, "lancers")
    cw_prev = _job_count(last_monday, last_sunday, "crowdworks")
    lc_prev = _job_count(last_monday, last_sunday, "lancers")

    # 着地予測
    forecast = get_monthly_forecast(db)

    return {
        "period": f"{this_monday.strftime('%m/%d')}〜{(this_sunday - timedelta(days=1)).strftime('%m/%d')}",
        "leads": this_week["leads"],
        "sent": this_week["sent"],
        "replies": this_week["replies"],
        "meetings": this_week["meetings"],
        "closed": this_week["closed"],
        "leads_prev": last_week["leads"],
        "sent_prev": last_week["sent"],
        "replies_prev": last_week["replies"],
        "meetings_prev": last_week["meetings"],
        "closed_prev": last_week["closed"],
        "reply_rate": reply_rate,
        "forecast_sent": forecast["forecast"]["sent"],
        "forecast_replies": forecast["forecast"]["replies"],
        # 案件取得ファネル
        "cw_detected": cw_this["detected"],
        "cw_review": cw_this["review"],
        "cw_applied": cw_this["applied"],
        "cw_avg_score": cw_this["avg_score"],
        "cw_detected_prev": cw_prev["detected"],
        "cw_review_prev": cw_prev["review"],
        "lc_detected": lc_this["detected"],
        "lc_review": lc_this["review"],
        "lc_applied": lc_this["applied"],
        "lc_avg_score": lc_this["avg_score"],
        "lc_detected_prev": lc_prev["detected"],
        "lc_review_prev": lc_prev["review"],
    }

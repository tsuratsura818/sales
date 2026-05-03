"""ダッシュボードAPI（パフォーマンス最適化版）

全エンドポイントをSQL集計ベースに変更。.all()によるフルテーブルロードを廃止。
統合エンドポイント /api/dashboard/all でフロント側のリクエスト数を削減。
"""
import json
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_

from app.database import get_db
from app.models.lead import Lead
from app.models.email_log import EmailLog
from app.models.search_job import SearchJob

router = APIRouter(prefix="/api/dashboard", tags=["dashboard-api"])

SENT_STATUSES = ("sent", "replied", "meeting", "closed")
REPLIED_STATUSES = ("replied", "meeting", "closed")
MEETING_STATUSES = ("meeting", "closed")

# キャッシュ（TTL: 60秒）
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60


def _cached(key: str, fn, *args):
    """簡易キャッシュ"""
    now = time.time()
    if key in _cache:
        cached_at, data = _cache[key]
        if now - cached_at < _CACHE_TTL:
            return data
    result = fn(*args)
    _cache[key] = (now, result)
    return result


def _kpi_data(db: Session) -> dict:
    """KPI — 1クエリで全カウントを取得"""
    row = db.query(
        func.count(case((Lead.status != "excluded", 1))).label("total_leads"),
        func.count(case((Lead.status.in_(SENT_STATUSES), 1))).label("total_sent"),
        func.count(case((Lead.status.in_(REPLIED_STATUSES), 1))).label("total_replied"),
        func.count(case((Lead.status.in_(MEETING_STATUSES), 1))).label("total_meeting"),
        func.count(case((Lead.status == "closed", 1))).label("total_closed"),
        func.sum(case((and_(Lead.status == "closed", Lead.deal_amount.isnot(None)), Lead.deal_amount), else_=0)).label("total_revenue"),
    ).first()

    total_sent = row.total_sent or 0
    total_replied = row.total_replied or 0

    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_sent = db.query(func.count(EmailLog.id)).filter(
        EmailLog.sent_at >= week_start, EmailLog.sent_at.isnot(None),
    ).scalar() or 0

    return {
        "total_leads": row.total_leads or 0,
        "total_sent": total_sent,
        "total_replied": total_replied,
        "total_meeting": row.total_meeting or 0,
        "total_closed": row.total_closed or 0,
        "total_revenue": row.total_revenue or 0,
        "reply_rate": round(total_replied / total_sent * 100, 1) if total_sent > 0 else 0,
        "week_sent": week_sent,
    }


def _funnel_data(db: Session) -> dict:
    """ファネル — SQL COUNTのみ"""
    analyzed = db.query(func.count(Lead.id)).filter(
        Lead.status != "excluded",
        Lead.status.notin_(["new", "analyzing", "error"]),
    ).scalar() or 0
    sent = db.query(func.count(Lead.id)).filter(Lead.status.in_(SENT_STATUSES)).scalar() or 0
    replied = db.query(func.count(Lead.id)).filter(Lead.status.in_(REPLIED_STATUSES)).scalar() or 0
    meeting = db.query(func.count(Lead.id)).filter(Lead.status.in_(MEETING_STATUSES)).scalar() or 0
    closed = db.query(func.count(Lead.id)).filter(Lead.status == "closed").scalar() or 0

    values = [analyzed, sent, replied, meeting, closed]
    rates = []
    prev = None
    for v in values:
        if prev is None:
            rates.append(100.0)
        else:
            rates.append(round(v / prev * 100, 1) if prev > 0 else 0)
        prev = v

    return {"labels": ["分析完了", "メール送信", "返信あり", "商談", "成約"], "values": values, "rates": rates}


def _industry_data(db: Session) -> dict:
    """業種別返信率 — GROUP BY集計"""
    rows = db.query(
        Lead.industry_category,
        func.count(Lead.id).label("sent"),
        func.count(case((Lead.status.in_(REPLIED_STATUSES), 1))).label("replied"),
    ).filter(
        Lead.status.in_(SENT_STATUSES),
        Lead.industry_category.isnot(None),
    ).group_by(Lead.industry_category).order_by(func.count(Lead.id).desc()).all()

    labels = [r.industry_category or "その他" for r in rows]
    sent = [r.sent for r in rows]
    replied = [r.replied for r in rows]
    rates = [round(r.replied / r.sent * 100, 1) if r.sent > 0 else 0 for r in rows]
    return {"labels": labels, "sent": sent, "replied": replied, "rates": rates}


def _score_data(db: Session) -> dict:
    """スコア帯別返信率 — CASE集計"""
    bands = [("0-19", 0, 19), ("20-39", 20, 39), ("40-59", 40, 59), ("60-79", 60, 79), ("80+", 80, 999)]
    labels, sent_counts, replied_counts, rates = [], [], [], []

    for label, lo, hi in bands:
        row = db.query(
            func.count(Lead.id).label("sent"),
            func.count(case((Lead.status.in_(REPLIED_STATUSES), 1))).label("replied"),
        ).filter(
            Lead.status.in_(SENT_STATUSES),
            Lead.score >= lo, Lead.score <= hi,
        ).first()
        s, r = row.sent or 0, row.replied or 0
        labels.append(label)
        sent_counts.append(s)
        replied_counts.append(r)
        rates.append(round(r / s * 100, 1) if s > 0 else 0)

    return {"labels": labels, "sent": sent_counts, "replied": replied_counts, "rates": rates}


ISSUE_LABELS = {
    "no_https": "HTTPS非対応", "old_copyright_3yr": "著作権年が古い(3年+)",
    "old_copyright_5yr": "著作権年が古い(5年+)", "no_mobile": "モバイル非対応",
    "old_domain_10yr": "ドメイン10年以上", "has_flash": "Flash使用",
    "ssl_expiry_90days": "SSL期限切れ間近", "low_pagespeed": "低速表示",
    "old_wordpress": "WordPress旧バージョン", "no_og_image": "OGP画像なし",
    "no_favicon": "ファビコンなし", "table_layout": "テーブルレイアウト",
    "many_missing_alt": "alt属性欠落", "no_structured_data": "構造化データなし",
    "no_sitemap": "サイトマップなし", "no_robots_txt": "robots.txtなし",
    "no_breadcrumb": "パンくずリストなし",
}


def _effectiveness_data(db: Session) -> dict:
    """効果分析 — score_breakdownのみロード（Leadオブジェクト全体をロードしない）"""
    rows = db.query(Lead.score_breakdown, Lead.status).filter(
        Lead.status.in_(SENT_STATUSES),
        Lead.score_breakdown.isnot(None),
    ).all()

    issue_stats: dict[str, dict[str, int]] = {}
    for breakdown_str, status in rows:
        try:
            breakdown = json.loads(breakdown_str) if isinstance(breakdown_str, str) else {}
        except Exception:
            continue
        is_replied = status in REPLIED_STATUSES
        for key in breakdown:
            if key not in issue_stats:
                issue_stats[key] = {"sent": 0, "replied": 0}
            issue_stats[key]["sent"] += 1
            if is_replied:
                issue_stats[key]["replied"] += 1

    result = [
        {"key": k, "label": ISSUE_LABELS.get(k, k), "sent": s["sent"], "replied": s["replied"],
         "rate": round(s["replied"] / s["sent"] * 100, 1) if s["sent"] > 0 else 0}
        for k, s in issue_stats.items() if s["sent"] >= 1
    ]
    result.sort(key=lambda x: x["rate"], reverse=True)

    return {
        "issues": result,
        "labels": [r["label"] for r in result],
        "rates": [r["rate"] for r in result],
        "sent_counts": [r["sent"] for r in result],
        "replied_counts": [r["replied"] for r in result],
    }


# ===== 統合エンドポイント =====

@router.get("/all")
async def dashboard_all(db: Session = Depends(get_db)):
    """全ダッシュボードデータを1リクエストで返す"""
    from app.services.forecast_service import get_monthly_forecast
    from app.services.goal_service import get_current_goals

    return _cached("dashboard_all", lambda: {
        "kpi": _kpi_data(db),
        "funnel": _funnel_data(db),
        "industry": _industry_data(db),
        "score": _score_data(db),
        "effectiveness": _effectiveness_data(db),
        "forecast": get_monthly_forecast(db),
        "goals": get_current_goals(db),
    })


# ===== 個別エンドポイント（互換性維持） =====

@router.get("/kpi")
async def kpi_summary(db: Session = Depends(get_db)):
    return _cached("kpi", _kpi_data, db)


@router.get("/funnel")
async def funnel_data(db: Session = Depends(get_db)):
    return _cached("funnel", _funnel_data, db)


@router.get("/reply-by-industry")
async def reply_by_industry(db: Session = Depends(get_db)):
    return _cached("industry", _industry_data, db)


@router.get("/reply-by-score")
async def reply_by_score(db: Session = Depends(get_db)):
    return _cached("score", _score_data, db)


@router.get("/issue-effectiveness")
async def issue_effectiveness(db: Session = Depends(get_db)):
    return _cached("effectiveness", _effectiveness_data, db)


@router.get("/forecast")
async def forecast_data(db: Session = Depends(get_db)):
    from app.services.forecast_service import get_monthly_forecast
    return _cached("forecast", get_monthly_forecast, db)


# ===== 案件取得アナリティクス =====

def _jobs_funnel_data(db: Session) -> dict:
    """CW/Lancers別のファネル（直近30日）"""
    from app.models.job_listing import JobListing
    cutoff = datetime.now() - timedelta(days=30)

    def _platform_funnel(plat: str) -> dict:
        base = db.query(JobListing).filter(
            JobListing.created_at >= cutoff, JobListing.platform == plat
        )
        detected = base.count()
        review = base.filter(JobListing.status == "review").count()
        applied = base.filter(JobListing.status == "applied").count()
        skipped = base.filter(JobListing.status == "skipped").count()
        avg_score_row = base.filter(JobListing.match_score.isnot(None)).with_entities(
            func.avg(JobListing.match_score)
        ).scalar()
        return {
            "detected": detected,
            "review": review,
            "applied": applied,
            "skipped": skipped,
            "avg_score": round(float(avg_score_row), 1) if avg_score_row else 0,
        }

    return {
        "crowdworks": _platform_funnel("crowdworks"),
        "lancers": _platform_funnel("lancers"),
        "hikakubiz": _platform_funnel("hikakubiz"),
        "period": "直近30日",
    }


def _jobs_trend_data(db: Session) -> dict:
    """日次検知トレンド（直近30日, プラットフォーム別）"""
    from app.models.job_listing import JobListing
    cutoff = datetime.now() - timedelta(days=30)

    rows = db.query(
        func.date(JobListing.created_at).label("d"),
        JobListing.platform,
        func.count(JobListing.id).label("c"),
    ).filter(
        JobListing.created_at >= cutoff
    ).group_by("d", JobListing.platform).all()

    # 日付の系列
    days = [(datetime.now().date() - timedelta(days=i)) for i in range(29, -1, -1)]
    labels = [d.strftime("%m/%d") for d in days]

    series = {"crowdworks": [0] * 30, "lancers": [0] * 30, "hikakubiz": [0] * 30}
    day_index = {d: i for i, d in enumerate(days)}
    for r in rows:
        d_str = str(r.d)
        try:
            d_obj = datetime.strptime(d_str[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        i = day_index.get(d_obj)
        if i is None:
            continue
        series.setdefault(r.platform, [0] * 30)[i] = r.c

    return {"labels": labels, "series": series}


def _jobs_by_category_data(db: Session) -> dict:
    """カテゴリ別検知数 + 平均スコア（直近30日）"""
    from app.models.job_listing import JobListing
    cutoff = datetime.now() - timedelta(days=30)

    rows = db.query(
        JobListing.category,
        func.count(JobListing.id).label("c"),
        func.avg(JobListing.match_score).label("avg_score"),
        func.count(case((JobListing.status == "review", 1))).label("review"),
    ).filter(
        JobListing.created_at >= cutoff,
        JobListing.category.isnot(None),
    ).group_by(JobListing.category).order_by(func.count(JobListing.id).desc()).limit(15).all()

    return [
        {
            "category": r.category or "(none)",
            "count": r.c,
            "avg_score": round(float(r.avg_score), 1) if r.avg_score else 0,
            "review": r.review or 0,
        }
        for r in rows
    ]


@router.get("/jobs-funnel")
async def jobs_funnel(db: Session = Depends(get_db)):
    return _cached("jobs_funnel", _jobs_funnel_data, db)


@router.get("/jobs-trend")
async def jobs_trend(db: Session = Depends(get_db)):
    return _cached("jobs_trend", _jobs_trend_data, db)


@router.get("/jobs-by-category")
async def jobs_by_category(db: Session = Depends(get_db)):
    return _cached("jobs_by_category", _jobs_by_category_data, db)


@router.get("/report")
async def report_data(period: str = Query("weekly"), db: Session = Depends(get_db)):
    """週次/月次レポート"""
    now = datetime.now()

    if period == "monthly":
        periods = []
        for i in range(5, -1, -1):
            dt = now - timedelta(days=30 * i)
            start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if i == 0:
                end = now
            else:
                next_month = (start.month % 12) + 1
                year = start.year + (1 if next_month == 1 else 0)
                end = start.replace(year=year, month=next_month)
            periods.append({"label": start.strftime("%Y/%m"), "start": start, "end": end})
    else:
        periods = []
        for i in range(7, -1, -1):
            start = now - timedelta(weeks=i, days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
            periods.append({"label": start.strftime("%m/%d") + "~", "start": start, "end": end})

    labels, analyzed_counts, sent_counts, replied_counts, costs = [], [], [], [], []
    for p in periods:
        labels.append(p["label"])
        analyzed_counts.append(db.query(func.count(Lead.id)).filter(
            Lead.created_at >= p["start"], Lead.created_at < p["end"],
            Lead.status.notin_(["new", "analyzing", "error", "excluded"]),
        ).scalar() or 0)
        sent_counts.append(db.query(func.count(EmailLog.id)).filter(
            EmailLog.sent_at >= p["start"], EmailLog.sent_at < p["end"], EmailLog.sent_at.isnot(None),
        ).scalar() or 0)
        replied_counts.append(db.query(func.count(Lead.id)).filter(
            Lead.updated_at >= p["start"], Lead.updated_at < p["end"], Lead.status.in_(REPLIED_STATUSES),
        ).scalar() or 0)
        serpapi_cost = db.query(func.sum(SearchJob.serpapi_calls_used)).filter(
            SearchJob.created_at >= p["start"], SearchJob.created_at < p["end"],
        ).scalar() or 0
        costs.append(round(serpapi_cost * 1.5 + sent_counts[-1] * 4.5))

    return {"period": period, "labels": labels, "analyzed": analyzed_counts,
            "sent": sent_counts, "replied": replied_counts, "costs": costs}

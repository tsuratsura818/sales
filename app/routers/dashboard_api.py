import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.lead import Lead
from app.models.email_log import EmailLog
from app.models.search_job import SearchJob

router = APIRouter(prefix="/api/dashboard", tags=["dashboard-api"])

# ファネルで「送信済み以降」とみなすステータス
SENT_STATUSES = ("sent", "replied", "meeting", "closed")
REPLIED_STATUSES = ("replied", "meeting", "closed")
MEETING_STATUSES = ("meeting", "closed")


@router.get("/kpi")
async def kpi_summary(db: Session = Depends(get_db)):
    """KPIサマリー（カード表示用）"""
    total_leads = db.query(func.count(Lead.id)).filter(
        Lead.status != "excluded"
    ).scalar() or 0

    total_sent = db.query(func.count(Lead.id)).filter(
        Lead.status.in_(SENT_STATUSES)
    ).scalar() or 0

    total_replied = db.query(func.count(Lead.id)).filter(
        Lead.status.in_(REPLIED_STATUSES)
    ).scalar() or 0

    total_meeting = db.query(func.count(Lead.id)).filter(
        Lead.status.in_(MEETING_STATUSES)
    ).scalar() or 0

    total_closed = db.query(func.count(Lead.id)).filter(
        Lead.status == "closed"
    ).scalar() or 0

    total_revenue = db.query(func.sum(Lead.deal_amount)).filter(
        Lead.status == "closed",
        Lead.deal_amount.isnot(None),
    ).scalar() or 0

    reply_rate = round(total_replied / total_sent * 100, 1) if total_sent > 0 else 0

    # 今週の送信数
    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_sent = db.query(func.count(EmailLog.id)).filter(
        EmailLog.sent_at >= week_start,
        EmailLog.sent_at.isnot(None),
    ).scalar() or 0

    return {
        "total_leads": total_leads,
        "total_sent": total_sent,
        "total_replied": total_replied,
        "total_meeting": total_meeting,
        "total_closed": total_closed,
        "total_revenue": total_revenue,
        "reply_rate": reply_rate,
        "week_sent": week_sent,
    }


@router.get("/funnel")
async def funnel_data(db: Session = Depends(get_db)):
    """営業ファネルデータ"""
    leads = db.query(Lead).filter(Lead.status != "excluded").all()

    analyzed = sum(1 for l in leads if l.status not in ("new", "analyzing", "error"))
    sent = sum(1 for l in leads if l.status in SENT_STATUSES)
    replied = sum(1 for l in leads if l.status in REPLIED_STATUSES)
    meeting = sum(1 for l in leads if l.status in MEETING_STATUSES)
    closed = sum(1 for l in leads if l.status == "closed")

    values = [analyzed, sent, replied, meeting, closed]
    rates = []
    prev = None
    for v in values:
        if prev is None:
            rates.append(100.0)
        else:
            rates.append(round(v / prev * 100, 1) if prev > 0 else 0)
        prev = v

    return {
        "labels": ["分析完了", "メール送信", "返信あり", "商談", "成約"],
        "values": values,
        "rates": rates,
    }


@router.get("/reply-by-industry")
async def reply_by_industry(db: Session = Depends(get_db)):
    """業種別返信率"""
    leads = db.query(Lead).filter(
        Lead.status.in_(SENT_STATUSES),
        Lead.industry_category.isnot(None),
    ).all()

    stats = {}
    for lead in leads:
        cat = lead.industry_category or "その他"
        if cat not in stats:
            stats[cat] = {"sent": 0, "replied": 0}
        stats[cat]["sent"] += 1
        if lead.status in REPLIED_STATUSES:
            stats[cat]["replied"] += 1

    sorted_items = sorted(stats.items(), key=lambda x: x[1]["sent"], reverse=True)

    return {
        "labels": [c for c, _ in sorted_items],
        "sent": [s["sent"] for _, s in sorted_items],
        "replied": [s["replied"] for _, s in sorted_items],
        "rates": [
            round(s["replied"] / s["sent"] * 100, 1) if s["sent"] > 0 else 0
            for _, s in sorted_items
        ],
    }


@router.get("/reply-by-score")
async def reply_by_score(db: Session = Depends(get_db)):
    """スコア帯別返信率"""
    leads = db.query(Lead).filter(Lead.status.in_(SENT_STATUSES)).all()

    bands = [
        ("0-19", 0, 19),
        ("20-39", 20, 39),
        ("40-59", 40, 59),
        ("60-79", 60, 79),
        ("80+", 80, 999),
    ]

    labels = []
    sent_counts = []
    replied_counts = []
    rates = []
    for label, lo, hi in bands:
        sent = sum(1 for l in leads if lo <= (l.score or 0) <= hi)
        replied = sum(
            1 for l in leads
            if lo <= (l.score or 0) <= hi and l.status in REPLIED_STATUSES
        )
        labels.append(label)
        sent_counts.append(sent)
        replied_counts.append(replied)
        rates.append(round(replied / sent * 100, 1) if sent > 0 else 0)

    return {
        "labels": labels,
        "sent": sent_counts,
        "replied": replied_counts,
        "rates": rates,
    }


ISSUE_LABELS = {
    "no_https": "HTTPS非対応",
    "old_copyright_3yr": "著作権年が古い(3年+)",
    "old_copyright_5yr": "著作権年が古い(5年+)",
    "no_mobile": "モバイル非対応",
    "old_domain_10yr": "ドメイン10年以上",
    "has_flash": "Flash使用",
    "ssl_expiry_90days": "SSL期限切れ間近",
    "low_pagespeed": "低速表示",
    "old_wordpress": "WordPress旧バージョン",
    "no_og_image": "OGP画像なし",
    "no_favicon": "ファビコンなし",
    "table_layout": "テーブルレイアウト",
    "many_missing_alt": "alt属性欠落",
    "no_structured_data": "構造化データなし",
    "no_sitemap": "サイトマップなし",
    "no_robots_txt": "robots.txtなし",
    "no_breadcrumb": "パンくずリストなし",
}


@router.get("/issue-effectiveness")
async def issue_effectiveness(db: Session = Depends(get_db)):
    """問題点別の返信率（効果分析）"""
    leads = db.query(Lead).filter(
        Lead.status.in_(SENT_STATUSES),
        Lead.score_breakdown.isnot(None),
    ).all()

    issue_stats = {}
    for lead in leads:
        try:
            breakdown = json.loads(lead.score_breakdown) if isinstance(lead.score_breakdown, str) else {}
        except Exception:
            breakdown = {}

        is_replied = lead.status in REPLIED_STATUSES
        for key in breakdown:
            if key not in issue_stats:
                issue_stats[key] = {"sent": 0, "replied": 0}
            issue_stats[key]["sent"] += 1
            if is_replied:
                issue_stats[key]["replied"] += 1

    result = []
    for key, s in issue_stats.items():
        if s["sent"] >= 1:
            result.append({
                "key": key,
                "label": ISSUE_LABELS.get(key, key),
                "sent": s["sent"],
                "replied": s["replied"],
                "rate": round(s["replied"] / s["sent"] * 100, 1) if s["sent"] > 0 else 0,
            })
    result.sort(key=lambda x: x["rate"], reverse=True)

    return {
        "issues": result,
        "labels": [r["label"] for r in result],
        "rates": [r["rate"] for r in result],
        "sent_counts": [r["sent"] for r in result],
        "replied_counts": [r["replied"] for r in result],
    }


@router.get("/report")
async def report_data(
    period: str = Query("weekly"),
    db: Session = Depends(get_db),
):
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
            periods.append({
                "label": start.strftime("%Y/%m"),
                "start": start,
                "end": end,
            })
    else:
        periods = []
        for i in range(7, -1, -1):
            start = now - timedelta(weeks=i, days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
            periods.append({
                "label": start.strftime("%m/%d") + "~",
                "start": start,
                "end": end,
            })

    labels = []
    analyzed_counts = []
    sent_counts = []
    replied_counts = []
    costs = []

    for p in periods:
        labels.append(p["label"])

        # 分析済みリード
        analyzed = db.query(func.count(Lead.id)).filter(
            Lead.created_at >= p["start"],
            Lead.created_at < p["end"],
            Lead.status.notin_(["new", "analyzing", "error", "excluded"]),
        ).scalar() or 0
        analyzed_counts.append(analyzed)

        # 送信数
        sent = db.query(func.count(EmailLog.id)).filter(
            EmailLog.sent_at >= p["start"],
            EmailLog.sent_at < p["end"],
            EmailLog.sent_at.isnot(None),
        ).scalar() or 0
        sent_counts.append(sent)

        # 返信数（updated_atベース近似）
        replied = db.query(func.count(Lead.id)).filter(
            Lead.updated_at >= p["start"],
            Lead.updated_at < p["end"],
            Lead.status.in_(REPLIED_STATUSES),
        ).scalar() or 0
        replied_counts.append(replied)

        # コスト（SerpAPI + Claude概算）
        serpapi_cost = db.query(func.sum(SearchJob.serpapi_calls_used)).filter(
            SearchJob.created_at >= p["start"],
            SearchJob.created_at < p["end"],
        ).scalar() or 0
        cost_jpy = round(serpapi_cost * 1.5 + sent * 4.5)
        costs.append(cost_jpy)

    return {
        "period": period,
        "labels": labels,
        "analyzed": analyzed_counts,
        "sent": sent_counts,
        "replied": replied_counts,
        "costs": costs,
    }

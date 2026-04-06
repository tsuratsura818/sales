"""目標管理サービス

目標の作成・更新、実績の自動集計、スナップショット記録
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.goal import Goal, GoalSnapshot
from app.models.lead import Lead
from app.models.email_log import EmailLog

logger = logging.getLogger(__name__)

SENT_STATUSES = ("sent", "replied", "meeting", "closed")
REPLIED_STATUSES = ("replied", "meeting", "closed")
MEETING_STATUSES = ("meeting", "closed")


def get_current_period_keys() -> dict[str, str]:
    """現在の期間キーを返す"""
    now = datetime.now()
    iso = now.isocalendar()
    return {
        "weekly": f"{iso[0]}-W{iso[1]:02d}",
        "monthly": now.strftime("%Y-%m"),
        "quarterly": f"{now.year}-Q{(now.month - 1) // 3 + 1}",
    }


def get_period_range(period_type: str, period_key: str) -> tuple[datetime, datetime]:
    """期間キーから開始日・終了日を算出"""
    if period_type == "weekly":
        # "2026-W15" → ISO week（月曜始まり）
        year, week = period_key.split("-W")
        start = datetime.fromisocalendar(int(year), int(week), 1)  # 月曜
        end = start + timedelta(days=7)
    elif period_type == "monthly":
        # "2026-04"
        start = datetime.strptime(period_key + "-01", "%Y-%m-%d")
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    elif period_type == "quarterly":
        # "2026-Q2"
        year, q = period_key.split("-Q")
        quarter = int(q)
        start_month = (quarter - 1) * 3 + 1
        start = datetime(int(year), start_month, 1)
        end_month = start_month + 3
        if end_month > 12:
            end = datetime(int(year) + 1, end_month - 12, 1)
        else:
            end = datetime(int(year), end_month, 1)
    else:
        start = datetime.now()
        end = start + timedelta(days=7)

    return start, end


def calculate_actuals(db: Session, period_type: str, period_key: str) -> dict:
    """指定期間の実績を集計"""
    start, end = get_period_range(period_type, period_key)

    # リード数（期間内作成、excludedを除く）
    leads_count = db.query(func.count(Lead.id)).filter(
        Lead.created_at >= start,
        Lead.created_at < end,
        Lead.status != "excluded",
    ).scalar() or 0

    # 送信数
    sent_count = db.query(func.count(EmailLog.id)).filter(
        EmailLog.sent_at >= start,
        EmailLog.sent_at < end,
        EmailLog.sent_at.isnot(None),
    ).scalar() or 0

    # 返信数（updated_atベース近似）
    replies_count = db.query(func.count(Lead.id)).filter(
        Lead.updated_at >= start,
        Lead.updated_at < end,
        Lead.status.in_(REPLIED_STATUSES),
    ).scalar() or 0

    # 商談数
    meetings_count = db.query(func.count(Lead.id)).filter(
        Lead.meeting_scheduled_at >= start,
        Lead.meeting_scheduled_at < end,
    ).scalar() or 0

    # 成約数
    closed_count = db.query(func.count(Lead.id)).filter(
        Lead.deal_closed_at >= start,
        Lead.deal_closed_at < end,
    ).scalar() or 0

    # 売上
    revenue = db.query(func.sum(Lead.deal_amount)).filter(
        Lead.deal_closed_at >= start,
        Lead.deal_closed_at < end,
        Lead.deal_amount.isnot(None),
    ).scalar() or 0

    return {
        "leads": leads_count,
        "sent": sent_count,
        "replies": replies_count,
        "meetings": meetings_count,
        "closed": closed_count,
        "revenue": revenue,
    }


def refresh_goal_actuals(db: Session, goal: Goal) -> Goal:
    """目標の実績値を最新に更新"""
    actuals = calculate_actuals(db, goal.period_type, goal.period_key)
    goal.actual_leads = actuals["leads"]
    goal.actual_sent = actuals["sent"]
    goal.actual_replies = actuals["replies"]
    goal.actual_meetings = actuals["meetings"]
    goal.actual_closed = actuals["closed"]
    goal.actual_revenue = actuals["revenue"]
    db.commit()
    return goal


def get_or_create_goal(db: Session, period_type: str, period_key: str) -> Goal:
    """目標を取得、なければ作成"""
    goal = db.query(Goal).filter(
        Goal.period_type == period_type,
        Goal.period_key == period_key,
    ).first()

    if not goal:
        goal = Goal(period_type=period_type, period_key=period_key)
        db.add(goal)
        db.commit()
        db.refresh(goal)

    return goal


def get_current_goals(db: Session) -> list[dict]:
    """現在の全期間の目標と実績を取得"""
    keys = get_current_period_keys()
    results = []

    for ptype, pkey in keys.items():
        goal = get_or_create_goal(db, ptype, pkey)
        goal = refresh_goal_actuals(db, goal)

        metrics = []
        for label, target_field, actual_field, unit in [
            ("リード", "target_leads", "actual_leads", "件"),
            ("送信", "target_sent", "actual_sent", "件"),
            ("返信", "target_replies", "actual_replies", "件"),
            ("商談", "target_meetings", "actual_meetings", "件"),
            ("成約", "target_closed", "actual_closed", "件"),
            ("売上", "target_revenue", "actual_revenue", "円"),
        ]:
            target = getattr(goal, target_field)
            actual = getattr(goal, actual_field)
            pct = round(actual / target * 100, 1) if target > 0 else 0
            metrics.append({
                "label": label,
                "target": target,
                "actual": actual,
                "pct": pct,
                "unit": unit,
            })

        type_labels = {"weekly": "今週", "monthly": "今月", "quarterly": "今四半期"}

        results.append({
            "goal": goal,
            "period_type": ptype,
            "period_key": pkey,
            "period_label": type_labels.get(ptype, ptype),
            "metrics": metrics,
        })

    return results


def take_daily_snapshot(db: Session) -> GoalSnapshot:
    """日次スナップショットを記録"""
    today = datetime.now().strftime("%Y-%m-%d")

    existing = db.query(GoalSnapshot).filter(
        GoalSnapshot.snapshot_date == today
    ).first()
    if existing:
        return existing

    # 全期間の累積
    total_leads = db.query(func.count(Lead.id)).filter(
        Lead.status != "excluded"
    ).scalar() or 0

    total_sent = db.query(func.count(Lead.id)).filter(
        Lead.status.in_(SENT_STATUSES)
    ).scalar() or 0

    total_replies = db.query(func.count(Lead.id)).filter(
        Lead.status.in_(REPLIED_STATUSES)
    ).scalar() or 0

    total_meetings = db.query(func.count(Lead.id)).filter(
        Lead.status.in_(MEETING_STATUSES)
    ).scalar() or 0

    total_closed = db.query(func.count(Lead.id)).filter(
        Lead.status == "closed"
    ).scalar() or 0

    total_revenue = db.query(func.sum(Lead.deal_amount)).filter(
        Lead.status == "closed",
        Lead.deal_amount.isnot(None),
    ).scalar() or 0

    # 前日のスナップショットから日次増分を計算
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    prev = db.query(GoalSnapshot).filter(
        GoalSnapshot.snapshot_date == yesterday
    ).first()

    daily_leads = total_leads - (prev.total_leads if prev else 0)
    daily_sent = total_sent - (prev.total_sent if prev else 0)
    daily_replies = total_replies - (prev.total_replies if prev else 0)

    snapshot = GoalSnapshot(
        snapshot_date=today,
        total_leads=total_leads,
        total_sent=total_sent,
        total_replies=total_replies,
        total_meetings=total_meetings,
        total_closed=total_closed,
        total_revenue=total_revenue,
        daily_leads=max(0, daily_leads),
        daily_sent=max(0, daily_sent),
        daily_replies=max(0, daily_replies),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot

"""目標管理ルーター

GET /goals - 目標管理ページ
GET /api/goals/current - 現在の目標と実績
POST /api/goals - 目標設定/更新
GET /api/goals/snapshots - スナップショット履歴
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.goal import Goal, GoalSnapshot
from app.services.goal_service import (
    get_current_goals,
    get_or_create_goal,
    refresh_goal_actuals,
    take_daily_snapshot,
)

router = APIRouter(tags=["goals"])


def _get_templates():
    from main import templates
    return templates


@router.get("/goals", response_class=HTMLResponse)
async def goals_page(request: Request):
    return _get_templates().TemplateResponse(request, "goals.html", {})


class GoalUpdate(BaseModel):
    period_type: str
    period_key: str
    target_leads: int = 0
    target_sent: int = 0
    target_replies: int = 0
    target_meetings: int = 0
    target_closed: int = 0
    target_revenue: int = 0
    note: str | None = None


@router.get("/api/goals/current")
async def get_goals_current(db: Session = Depends(get_db)):
    """現在の週次/月次/四半期目標と実績"""
    goals = get_current_goals(db)
    return {"goals": goals}


@router.post("/api/goals")
async def upsert_goal(data: GoalUpdate, db: Session = Depends(get_db)):
    """目標を設定/更新"""
    goal = get_or_create_goal(db, data.period_type, data.period_key)
    goal.target_leads = data.target_leads
    goal.target_sent = data.target_sent
    goal.target_replies = data.target_replies
    goal.target_meetings = data.target_meetings
    goal.target_closed = data.target_closed
    goal.target_revenue = data.target_revenue
    if data.note is not None:
        goal.note = data.note
    db.commit()

    goal = refresh_goal_actuals(db, goal)
    return {"success": True, "goal_id": goal.id}


@router.patch("/api/goals/{goal_id}")
async def patch_goal(goal_id: int, data: GoalUpdate, db: Session = Depends(get_db)):
    """目標を部分更新"""
    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        raise HTTPException(status_code=404, detail="目標が見つかりません")

    goal.target_leads = data.target_leads
    goal.target_sent = data.target_sent
    goal.target_replies = data.target_replies
    goal.target_meetings = data.target_meetings
    goal.target_closed = data.target_closed
    goal.target_revenue = data.target_revenue
    if data.note is not None:
        goal.note = data.note
    db.commit()

    goal = refresh_goal_actuals(db, goal)
    return {"success": True}


@router.get("/api/goals/snapshots")
async def get_snapshots(days: int = 30, db: Session = Depends(get_db)):
    """日次スナップショット履歴"""
    snapshots = (
        db.query(GoalSnapshot)
        .order_by(GoalSnapshot.snapshot_date.desc())
        .limit(days)
        .all()
    )
    snapshots.reverse()

    return {
        "snapshots": [
            {
                "date": s.snapshot_date,
                "total_leads": s.total_leads,
                "total_sent": s.total_sent,
                "total_replies": s.total_replies,
                "total_meetings": s.total_meetings,
                "total_closed": s.total_closed,
                "total_revenue": s.total_revenue,
                "daily_leads": s.daily_leads,
                "daily_sent": s.daily_sent,
                "daily_replies": s.daily_replies,
            }
            for s in snapshots
        ]
    }


@router.post("/api/goals/snapshot")
async def create_snapshot(db: Session = Depends(get_db)):
    """手動でスナップショットを取得"""
    snapshot = take_daily_snapshot(db)
    return {"success": True, "date": snapshot.snapshot_date}

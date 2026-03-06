"""今日のスケジュール立案ルーター"""

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc

from app.services import daily_planner, calendar_service, notion_service
from app.database import SessionLocal
from app.models.daily_plan import DailyPlan

router = APIRouter(tags=["today"])

JST = timezone(timedelta(hours=9))


def _get_templates():
    from main import templates
    return templates


@router.get("/today", response_class=HTMLResponse)
async def today_page(request: Request):
    """今日のスケジュールページ"""
    today_str = datetime.now(JST).strftime("%Y-%m-%d")

    cal_status = calendar_service.check_connection()
    notion_status = await notion_service.check_connection()

    db = SessionLocal()
    try:
        existing_plan = (
            db.query(DailyPlan)
            .filter(DailyPlan.plan_date == today_str)
            .order_by(desc(DailyPlan.created_at))
            .first()
        )
        plan_data = None
        generated_at = None
        if existing_plan:
            plan_data = json.loads(existing_plan.plan_json)
            generated_at = existing_plan.created_at.isoformat() if existing_plan.created_at else None
    finally:
        db.close()

    return _get_templates().TemplateResponse("today.html", {
        "request": request,
        "today_str": today_str,
        "cal_connected": cal_status.get("ok", False),
        "cal_error": cal_status.get("error"),
        "notion_connected": notion_status.get("ok", False),
        "notion_error": notion_status.get("error"),
        "plan": plan_data,
        "plan_exists": existing_plan is not None,
        "generated_at": generated_at,
    })


@router.post("/api/today/generate")
async def api_generate_plan():
    """1日のスケジュールをAIで生成"""
    today_str = datetime.now(JST).strftime("%Y-%m-%d")

    context = await daily_planner.gather_context()
    plan = await daily_planner.generate_daily_plan(context)

    db = SessionLocal()
    try:
        record = DailyPlan(
            plan_date=today_str,
            plan_json=json.dumps(plan, ensure_ascii=False),
            context_json=json.dumps(context, ensure_ascii=False, default=str),
            source="manual",
        )
        db.add(record)
        db.commit()
    finally:
        db.close()

    return {"success": True, "plan": plan}


@router.get("/api/today/calendar")
async def api_get_calendar():
    """Googleカレンダーの予定を返す"""
    status = calendar_service.check_connection()
    if not status.get("ok"):
        return {"connected": False, "error": status.get("error")}
    return {
        "connected": True,
        "today": calendar_service.get_today_events(),
        "week": calendar_service.get_week_events(),
    }


@router.post("/api/today/send-line")
async def api_send_line():
    """最新のプランをLINEに送信"""
    from app.services import line_service

    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        plan_record = (
            db.query(DailyPlan)
            .filter(DailyPlan.plan_date == today_str)
            .order_by(desc(DailyPlan.created_at))
            .first()
        )
        if not plan_record:
            return {"success": False, "error": "今日のプランがありません。先に生成してください。"}

        plan = json.loads(plan_record.plan_json)
        text = daily_planner.format_plan_for_line(plan)
        await line_service.push_text_message(text)

        plan_record.line_sent = 1
        db.commit()
        return {"success": True}
    finally:
        db.close()

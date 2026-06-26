"""今日のスケジュール立案ルーター"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import desc

from app.services import daily_planner, calendar_service, notion_service
from app.database import SessionLocal
from app.models.daily_plan import DailyPlan
from app.models.app_settings import AppSettings

router = APIRouter(tags=["today"])

JST = timezone(timedelta(hours=9))


def _get_templates():
    from main import templates
    return templates


def _get_app_settings(db) -> AppSettings:
    """AppSettings を取得（なければ作成）"""
    row = db.query(AppSettings).first()
    if not row:
        row = AppSettings(daily_plan_enabled=False, daily_plan_hour_jst=8)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/today", response_class=HTMLResponse)
async def today_page(request: Request):
    """今日のスケジュールページ"""
    today_str = datetime.now(JST).strftime("%Y-%m-%d")

    cal_status = calendar_service.check_connection()
    notion_status = await notion_service.check_connection()

    # カレンダー予定取得
    cal_events = []
    if cal_status.get("ok"):
        try:
            cal_events = calendar_service.get_today_events()
        except Exception:
            pass

    # 今日やるべきNotionタスク（当日期日 + 期限切れ、完了は除く）
    today_tasks: list[dict] = []
    active_projects: list[dict] = []
    if notion_status.get("ok"):
        try:
            all_tasks = await notion_service.list_tasks()
            for t in all_tasks:
                due = t.get("due_date")
                if not due or t.get("status") == "完了":
                    continue
                if due <= today_str:
                    t = {**t, "overdue": due < today_str}
                    today_tasks.append(t)
            # 期限切れを先に、その中で期日昇順
            today_tasks.sort(key=lambda x: (not x["overdue"], x.get("due_date") or ""))
        except Exception:
            today_tasks = []

        # アクティブ案件（案件化ステータス）。案件は納期より「進行中のもの」を把握する
        try:
            projects = await notion_service.list_projects()
            active_projects = [p for p in projects if p.get("status") == "案件化"]
            active_projects.sort(key=lambda x: (x.get("client") or "", x.get("name") or ""))
        except Exception:
            active_projects = []

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
            if existing_plan.created_at:
                utc_time = existing_plan.created_at.replace(tzinfo=timezone.utc)
                jst_time = utc_time.astimezone(JST)
                generated_at = jst_time.isoformat()

        app_cfg = _get_app_settings(db)
        daily_plan_enabled = app_cfg.daily_plan_enabled
        daily_plan_hour = app_cfg.daily_plan_hour_jst
        task_reminder_enabled = getattr(app_cfg, "task_reminder_enabled", False)
        task_reminder_hour = getattr(app_cfg, "task_reminder_hour_jst", 8)
        wip_reminder_enabled = getattr(app_cfg, "wip_reminder_enabled", False)
        wip_reminder_hour = getattr(app_cfg, "wip_reminder_hour_jst", 9)
        wip_reminder_minute = getattr(app_cfg, "wip_reminder_minute_jst", 5)
        weekly_outreach_enabled = getattr(app_cfg, "weekly_outreach_enabled", False)
        weekly_outreach_weekday = getattr(app_cfg, "weekly_outreach_weekday", 0)
        weekly_outreach_hour = getattr(app_cfg, "weekly_outreach_hour_jst", 9)
        weekly_outreach_send_cap = getattr(app_cfg, "weekly_outreach_send_cap", 50)
        weekly_outreach_last_week = getattr(app_cfg, "weekly_outreach_last_week", None)

    finally:
        db.close()

    return _get_templates().TemplateResponse(request, "today.html", {
        "today_str": today_str,
        "cal_connected": cal_status.get("ok", False),
        "cal_error": cal_status.get("error"),
        "notion_connected": notion_status.get("ok", False),
        "notion_error": notion_status.get("error"),
        "plan": plan_data,
        "plan_exists": existing_plan is not None,
        "generated_at": generated_at,
        "daily_plan_enabled": daily_plan_enabled,
        "daily_plan_hour": daily_plan_hour,
        "task_reminder_enabled": task_reminder_enabled,
        "task_reminder_hour": task_reminder_hour,
        "wip_reminder_enabled": wip_reminder_enabled,
        "wip_reminder_hour": wip_reminder_hour,
        "wip_reminder_minute": wip_reminder_minute,
        "weekly_outreach_enabled": weekly_outreach_enabled,
        "weekly_outreach_weekday": weekly_outreach_weekday,
        "weekly_outreach_hour": weekly_outreach_hour,
        "weekly_outreach_send_cap": weekly_outreach_send_cap,
        "weekly_outreach_last_week": weekly_outreach_last_week,
        "cal_events": cal_events,
        "today_tasks": today_tasks,
        "active_projects": active_projects,
    })


@router.post("/api/today/generate")
async def api_generate_plan():
    """1日のスケジュールをAI(API)で生成（フォールバック用）"""
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


# ===== ローカルClaude(ブリッジ)用: prepare → (ブラウザがbridge実行) → save =====

@router.post("/api/today/plan-prepare")
async def api_plan_prepare():
    """スケジュール生成用プロンプトを返す（claude実行はブラウザ側のローカルブリッジ）"""
    context = await daily_planner.gather_context()
    prompt = daily_planner.build_plan_prompt(context)
    return {"prompt": prompt, "context": context}


class PlanSaveRequest(BaseModel):
    raw: str
    context: dict | None = None


@router.post("/api/today/plan-save")
async def api_plan_save(data: PlanSaveRequest):
    """ローカルClaudeの出力を解釈してプランを保存"""
    try:
        plan = daily_planner.parse_plan(data.raw)
    except Exception as e:
        return {"success": False, "error": f"プラン解釈に失敗: {e}"}
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        record = DailyPlan(
            plan_date=today_str,
            plan_json=json.dumps(plan, ensure_ascii=False),
            context_json=json.dumps(data.context or {}, ensure_ascii=False, default=str),
            source="manual-local",
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


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    """月間カレンダーページ"""
    import calendar as cal_mod

    now_jst = datetime.now(JST)
    year = int(request.query_params.get("year", now_jst.year))
    month = int(request.query_params.get("month", now_jst.month))

    cal_status = calendar_service.check_connection()
    events = []
    if cal_status.get("ok"):
        try:
            events = calendar_service.get_month_events(year, month)
        except Exception:
            pass

    # カレンダーグリッド生成（月曜始まり）
    first_day = datetime(year, month, 1, tzinfo=JST)
    _, last_date = cal_mod.monthrange(year, month)
    start_weekday = first_day.weekday()

    weeks: list[list[dict]] = []
    current_date = first_day - timedelta(days=start_weekday)

    while True:
        week = []
        for _ in range(7):
            day_str = current_date.strftime("%Y-%m-%d")
            day_events = []
            for ev in events:
                ev_date = ev["start"][:10] if ev["start"] else ""
                if ev_date == day_str:
                    day_events.append(ev)
            # 終日イベントを先に
            day_events.sort(key=lambda e: (not e["all_day"], e["start"]))

            week.append({
                "date": current_date,
                "day": current_date.day,
                "is_today": current_date.date() == now_jst.date(),
                "is_current_month": current_date.month == month,
                "events": day_events,
                "weekday": current_date.weekday(),
            })
            current_date += timedelta(days=1)
        weeks.append(week)
        if current_date.month != month and current_date.weekday() == 0:
            break

    # 前月・翌月
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    return _get_templates().TemplateResponse(request, "calendar.html", {
        "year": year,
        "month": month,
        "weeks": weeks,
        "cal_connected": cal_status.get("ok", False),
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
    })


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


@router.get("/api/today/settings")
async def api_get_settings():
    """日次プラン設定を取得"""
    db = SessionLocal()
    try:
        cfg = _get_app_settings(db)
        return {
            "daily_plan_enabled": cfg.daily_plan_enabled,
            "daily_plan_hour": cfg.daily_plan_hour_jst,
            "task_reminder_enabled": getattr(cfg, "task_reminder_enabled", False),
            "task_reminder_hour": getattr(cfg, "task_reminder_hour_jst", 8),
            "wip_reminder_enabled": getattr(cfg, "wip_reminder_enabled", False),
            "wip_reminder_hour": getattr(cfg, "wip_reminder_hour_jst", 9),
            "wip_reminder_minute": getattr(cfg, "wip_reminder_minute_jst", 5),
            "weekly_outreach_enabled": getattr(cfg, "weekly_outreach_enabled", False),
            "weekly_outreach_weekday": getattr(cfg, "weekly_outreach_weekday", 0),
            "weekly_outreach_hour": getattr(cfg, "weekly_outreach_hour_jst", 9),
            "weekly_outreach_send_cap": getattr(cfg, "weekly_outreach_send_cap", 50),
            "weekly_outreach_last_week": getattr(cfg, "weekly_outreach_last_week", None),
        }
    finally:
        db.close()


@router.post("/api/today/send-wip-reminder")
async def api_send_wip_reminder():
    """進行中タスクの残リマインドを今すぐLINE送信（テスト用）"""
    from app.tasks.wip_reminder_scheduler import send_wip_reminder
    try:
        sent = await send_wip_reminder()
        if sent:
            return {"success": True}
        return {"success": False, "error": "進行中のタスクがありません"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/today/run-weekly-outreach")
async def api_run_weekly_outreach():
    """週次自動アウトリーチを今すぐ1回実行（テスト用）。重いのでバックグラウンド起動し即返す。"""
    from app.tasks.weekly_outreach_scheduler import run_weekly_outreach
    asyncio.create_task(run_weekly_outreach())
    return {"success": True, "message": "アウトリーチを開始しました。完了時にLINE通知します（数分かかります）。"}


@router.post("/api/today/send-task-reminder")
async def api_send_task_reminder():
    """タスク期限リマインドを今すぐLINE送信（テスト用）"""
    from app.tasks.task_reminder_scheduler import send_task_reminder
    try:
        sent = await send_task_reminder()
        if sent:
            return {"success": True}
        return {"success": False, "error": "対象のタスク（今日が期日/期限切れ）がありません"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.patch("/api/today/settings")
async def api_update_settings(request: Request):
    """日次プラン設定を更新"""
    body = await request.json()
    db = SessionLocal()
    try:
        cfg = _get_app_settings(db)
        if "daily_plan_enabled" in body:
            cfg.daily_plan_enabled = bool(body["daily_plan_enabled"])
        if "daily_plan_hour" in body:
            hour = int(body["daily_plan_hour"])
            if 0 <= hour <= 23:
                cfg.daily_plan_hour_jst = hour
        if "task_reminder_enabled" in body:
            cfg.task_reminder_enabled = bool(body["task_reminder_enabled"])
        if "task_reminder_hour" in body:
            hour = int(body["task_reminder_hour"])
            if 0 <= hour <= 23:
                cfg.task_reminder_hour_jst = hour
        if "wip_reminder_enabled" in body:
            cfg.wip_reminder_enabled = bool(body["wip_reminder_enabled"])
        if "wip_reminder_hour" in body:
            hour = int(body["wip_reminder_hour"])
            if 0 <= hour <= 23:
                cfg.wip_reminder_hour_jst = hour
        if "wip_reminder_minute" in body:
            minute = int(body["wip_reminder_minute"])
            if 0 <= minute <= 59:
                cfg.wip_reminder_minute_jst = minute
        if "weekly_outreach_enabled" in body:
            cfg.weekly_outreach_enabled = bool(body["weekly_outreach_enabled"])
        if "weekly_outreach_weekday" in body:
            wd = int(body["weekly_outreach_weekday"])
            if 0 <= wd <= 6:
                cfg.weekly_outreach_weekday = wd
        if "weekly_outreach_hour" in body:
            hour = int(body["weekly_outreach_hour"])
            if 0 <= hour <= 23:
                cfg.weekly_outreach_hour_jst = hour
        if "weekly_outreach_send_cap" in body:
            cap = int(body["weekly_outreach_send_cap"])
            if 1 <= cap <= 500:
                cfg.weekly_outreach_send_cap = cap
        db.commit()
        return {
            "success": True,
            "daily_plan_enabled": cfg.daily_plan_enabled,
            "daily_plan_hour": cfg.daily_plan_hour_jst,
            "task_reminder_enabled": cfg.task_reminder_enabled,
            "task_reminder_hour": cfg.task_reminder_hour_jst,
            "wip_reminder_enabled": cfg.wip_reminder_enabled,
            "wip_reminder_hour": cfg.wip_reminder_hour_jst,
            "wip_reminder_minute": cfg.wip_reminder_minute_jst,
            "weekly_outreach_enabled": cfg.weekly_outreach_enabled,
            "weekly_outreach_weekday": cfg.weekly_outreach_weekday,
            "weekly_outreach_hour": cfg.weekly_outreach_hour_jst,
            "weekly_outreach_send_cap": cfg.weekly_outreach_send_cap,
        }
    finally:
        db.close()

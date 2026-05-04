# 全 import より前に .env を読み込む(mailforge_client 等が os.getenv で参照するため)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import init_db, SessionLocal
from app.tasks import task_queue
from app.tasks.followup_scheduler import followup_scheduler
from app.tasks.job_monitor import job_monitor
from app.tasks.keep_alive import keep_alive
from app.tasks.daily_plan_scheduler import daily_plan_scheduler
from app.tasks.reply_checker import reply_checker
from app.tasks.bounce_checker import bounce_checker
from app.tasks.weekly_report_scheduler import weekly_report_scheduler
from app.tasks.heartbeat_checker import heartbeat_checker
from app.tasks.health_check_scheduler import health_check_scheduler
from app.routers import dashboard, search, leads, emails, events, followups, competitors, dashboard_api, portfolios, jobs, line_webhook, projects, today, memos, mail, goals, pipeline, webhook, tracking, clients

STATUS_JA = {
    # リードステータス
    "new": "新規",
    "analyzing": "分析中",
    "analyzed": "分析済み",
    "email_generated": "メール生成済み",
    "sent": "送信済み",
    "replied": "返信あり",
    "meeting": "商談中",
    "closed": "成約",
    "error": "エラー",
    "excluded": "対象外",
    # フォローアップステータス
    "active": "フォローアップ中",
    "paused": "一時停止",
    "stopped": "停止",
    # ジョブステータス
    "pending": "待機中",
    "running": "実行中",
    "completed": "完了",
    "failed": "失敗",
    # 案件モニターステータス
    "notified": "通知済み",
    "approved": "承認済み",
    "generating": "生成中",
    "review": "確認待ち",
    "applying": "応募中",
    "applied": "応募完了",
    "skipped": "スキップ",
    "expired": "期限切れ",
}


def status_ja(value: str) -> str:
    return STATUS_JA.get(value, value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時
    init_db()
    worker_task = asyncio.create_task(task_queue.worker())
    scheduler_task = asyncio.create_task(followup_scheduler())
    monitor_task = asyncio.create_task(job_monitor())
    keepalive_task = asyncio.create_task(keep_alive())
    daily_plan_task = asyncio.create_task(daily_plan_scheduler())
    reply_task = asyncio.create_task(reply_checker())
    report_task = asyncio.create_task(weekly_report_scheduler())
    bounce_task = asyncio.create_task(bounce_checker())
    heartbeat_task = asyncio.create_task(heartbeat_checker())
    health_task = asyncio.create_task(health_check_scheduler())
    yield
    # 終了時
    all_tasks = [worker_task, scheduler_task, monitor_task, keepalive_task, daily_plan_task, reply_task, report_task, bounce_task, heartbeat_task, health_task]
    for task in all_tasks:
        task.cancel()
    for task in all_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="SellBuddy", lifespan=lifespan)

# Basic Auth（BASIC_AUTH_USER / BASIC_AUTH_PASS 未設定なら素通し）
from app.middleware.basic_auth import BasicAuthMiddleware  # noqa: E402
app.add_middleware(BasicAuthMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2テンプレートにフィルターを登録
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["status_ja"] = status_ja

app.include_router(dashboard.router)
app.include_router(search.router)
app.include_router(leads.router)
app.include_router(emails.router)
app.include_router(events.router)
app.include_router(followups.router)
app.include_router(competitors.router)
app.include_router(dashboard_api.router)
app.include_router(portfolios.router)
app.include_router(jobs.router)
app.include_router(line_webhook.router)
app.include_router(projects.router)
app.include_router(today.router)
app.include_router(memos.router)
app.include_router(mail.router)
app.include_router(goals.router)
app.include_router(pipeline.router)
app.include_router(webhook.router)
app.include_router(clients.router)
app.include_router(tracking.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/monitor/status")
async def monitor_status():
    """案件モニターの稼働状況を返す"""
    from app.models.monitor_log import MonitorLog
    from sqlalchemy import desc
    db_session = SessionLocal()
    try:
        logs = db_session.query(MonitorLog).order_by(desc(MonitorLog.run_at)).limit(20).all()
        return {
            "total_runs": db_session.query(MonitorLog).count(),
            "recent": [
                {
                    "id": log.id,
                    "run_at": log.run_at.isoformat() if log.run_at else None,
                    "status": log.status,
                    "message": log.message,
                    "cw_count": log.cw_count,
                    "lc_count": log.lc_count,
                    "notified_count": log.notified_count,
                    "duration_sec": log.duration_sec,
                }
                for log in logs
            ],
        }
    finally:
        db_session.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)

"""Claude AI による 1日のタスク立案サービス"""

import json
import re
import logging
from datetime import datetime, timedelta, timezone

import anthropic
from app.config import get_settings
from app.services import notion_service, calendar_service
from app.database import SessionLocal
from app.models.job_listing import JobListing

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

PLANNER_SYSTEM_PROMPT = """あなたはフリーランスのWeb制作者・デザイナーの生産性アシスタントAIです。
1日のスケジュールを立案してください。

## ルール
- カレンダーの予定（会議・打ち合わせ等）はそのまま固定枠として配置
- 空き時間にNotionのタスクや案件作業を優先度順に割り当て
- 高優先度・期日が近いタスクを先に配置
- 集中作業（コーディング等）は午前中の連続した時間に配置
- 昼休憩（12:00-13:00）を確保
- 1日の稼働は9:00-18:00を基本とする（柔軟に調整可）
- 各タスクには推定所要時間を付ける
- 案件モニターで注目案件がある場合は、提案文作成の時間も確保

## 出力フォーマット（JSON）
{
  "greeting": "おはようございます！今日のスケジュールを提案します。",
  "summary": "今日は2件の打ち合わせがあり、残りの時間でXXXに集中できます。",
  "schedule": [
    {
      "time": "09:00-10:30",
      "title": "XX案件 コーディング",
      "type": "work",
      "priority": "high",
      "note": "期限が近いため優先"
    }
  ],
  "tips": ["集中作業は午前中に。"],
  "unscheduled": ["低優先度タスクA"]
}

typeは "work", "meeting", "break", "admin" のいずれか。
priorityは "fixed"(カレンダー予定), "high", "medium", "low" のいずれか。
"""


async def gather_context() -> dict:
    """全データソースから情報を収集"""
    today_events: list[dict] = []
    week_events: list[dict] = []
    cal_connected = False
    try:
        cal_status = calendar_service.check_connection()
        if cal_status["ok"]:
            cal_connected = True
            today_events = calendar_service.get_today_events()
            week_events = calendar_service.get_week_events()
    except Exception as e:
        logger.warning(f"カレンダー取得失敗: {e}")

    projects: list[dict] = []
    tasks: list[dict] = []
    notion_connected = False
    try:
        conn = await notion_service.check_connection()
        if conn["ok"]:
            notion_connected = True
            all_projects = await notion_service.list_projects()
            projects = [
                p for p in all_projects
                if p.get("status") in ("進行中", "受注", "商談中", "提案中")
            ]
            tasks_todo = await notion_service.list_tasks(status="未着手")
            tasks_wip = await notion_service.list_tasks(status="進行中")
            tasks = tasks_todo + tasks_wip
    except Exception as e:
        logger.warning(f"Notion取得失敗: {e}")

    notified_jobs: list[dict] = []
    try:
        db = SessionLocal()
        jobs = (
            db.query(JobListing)
            .filter(JobListing.status == "notified")
            .order_by(JobListing.created_at.desc())
            .limit(5)
            .all()
        )
        notified_jobs = [
            {
                "title": j.title,
                "platform": j.platform,
                "match_score": j.match_score,
                "budget_min": j.budget_min,
                "budget_max": j.budget_max,
                "url": j.url,
            }
            for j in jobs
        ]
        db.close()
    except Exception as e:
        logger.warning(f"DB案件取得失敗: {e}")

    return {
        "date": datetime.now(JST).strftime("%Y年%m月%d日 (%A)"),
        "calendar_connected": cal_connected,
        "today_events": today_events,
        "week_events": week_events,
        "notion_connected": notion_connected,
        "projects": projects,
        "tasks": tasks,
        "notified_jobs": notified_jobs,
    }


async def generate_daily_plan(context: dict | None = None) -> dict:
    """Claude AI で1日のスケジュールを立案"""
    settings = get_settings()
    if context is None:
        context = await gather_context()

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    parts = [f"日付: {context['date']}\n"]

    if context["today_events"]:
        parts.append("## 今日のカレンダー予定")
        for ev in context["today_events"]:
            time_str = ev["start"] if not ev["all_day"] else "終日"
            parts.append(f"- {time_str}: {ev['summary']}")
        parts.append("")

    if context["week_events"]:
        parts.append("## 今週のカレンダー予定（参考）")
        for ev in context["week_events"][:10]:
            parts.append(f"- {ev['start']}: {ev['summary']}")
        parts.append("")

    if context["projects"]:
        parts.append("## 進行中の案件")
        for p in context["projects"]:
            amount = f" ({p['amount']:,}円)" if p.get("amount") else ""
            deadline = f" 期限:{p['end_date']}" if p.get("end_date") else ""
            parts.append(f"- [{p['status']}] {p['name']}{amount}{deadline}")
        parts.append("")

    if context["tasks"]:
        parts.append("## 未完了タスク")
        for t in context["tasks"]:
            prio = f"[{t['priority']}]" if t.get("priority") else ""
            due = f" 期限:{t['due_date']}" if t.get("due_date") else ""
            parts.append(f"- {prio} {t['name']}{due} ({t['status']})")
        parts.append("")

    if context["notified_jobs"]:
        parts.append("## 注目案件（未対応）")
        for j in context["notified_jobs"]:
            budget = ""
            if j.get("budget_min") and j.get("budget_max"):
                budget = f" {j['budget_min']:,}〜{j['budget_max']:,}円"
            parts.append(
                f"- [{j['platform']}] {j['title']}{budget} (マッチ度:{j['match_score']}点)"
            )
        parts.append("")

    if not context["today_events"] and not context["tasks"] and not context["projects"]:
        parts.append("※ カレンダー・Notionともにデータがありません。一般的なフリーランスの1日のスケジュールを提案してください。")

    user_prompt = "\n".join(parts) + "\n上記の情報をもとに、今日の最適なスケジュールをJSON形式で提案してください。"

    try:
        message = await client.messages.create(
            model=settings.CLAUDE_MODEL_EVAL,
            max_tokens=2048,
            messages=[{"role": "user", "content": user_prompt}],
            system=PLANNER_SYSTEM_PROMPT,
        )

        content = message.content[0].text
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            plan = json.loads(json_match.group())
            plan["generated_at"] = datetime.now(JST).isoformat()
            return plan
    except Exception as e:
        logger.error(f"スケジュール生成エラー: {e}")

    return {
        "greeting": "スケジュール生成に失敗しました。",
        "summary": "データの取得またはAI生成でエラーが発生しました。",
        "schedule": [],
        "tips": [],
        "unscheduled": [],
        "generated_at": datetime.now(JST).isoformat(),
    }


def format_plan_for_line(plan: dict) -> str:
    """LINE送信用テキストフォーマット"""
    lines = [
        plan.get("greeting", "おはようございます！"),
        "",
        plan.get("summary", ""),
        "",
        "--- 今日のスケジュール ---",
    ]

    type_emoji = {"meeting": "📅", "work": "💻", "break": "☕", "admin": "📋"}

    for item in plan.get("schedule", []):
        emoji = type_emoji.get(item.get("type"), "▶️")
        prio_mark = " 🔴" if item.get("priority") == "high" else ""
        lines.append(f"{emoji} {item['time']}  {item['title']}{prio_mark}")
        if item.get("note"):
            lines.append(f"   └ {item['note']}")

    if plan.get("tips"):
        lines.append("")
        lines.append("💡 Tips:")
        for tip in plan["tips"]:
            lines.append(f"  ・{tip}")

    if plan.get("unscheduled"):
        lines.append("")
        lines.append("📌 今日中でなくてもOK:")
        for item in plan["unscheduled"]:
            lines.append(f"  ・{item}")

    return "\n".join(lines)

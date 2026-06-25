"""秘書AIチャット: ローカルの claude CLI でユーザー依頼を解釈し、タスク操作を実行する。

本番(Render)では claude CLI が無いため is_available()=False。呼び出し側で graceful degrade。
LLM には現在のタスク/案件一覧(ID付き)を渡し、{reply, actions[]} のJSONを返させる。
actions をこちら側で実行し、結果を reply と共に返す。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from app.services import local_claude, notion_service

log = logging.getLogger("assistant")
JST = timezone(timedelta(hours=9))

SYSTEM_PROMPT = (
    "あなたは営業ツール『SellBuddy』の秘書AIです。ユーザーの依頼を理解し、"
    "タスク・案件の操作を行います。必ず指定のJSON形式のみで回答してください。"
)


def _build_prompt(messages: list[dict], tasks: list[dict], projects: list[dict]) -> str:
    today = datetime.now(JST).strftime("%Y-%m-%d (%a)")
    pj_map = {p["id"]: p.get("name") for p in projects}

    def task_line(t: dict) -> dict:
        pids = t.get("project_ids") or []
        return {
            "id": t["id"], "name": t.get("name"), "status": t.get("status"),
            "priority": t.get("priority"), "due_date": t.get("due_date"),
            "project": pj_map.get(pids[0]) if pids else None,
        }

    task_json = json.dumps([task_line(t) for t in tasks], ensure_ascii=False)
    proj_json = json.dumps(
        [{"id": p["id"], "name": p.get("name"), "status": p.get("status")}
         for p in projects if p.get("status") not in ("完了", "失注")],
        ensure_ascii=False,
    )
    convo = "\n".join(
        f"{'ユーザー' if m.get('role') == 'user' else '秘書'}: {m.get('content', '')}"
        for m in messages[-8:]
    )

    return f"""今日: {today}

【現在のタスク一覧(JSON)】
{task_json}

【案件一覧(進行中のもの, JSON)】
{proj_json}

【会話履歴】
{convo}

上記を踏まえ、最新のユーザー発言に応えてください。
タスク/案件を操作する場合は actions に入れてください。雑談や質問なら actions は空配列に。

使えるアクション(type と必要フィールド):
- {{"type":"set_status","task_id":"<id>","status":"未着手|進行中|外注対応|確認中|完了"}}
- {{"type":"complete","task_id":"<id>"}}  # status を完了にする短縮
- {{"type":"set_priority","task_id":"<id>","priority":"高|中|低"}}
- {{"type":"set_due","task_id":"<id>","due_date":"YYYY-MM-DD" または null}}
- {{"type":"create_task","name":"...","project_id":"<id>|null","status":"未着手","priority":"中","due_date":"YYYY-MM-DD|null"}}
- {{"type":"delete","task_id":"<id>"}}  # アーカイブ(復元可)

注意:
- task_id / project_id は必ず上記一覧の実在IDを使う。名前で言われたら一覧から最も一致するものを選ぶ。
- 一致が曖昧/複数候補なら actions は空にして、reply で候補を挙げて確認する。
- 日付は今日を基準に YYYY-MM-DD で。
- reply はユーザーへの自然な日本語の返答(実行した内容を簡潔に報告)。

必ず次のJSONのみを出力(前後に文章やコードフェンス不要):
{{"reply":"<日本語の返答>","actions":[ ... ]}}"""


async def _execute_action(a: dict) -> dict:
    t = a.get("type")
    try:
        if t in ("complete", "set_status"):
            status = "完了" if t == "complete" else a.get("status")
            await notion_service.update_task(a["task_id"], {"status": status})
            return {"ok": True, "type": t, "status": status}
        if t == "set_priority":
            await notion_service.update_task(a["task_id"], {"priority": a["priority"]})
            return {"ok": True, "type": t}
        if t == "set_due":
            await notion_service.update_task(a["task_id"], {"due_date": a.get("due_date")})
            return {"ok": True, "type": t}
        if t == "create_task":
            task = await notion_service.create_task(
                name=a["name"], project_id=a.get("project_id") or None,
                status=a.get("status") or "未着手", priority=a.get("priority") or "中",
                due_date=a.get("due_date") or None,
            )
            return {"ok": True, "type": t, "task_id": task.get("id")}
        if t == "delete":
            await notion_service.archive_task(a["task_id"])
            return {"ok": True, "type": t}
        return {"ok": False, "type": t, "error": "未知のアクション"}
    except Exception as e:
        log.error(f"action実行失敗 {a}: {e}")
        return {"ok": False, "type": t, "error": str(e)}


async def chat(messages: list[dict]) -> dict:
    """会話履歴を受け取り、秘書の返答とアクション実行結果を返す。"""
    if not local_claude.is_available():
        return {
            "reply": "この秘書チャットは、SellBuddy をローカル(自分のPC)で起動した時だけ使えます。"
                     "本番(クラウド)では claude CLI が無いため利用できません。",
            "executed": [], "available": False,
        }

    conn = await notion_service.check_connection()
    tasks, projects = [], []
    if conn["ok"]:
        tasks = await notion_service.list_tasks()
        projects = await notion_service.list_projects()

    prompt = _build_prompt(messages, tasks, projects)
    try:
        raw = await local_claude.invoke(prompt, system_prompt=SYSTEM_PROMPT, timeout=120)
        data = local_claude.extract_json(raw)
    except Exception as e:
        log.error(f"秘書チャット失敗: {e}")
        return {"reply": f"うまく処理できませんでした（{e}）。もう一度お願いします。",
                "executed": [], "available": True}

    reply = data.get("reply") or "（応答なし）"
    actions = data.get("actions") or []
    executed = []
    for a in actions:
        if isinstance(a, dict) and a.get("type"):
            executed.append(await _execute_action(a))

    return {"reply": reply, "executed": executed, "available": True,
            "changed": any(e.get("ok") for e in executed)}

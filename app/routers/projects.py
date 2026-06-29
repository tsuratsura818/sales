"""案件管理ルーター（Notion連携）"""

import urllib.parse

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from typing import Optional

from app.services import notion_service
from app.database import SessionLocal
from app.models.task_attachment import TaskAttachment
from app.models.recurring_task import RecurringTask

router = APIRouter(tags=["projects"])

# 添付ファイル制約
MAX_ATTACH_SIZE = 15 * 1024 * 1024  # 15MB
ALLOWED_ATTACH_TYPES = {
    "application/pdf",
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
}
ALLOWED_ATTACH_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _get_templates():
    from main import templates
    return templates


# ========== HTMLページ ==========

@router.get("/projects", response_class=HTMLResponse)
async def projects_page(request: Request):
    """案件ボード（カンバン）ページ"""
    conn = await notion_service.check_connection()
    projects = []
    if conn["ok"]:
        projects = await notion_service.list_projects()
    resp = _get_templates().TemplateResponse(request, "projects.html", {
        "projects": projects,
        "statuses": notion_service.PROJECT_STATUSES,
        "contract_types": notion_service.CONTRACT_TYPES,
        "billing_cycles": notion_service.BILLING_CYCLES,
        "connected": conn["ok"],
        "error": conn.get("error"),
    })
    # 保存直後に古い内容が表示されないようキャッシュ無効化
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    """タスク一覧ページ（全案件横断）"""
    conn = await notion_service.check_connection()
    projects = []
    tasks = []
    if conn["ok"]:
        projects = await notion_service.list_projects()
        tasks = await notion_service.list_tasks()
        # 各タスクの添付ファイル件数を付与（📎バッジ用）
        try:
            from sqlalchemy import func
            db = SessionLocal()
            try:
                rows = (
                    db.query(TaskAttachment.task_id, func.count(TaskAttachment.id))
                    .group_by(TaskAttachment.task_id)
                    .all()
                )
                counts = {tid: c for tid, c in rows}
            finally:
                db.close()
            for t in tasks:
                t["attachment_count"] = counts.get(t["id"], 0)
        except Exception:
            for t in tasks:
                t["attachment_count"] = 0
    return _get_templates().TemplateResponse(request, "tasks.html", {
        "projects": projects,
        "tasks": tasks,
        "statuses": notion_service.TASK_STATUSES,
        "priorities": notion_service.TASK_PRIORITIES,
        "project_statuses": notion_service.PROJECT_STATUSES,
        "contract_types": notion_service.CONTRACT_TYPES,
        "connected": conn["ok"],
        "error": conn.get("error"),
    })


@router.get("/gantt", response_class=HTMLResponse)
async def gantt_page(request: Request):
    """ガントチャートページ"""
    conn = await notion_service.check_connection()
    projects = []
    tasks = []
    if conn["ok"]:
        projects = await notion_service.list_projects()
        tasks = await notion_service.list_tasks()
    return _get_templates().TemplateResponse(request, "gantt.html", {
        "projects": projects,
        "tasks": tasks,
        "connected": conn["ok"],
        "error": conn.get("error"),
    })


# ========== 案件 API ==========

class ProjectCreate(BaseModel):
    name: str
    status: str = "提案前"
    client: str = ""
    amount: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    url: str = ""
    lead_id: str = ""
    memo: str = ""
    contract_type: str = "単発"
    billing_cycle: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    client: Optional[str] = None
    amount: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    url: Optional[str] = None
    memo: Optional[str] = None
    contract_type: Optional[str] = None
    billing_cycle: Optional[str] = None


@router.get("/api/projects")
async def api_list_projects(status: Optional[str] = Query(None)):
    """案件一覧API"""
    try:
        projects = await notion_service.list_projects(status=status)
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 注意: 固定パスのGETは /api/projects/{project_id} より前に定義すること
# （後に置くと {project_id} に先取りされ "monthly-summary" 等がNotion問い合わせされ500になる）
@router.get("/api/projects/monthly-summary")
async def api_monthly_summary(month: Optional[str] = Query(None)):
    """月別の継続案件サマリー"""
    try:
        projects = await notion_service.list_projects()
        retainer = [p for p in projects if p.get("contract_type") == "継続"]
        onetime = [p for p in projects if p.get("contract_type") != "継続"]

        retainer_revenue = sum(p.get("amount") or 0 for p in retainer)
        onetime_revenue = sum(p.get("amount") or 0 for p in onetime)

        return {
            "retainer_count": len(retainer),
            "retainer_revenue": retainer_revenue,
            "onetime_count": len(onetime),
            "onetime_revenue": onetime_revenue,
            "total_revenue": retainer_revenue + onetime_revenue,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/projects/archived")
async def api_list_archived():
    """アーカイブ済み案件一覧API"""
    try:
        projects = await notion_service.list_archived_projects()
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/projects/{project_id}")
async def api_get_project(project_id: str):
    """案件詳細API"""
    try:
        project = await notion_service.get_project(project_id)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/projects")
async def api_create_project(data: ProjectCreate):
    """案件作成API"""
    try:
        project = await notion_service.create_project(
            name=data.name,
            status=data.status,
            client_name=data.client,
            amount=data.amount,
            start_date=data.start_date,
            end_date=data.end_date,
            url=data.url,
            lead_id=data.lead_id,
            memo=data.memo,
            contract_type=data.contract_type,
            billing_cycle=data.billing_cycle,
        )
        return {"success": True, "project": project}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/projects/{project_id}")
async def api_update_project(project_id: str, data: ProjectUpdate, suppress_tasks: bool = Query(False)):
    """案件更新API（suppress_tasks=True で案件化時のタスク自動生成を抑制）"""
    # 送信されたフィールドのみ反映（null/空も尊重）。タスク更新と同じ堅牢化。
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="更新内容がありません")
    try:
        project = await notion_service.update_project(project_id, updates)
        generated_tasks: list[dict] = []
        # ステータスが「案件化」になったら定型タスクを自動生成（既存タスクが無い場合のみ）
        # 詳細モーダルからの保存(suppress_tasks=True)では生成しない
        if updates.get("status") == "案件化" and not suppress_tasks:
            try:
                generated_tasks = await notion_service.generate_onboarding_tasks(project_id)
            except Exception:
                generated_tasks = []
        return {
            "success": True,
            "project": project,
            "generated_tasks": generated_tasks,
            "generated_task_count": len(generated_tasks),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str):
    """案件削除（アーカイブ）API"""
    try:
        await notion_service.archive_project(project_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== タスク API ==========

class TaskCreate(BaseModel):
    name: str
    project_id: Optional[str] = None
    status: str = "未着手"
    priority: str = "中"
    due_date: Optional[str] = None
    memo: str = ""
    recurring: bool = False
    target_month: str = ""


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    memo: Optional[str] = None
    project_id: Optional[str] = None
    recurring: Optional[bool] = None
    target_month: Optional[str] = None


@router.get("/api/projects/{project_id}/tasks")
async def api_list_tasks(
    project_id: str,
    month: Optional[str] = Query(None),
):
    """案件のタスク一覧API"""
    try:
        tasks = await notion_service.list_tasks(project_id=project_id, month=month)
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/tasks")
async def api_list_all_tasks(
    status: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
):
    """全タスク一覧API"""
    try:
        tasks = await notion_service.list_tasks(status=status, month=month)
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/tasks")
async def api_create_task(data: TaskCreate):
    """タスク作成API"""
    try:
        task = await notion_service.create_task(
            name=data.name,
            project_id=data.project_id,
            status=data.status,
            priority=data.priority,
            due_date=data.due_date,
            memo=data.memo,
            recurring=data.recurring,
            target_month=data.target_month,
        )
        return {"success": True, "task": task}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/tasks/{task_id}")
async def api_update_task(task_id: str, data: TaskUpdate):
    """タスク更新API"""
    # 送信されたフィールドだけを反映（null も「クリア」の意思として尊重する）。
    # ※ if v is not None で弾くと、期日やメモを空にしても元の値に戻ってしまう。
    updates = data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="更新内容がありません")
    try:
        task = await notion_service.update_task(task_id, updates)
        return {"success": True, "task": task}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/tasks/{task_id}")
async def api_delete_task(task_id: str):
    """タスク削除（アーカイブ）API"""
    try:
        await notion_service.archive_task(task_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== タスク添付ファイル ==========

def _attachment_dict(row: TaskAttachment) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "filename": row.filename,
        "content_type": row.content_type,
        "size": row.size,
        "is_image": (row.content_type or "").startswith("image/"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/api/tasks/{task_id}/attachments")
async def api_list_attachments(task_id: str):
    """タスクの添付ファイル一覧"""
    db = SessionLocal()
    try:
        rows = (
            db.query(TaskAttachment)
            .filter(TaskAttachment.task_id == task_id)
            .order_by(TaskAttachment.created_at)
            .all()
        )
        return {"attachments": [_attachment_dict(r) for r in rows]}
    finally:
        db.close()


@router.post("/api/tasks/{task_id}/attachments")
async def api_upload_attachment(task_id: str, file: UploadFile = File(...)):
    """タスクにファイル(PDF/画像)を添付"""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空のファイルです")
    if len(data) > MAX_ATTACH_SIZE:
        raise HTTPException(status_code=413, detail="ファイルが大きすぎます（最大15MB）")

    filename = file.filename or "file"
    ct = (file.content_type or "").lower()
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ct not in ALLOWED_ATTACH_TYPES and ext not in ALLOWED_ATTACH_EXTS:
        raise HTTPException(status_code=415, detail="PDFまたは画像ファイルのみ添付できます")
    if not ct or ct == "application/octet-stream":
        # 拡張子から推定
        ct = {
            ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }.get(ext, "application/octet-stream")

    db = SessionLocal()
    try:
        row = TaskAttachment(
            task_id=task_id, filename=filename[:300], content_type=ct[:150],
            size=len(data), data=data,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"success": True, "attachment": _attachment_dict(row)}
    finally:
        db.close()


@router.get("/api/attachments/{att_id}")
async def api_get_attachment(att_id: int, download: bool = Query(False)):
    """添付ファイルの中身を返す（表示 or ダウンロード）"""
    db = SessionLocal()
    try:
        row = db.query(TaskAttachment).filter(TaskAttachment.id == att_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="ファイルが見つかりません")
        disp = "attachment" if download else "inline"
        # RFC5987 で日本語ファイル名に対応
        quoted = urllib.parse.quote(row.filename or "file")
        headers = {
            "Content-Disposition": f"{disp}; filename*=UTF-8''{quoted}",
            "Cache-Control": "private, max-age=3600",
        }
        return Response(content=row.data, media_type=row.content_type or "application/octet-stream", headers=headers)
    finally:
        db.close()


@router.delete("/api/attachments/{att_id}")
async def api_delete_attachment(att_id: int):
    """添付ファイルを削除"""
    db = SessionLocal()
    try:
        row = db.query(TaskAttachment).filter(TaskAttachment.id == att_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="ファイルが見つかりません")
        db.delete(row)
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ========== 毎週のタスク（曜日指定の自動生成テンプレート） ==========

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]


class RecurringTaskIn(BaseModel):
    name: str
    weekday: int = 2  # 月=0..日=6（水=2）
    priority: str = "中"
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    create_status: str = "進行中"
    enabled: bool = True


def _recurring_dict(r: RecurringTask) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "weekday": r.weekday,
        "weekday_label": WEEKDAY_LABELS[r.weekday] if 0 <= r.weekday <= 6 else "",
        "priority": r.priority,
        "project_id": r.project_id,
        "project_name": r.project_name,
        "create_status": r.create_status,
        "enabled": r.enabled,
        "last_created_week": r.last_created_week,
    }


@router.get("/api/recurring-tasks")
async def api_list_recurring():
    """毎週のタスク一覧"""
    db = SessionLocal()
    try:
        rows = db.query(RecurringTask).order_by(RecurringTask.weekday, RecurringTask.id).all()
        return {"recurring_tasks": [_recurring_dict(r) for r in rows]}
    finally:
        db.close()


@router.post("/api/recurring-tasks")
async def api_create_recurring(data: RecurringTaskIn):
    """毎週のタスクを登録"""
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="タスク名は必須です")
    if not (0 <= data.weekday <= 6):
        raise HTTPException(status_code=400, detail="曜日が不正です")
    db = SessionLocal()
    try:
        row = RecurringTask(
            name=data.name.strip()[:300], weekday=data.weekday,
            priority=data.priority or "中", project_id=data.project_id or None,
            project_name=data.project_name or None, create_status=data.create_status or "進行中",
            enabled=data.enabled,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"success": True, "recurring_task": _recurring_dict(row)}
    finally:
        db.close()


@router.patch("/api/recurring-tasks/{rid}")
async def api_update_recurring(rid: int, data: RecurringTaskIn):
    """毎週のタスクを更新"""
    db = SessionLocal()
    try:
        row = db.query(RecurringTask).filter(RecurringTask.id == rid).first()
        if not row:
            raise HTTPException(status_code=404, detail="見つかりません")
        row.name = data.name.strip()[:300]
        row.weekday = data.weekday
        row.priority = data.priority or "中"
        row.project_id = data.project_id or None
        row.project_name = data.project_name or None
        row.create_status = data.create_status or "進行中"
        row.enabled = data.enabled
        db.commit()
        return {"success": True, "recurring_task": _recurring_dict(row)}
    finally:
        db.close()


@router.delete("/api/recurring-tasks/{rid}")
async def api_delete_recurring(rid: int):
    """毎週のタスクを削除"""
    db = SessionLocal()
    try:
        row = db.query(RecurringTask).filter(RecurringTask.id == rid).first()
        if not row:
            raise HTTPException(status_code=404, detail="見つかりません")
        db.delete(row)
        db.commit()
        return {"success": True}
    finally:
        db.close()


@router.post("/api/recurring-tasks/{rid}/run-now")
async def api_run_recurring_now(rid: int):
    """このテンプレートから今すぐタスクを1件作成（テスト用・週次dedupは無視）"""
    db = SessionLocal()
    try:
        row = db.query(RecurringTask).filter(RecurringTask.id == rid).first()
        if not row:
            raise HTTPException(status_code=404, detail="見つかりません")
        name, pid, status, prio = row.name, row.project_id, row.create_status, row.priority
    finally:
        db.close()
    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    try:
        task = await notion_service.create_task(
            name=name, project_id=pid or None, status=status or "進行中",
            priority=prio or "中", due_date=today,
        )
        return {"success": True, "task": task}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 繰り返しタスク生成 ==========

class GenerateTasksRequest(BaseModel):
    year_month: str  # "2026-03" 形式


@router.post("/api/projects/{project_id}/generate-tasks")
async def api_generate_monthly_tasks(project_id: str, data: GenerateTasksRequest):
    """繰り返しタスクから指定月のタスクを生成"""
    try:
        created = await notion_service.generate_monthly_tasks(
            project_id=project_id,
            year_month=data.year_month,
        )
        return {"success": True, "created_count": len(created), "tasks": created}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== リード→案件化 ==========

class BulkProjectCreate(BaseModel):
    projects: list[ProjectCreate]


@router.post("/api/projects/bulk")
async def api_bulk_create_projects(data: BulkProjectCreate):
    """案件一括作成API"""
    results: list[dict] = []
    errors: list[dict] = []
    for i, item in enumerate(data.projects):
        try:
            project = await notion_service.create_project(
                name=item.name,
                status=item.status,
                client_name=item.client,
                amount=item.amount,
                start_date=item.start_date,
                end_date=item.end_date,
                url=item.url,
                lead_id=item.lead_id,
                memo=item.memo,
                contract_type=item.contract_type,
                billing_cycle=item.billing_cycle,
            )
            results.append(project)
        except Exception as e:
            errors.append({"index": i, "name": item.name, "error": str(e)})
    return {
        "success": len(errors) == 0,
        "created_count": len(results),
        "error_count": len(errors),
        "projects": results,
        "errors": errors,
    }


class LeadToProjectRequest(BaseModel):
    lead_id: int
    name: str
    client: str = ""
    url: str = ""
    amount: Optional[int] = None
    memo: str = ""


@router.post("/api/leads/{lead_id}/to-project")
async def api_lead_to_project(lead_id: int, data: LeadToProjectRequest):
    """リードから案件を作成"""
    try:
        project = await notion_service.create_project(
            name=data.name,
            status="提案前",
            client_name=data.client,
            amount=data.amount,
            url=data.url,
            lead_id=str(lead_id),
            memo=data.memo,
        )
        return {"success": True, "project": project}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== アーカイブ ==========

@router.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request):
    """アーカイブ済み案件一覧ページ"""
    try:
        archived = await notion_service.list_archived_projects()
    except Exception:
        archived = []
    return _get_templates().TemplateResponse(request, "archive.html", {
        "projects": archived,
        "statuses": notion_service.PROJECT_STATUSES,
    })


@router.post("/api/projects/{project_id}/unarchive")
async def api_unarchive_project(project_id: str):
    """案件をアーカイブから復活"""
    try:
        project = await notion_service.unarchive_project(project_id)
        return {"success": True, "project": project}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== メモからタスク抽出 ==========

class ExtractTasksRequest(BaseModel):
    memo: str


@router.post("/api/projects/extract-tasks")
async def api_extract_tasks(data: ExtractTasksRequest):
    """メモ内容からAIでタスクを抽出"""
    if not data.memo.strip():
        return {"tasks": []}

    import httpx
    from app.config import get_settings
    import json

    settings = get_settings()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 512,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"""以下の案件メモからタスク（やるべきこと）を抽出してJSON配列で返してください。

【メモ】
{data.memo[:3000]}

JSON配列で返してください（コードブロック不要）。各要素:
- name: string (タスク名、簡潔に)
- priority: string (高/中/低)

タスクがない場合は空配列 [] を返してください。"""
                        }
                    ],
                },
            )
            resp.raise_for_status()
            result = resp.json()

        text = result["content"][0]["text"].strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        tasks = json.loads(text)
        if not isinstance(tasks, list):
            tasks = []

        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 接続確認 ==========

@router.get("/api/notion/status")
async def api_notion_status():
    """Notion接続状態を確認"""
    return await notion_service.check_connection()

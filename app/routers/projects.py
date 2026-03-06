"""案件管理ルーター（Notion連携）"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from app.services import notion_service

router = APIRouter(tags=["projects"])


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
    return _get_templates().TemplateResponse("projects.html", {
        "request": request,
        "projects": projects,
        "statuses": notion_service.PROJECT_STATUSES,
        "contract_types": notion_service.CONTRACT_TYPES,
        "billing_cycles": notion_service.BILLING_CYCLES,
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
    return _get_templates().TemplateResponse("gantt.html", {
        "request": request,
        "projects": projects,
        "tasks": tasks,
        "connected": conn["ok"],
        "error": conn.get("error"),
    })


# ========== 案件 API ==========

class ProjectCreate(BaseModel):
    name: str
    status: str = "見込み"
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
async def api_update_project(project_id: str, data: ProjectUpdate):
    """案件更新API"""
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="更新内容がありません")
    try:
        project = await notion_service.update_project(project_id, updates)
        return {"success": True, "project": project}
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
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
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


# ========== リード→案件化 ==========

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
            status="見込み",
            client_name=data.client,
            amount=data.amount,
            url=data.url,
            lead_id=str(lead_id),
            memo=data.memo,
        )
        return {"success": True, "project": project}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 接続確認 ==========

@router.get("/api/notion/status")
async def api_notion_status():
    """Notion接続状態を確認"""
    return await notion_service.check_connection()

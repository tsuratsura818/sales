"""Notion API クライアント - 案件管理・タスク管理"""

from typing import Optional
import httpx
from app.config import get_settings

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# 案件ステータス定義
PROJECT_STATUSES = ["見込み", "提案中", "商談中", "受注", "進行中", "完了", "失注"]
CONTRACT_TYPES = ["単発", "継続"]
BILLING_CYCLES = ["月次", "四半期", "年次"]
TASK_STATUSES = ["未着手", "進行中", "完了"]
TASK_PRIORITIES = ["高", "中", "低"]


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _db_ids() -> tuple[str, str]:
    settings = get_settings()
    return settings.NOTION_PROJECT_DB_ID, settings.NOTION_TASK_DB_ID


def _parse_page_property(prop: dict) -> str | int | float | None:
    """Notionプロパティからプレーンな値を抽出"""
    t = prop.get("type", "")
    if t == "title":
        return "".join(rt.get("plain_text", "") for rt in prop.get("title", []))
    if t == "rich_text":
        return "".join(rt.get("plain_text", "") for rt in prop.get("rich_text", []))
    if t == "select":
        sel = prop.get("select")
        return sel["name"] if sel else None
    if t == "number":
        return prop.get("number")
    if t == "date":
        d = prop.get("date")
        return d.get("start") if d else None
    if t == "url":
        return prop.get("url")
    if t == "checkbox":
        return prop.get("checkbox")
    if t == "relation":
        rels = prop.get("relation", [])
        return [r["id"] for r in rels] if rels else []
    return None


def _parse_project(page: dict) -> dict:
    """Notionページ → 案件dict"""
    props = page.get("properties", {})
    return {
        "id": page["id"],
        "name": _parse_page_property(props.get("案件名", {})),
        "status": _parse_page_property(props.get("ステータス", {})),
        "client": _parse_page_property(props.get("クライアント", {})),
        "amount": _parse_page_property(props.get("金額", {})),
        "start_date": _parse_page_property(props.get("開始日", {})),
        "end_date": _parse_page_property(props.get("期日", {})),
        "url": _parse_page_property(props.get("URL", {})),
        "lead_id": _parse_page_property(props.get("リードID", {})),
        "memo": _parse_page_property(props.get("メモ", {})),
        "contract_type": _parse_page_property(props.get("契約タイプ", {})),
        "billing_cycle": _parse_page_property(props.get("請求サイクル", {})),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
    }


def _parse_task(page: dict) -> dict:
    """Notionページ → タスクdict"""
    props = page.get("properties", {})
    return {
        "id": page["id"],
        "name": _parse_page_property(props.get("タスク名", {})),
        "status": _parse_page_property(props.get("ステータス", {})),
        "priority": _parse_page_property(props.get("優先度", {})),
        "due_date": _parse_page_property(props.get("期日", {})),
        "project_ids": _parse_page_property(props.get("案件", {})),
        "memo": _parse_page_property(props.get("メモ", {})),
        "recurring": _parse_page_property(props.get("繰り返し", {})),
        "target_month": _parse_page_property(props.get("対象年月", {})),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
    }


# ========== 案件 CRUD ==========

async def list_projects(
    status: Optional[str] = None,
    sort_by: str = "last_edited_time",
    ascending: bool = False,
) -> list[dict]:
    """案件一覧取得"""
    project_db_id, _ = _db_ids()
    payload: dict = {
        "sorts": [{"timestamp": sort_by, "direction": "ascending" if ascending else "descending"}],
        "page_size": 100,
    }
    if status:
        payload["filter"] = {
            "property": "ステータス",
            "select": {"equals": status},
        }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{NOTION_API_BASE}/databases/{project_db_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return [_parse_project(page) for page in data.get("results", [])]


async def get_project(project_id: str) -> dict:
    """案件詳細取得"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{NOTION_API_BASE}/pages/{project_id}",
            headers=_headers(),
        )
        resp.raise_for_status()
    return _parse_project(resp.json())


async def create_project(
    name: str,
    status: str = "見込み",
    client_name: str = "",
    amount: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    url: str = "",
    lead_id: str = "",
    memo: str = "",
    contract_type: str = "",
    billing_cycle: str = "",
) -> dict:
    """案件作成"""
    project_db_id, _ = _db_ids()
    properties: dict = {
        "案件名": {"title": [{"text": {"content": name}}]},
        "ステータス": {"select": {"name": status}},
    }
    if client_name:
        properties["クライアント"] = {"rich_text": [{"text": {"content": client_name}}]}
    if amount is not None:
        properties["金額"] = {"number": amount}
    if start_date:
        date_obj: dict = {"start": start_date}
        if end_date:
            date_obj["end"] = end_date
        properties["開始日"] = {"date": date_obj}
    if end_date:
        properties["期日"] = {"date": {"start": end_date}}
    if url:
        properties["URL"] = {"url": url}
    if lead_id:
        properties["リードID"] = {"rich_text": [{"text": {"content": str(lead_id)}}]}
    if memo:
        properties["メモ"] = {"rich_text": [{"text": {"content": memo}}]}
    if contract_type:
        properties["契約タイプ"] = {"select": {"name": contract_type}}
    if billing_cycle:
        properties["請求サイクル"] = {"select": {"name": billing_cycle}}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{NOTION_API_BASE}/pages",
            headers=_headers(),
            json={"parent": {"database_id": project_db_id}, "properties": properties},
        )
        resp.raise_for_status()
    return _parse_project(resp.json())


async def update_project(project_id: str, updates: dict) -> dict:
    """案件更新（部分更新）"""
    properties: dict = {}

    field_map = {
        "name": ("案件名", lambda v: {"title": [{"text": {"content": v}}]}),
        "status": ("ステータス", lambda v: {"select": {"name": v}}),
        "client": ("クライアント", lambda v: {"rich_text": [{"text": {"content": v}}]}),
        "amount": ("金額", lambda v: {"number": v}),
        "start_date": ("開始日", lambda v: {"date": {"start": v}} if v else {"date": None}),
        "end_date": ("期日", lambda v: {"date": {"start": v}} if v else {"date": None}),
        "url": ("URL", lambda v: {"url": v or None}),
        "memo": ("メモ", lambda v: {"rich_text": [{"text": {"content": v}}]}),
        "contract_type": ("契約タイプ", lambda v: {"select": {"name": v}} if v else {"select": None}),
        "billing_cycle": ("請求サイクル", lambda v: {"select": {"name": v}} if v else {"select": None}),
    }

    for key, value in updates.items():
        if key in field_map:
            notion_key, converter = field_map[key]
            properties[notion_key] = converter(value)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{NOTION_API_BASE}/pages/{project_id}",
            headers=_headers(),
            json={"properties": properties},
        )
        resp.raise_for_status()
    return _parse_project(resp.json())


async def archive_project(project_id: str) -> bool:
    """案件アーカイブ（削除相当）"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{NOTION_API_BASE}/pages/{project_id}",
            headers=_headers(),
            json={"archived": True},
        )
        resp.raise_for_status()
    return True


async def unarchive_project(project_id: str) -> dict:
    """案件アーカイブ解除（復活）"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{NOTION_API_BASE}/pages/{project_id}",
            headers=_headers(),
            json={"archived": False},
        )
        resp.raise_for_status()
    return _parse_project(resp.json())


async def list_archived_projects() -> list[dict]:
    """アーカイブ済み案件一覧"""
    project_db_id, _ = _db_ids()
    payload: dict = {
        "filter": {
            "property": "案件名",
            "title": {"is_not_empty": True},
        },
        "page_size": 100,
    }

    # Notion APIではarchivedページはfilter_propertiesで取れないため
    # 全ページ取得後にフィルタ（archivedはページ自体のプロパティ）
    # → 実際にはNotion APIの POST /databases/{id}/query に
    #   "filter_properties" ではなく "in_trash" パラメータを使う
    # ただし2024年以降のAPIでは archived ページは通常クエリに含まれない
    # → 個別ページ取得で archived: true を確認する方法もあるが、
    #   ここでは Notion の search API を使用
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{NOTION_API_BASE}/search",
            headers=_headers(),
            json={
                "filter": {"property": "object", "value": "page"},
                "page_size": 100,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    archived = []
    for page in data.get("results", []):
        if page.get("archived") and page.get("parent", {}).get("database_id", "").replace("-", "") == project_db_id.replace("-", ""):
            archived.append(_parse_project(page))

    return archived


# ========== タスク CRUD ==========

async def list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None,
) -> list[dict]:
    """タスク一覧取得"""
    _, task_db_id = _db_ids()
    filters: list[dict] = []

    if project_id:
        filters.append({
            "property": "案件",
            "relation": {"contains": project_id},
        })
    if status:
        filters.append({
            "property": "ステータス",
            "select": {"equals": status},
        })
    if month:
        filters.append({
            "property": "対象年月",
            "rich_text": {"equals": month},
        })

    payload: dict = {
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        "page_size": 100,
    }
    if len(filters) == 1:
        payload["filter"] = filters[0]
    elif len(filters) > 1:
        payload["filter"] = {"and": filters}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{NOTION_API_BASE}/databases/{task_db_id}/query",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return [_parse_task(page) for page in data.get("results", [])]


async def create_task(
    name: str,
    project_id: Optional[str] = None,
    status: str = "未着手",
    priority: str = "中",
    due_date: Optional[str] = None,
    memo: str = "",
    recurring: bool = False,
    target_month: str = "",
) -> dict:
    """タスク作成"""
    _, task_db_id = _db_ids()
    properties: dict = {
        "タスク名": {"title": [{"text": {"content": name}}]},
        "ステータス": {"select": {"name": status}},
        "優先度": {"select": {"name": priority}},
    }
    if project_id:
        properties["案件"] = {"relation": [{"id": project_id}]}
    if due_date:
        properties["期日"] = {"date": {"start": due_date}}
    if memo:
        properties["メモ"] = {"rich_text": [{"text": {"content": memo}}]}
    if recurring:
        properties["繰り返し"] = {"checkbox": True}
    if target_month:
        properties["対象年月"] = {"rich_text": [{"text": {"content": target_month}}]}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{NOTION_API_BASE}/pages",
            headers=_headers(),
            json={"parent": {"database_id": task_db_id}, "properties": properties},
        )
        resp.raise_for_status()
    return _parse_task(resp.json())


async def update_task(task_id: str, updates: dict) -> dict:
    """タスク更新（部分更新）"""
    properties: dict = {}

    field_map = {
        "name": ("タスク名", lambda v: {"title": [{"text": {"content": v}}]}),
        "status": ("ステータス", lambda v: {"select": {"name": v}}),
        "priority": ("優先度", lambda v: {"select": {"name": v}}),
        "due_date": ("期日", lambda v: {"date": {"start": v}} if v else {"date": None}),
        "memo": ("メモ", lambda v: {"rich_text": [{"text": {"content": v}}]}),
        "project_id": ("案件", lambda v: {"relation": [{"id": v}]} if v else {"relation": []}),
        "recurring": ("繰り返し", lambda v: {"checkbox": bool(v)}),
        "target_month": ("対象年月", lambda v: {"rich_text": [{"text": {"content": v}}]}),
    }

    for key, value in updates.items():
        if key in field_map:
            notion_key, converter = field_map[key]
            properties[notion_key] = converter(value)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{NOTION_API_BASE}/pages/{task_id}",
            headers=_headers(),
            json={"properties": properties},
        )
        resp.raise_for_status()
    return _parse_task(resp.json())


async def archive_task(task_id: str) -> bool:
    """タスクアーカイブ（削除相当）"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{NOTION_API_BASE}/pages/{task_id}",
            headers=_headers(),
            json={"archived": True},
        )
        resp.raise_for_status()
    return True


# ========== 繰り返しタスク生成 ==========

async def generate_monthly_tasks(project_id: str, year_month: str) -> list[dict]:
    """繰り返しタスクのテンプレートから指定月のタスクを生成"""
    all_tasks = await list_tasks(project_id=project_id)

    templates = [t for t in all_tasks if t.get("recurring")]
    existing = [t for t in all_tasks if t.get("target_month") == year_month]
    existing_names = {t["name"] for t in existing}

    created: list[dict] = []
    for tmpl in templates:
        if tmpl["name"] in existing_names:
            continue
        task = await create_task(
            name=tmpl["name"],
            project_id=project_id,
            status="未着手",
            priority=tmpl.get("priority", "中"),
            memo=tmpl.get("memo", ""),
            target_month=year_month,
        )
        created.append(task)

    return created


# ========== Notion DB初期化ヘルパー ==========

_conn_cache: dict | None = None
_conn_cache_at: float = 0

async def check_connection() -> dict:
    """Notion API接続確認（5分キャッシュ）"""
    import time
    global _conn_cache, _conn_cache_at

    if _conn_cache and time.time() - _conn_cache_at < 300:
        return _conn_cache

    try:
        project_db_id, task_db_id = _db_ids()
        if not get_settings().NOTION_API_KEY:
            return {"ok": False, "error": "NOTION_API_KEY が未設定です"}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{NOTION_API_BASE}/databases/{project_db_id}",
                headers=_headers(),
            )
            if resp.status_code != 200:
                return {"ok": False, "error": f"案件DB接続失敗: {resp.status_code}"}

            resp2 = await client.get(
                f"{NOTION_API_BASE}/databases/{task_db_id}",
                headers=_headers(),
            )
            if resp2.status_code != 200:
                return {"ok": False, "error": f"タスクDB接続失敗: {resp2.status_code}"}

        _conn_cache = {"ok": True}
        _conn_cache_at = time.time()
        return _conn_cache
    except Exception as e:
        return {"ok": False, "error": str(e)}

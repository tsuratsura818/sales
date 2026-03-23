"""メモ管理ルーター - Simplenote風メモ + 案件自動紐付け"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timezone

from app.database import get_db
from app.models.memo import Memo
from app.services.memo_classifier import classify_memo, append_memo_to_project

router = APIRouter(tags=["memos"])


def _get_templates():
    from main import templates
    return templates


# ========== HTMLページ ==========

@router.get("/memos", response_class=HTMLResponse)
async def memos_page(request: Request, db: Session = Depends(get_db)):
    """メモ一覧ページ"""
    try:
        memos = db.query(Memo).order_by(desc(Memo.updated_at)).all()
        return _get_templates().TemplateResponse("memos.html", {
            "request": request,
            "memos": memos,
        })
    except Exception as e:
        import traceback
        return HTMLResponse(f"<pre>{traceback.format_exc()}</pre>", status_code=500)


# ========== API ==========

class MemoCreate(BaseModel):
    content: str
    title: str = ""


class MemoUpdate(BaseModel):
    content: Optional[str] = None
    title: Optional[str] = None


class MemoLink(BaseModel):
    project_id: str
    project_name: str


@router.get("/api/memos")
async def api_list_memos(
    filter: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """メモ一覧API (filter: all/linked/unlinked)"""
    query = db.query(Memo).order_by(desc(Memo.updated_at))
    if filter == "linked":
        query = query.filter(Memo.notion_project_id.isnot(None))
    elif filter == "unlinked":
        query = query.filter(Memo.notion_project_id.is_(None))

    memos = query.all()
    return {
        "memos": [
            {
                "id": m.id,
                "title": m.title,
                "content": m.content,
                "notion_project_id": m.notion_project_id,
                "notion_project_name": m.notion_project_name,
                "classification_status": m.classification_status,
                "synced_to_notion": m.synced_to_notion,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in memos
        ]
    }


@router.post("/api/memos")
async def api_create_memo(data: MemoCreate, db: Session = Depends(get_db)):
    """メモ作成 + AI自動分類"""
    title = data.title or data.content.split("\n")[0][:100] or "無題"

    memo = Memo(
        content=data.content,
        title=title,
        classification_status="pending",
    )
    db.add(memo)
    db.commit()
    db.refresh(memo)

    # AI自動分類
    classification = await classify_memo(data.content)

    if classification["matched"] and classification["project_id"]:
        memo.notion_project_id = classification["project_id"]
        memo.notion_project_name = classification["project_name"]
        memo.classification_status = "classified"
    else:
        memo.classification_status = "unlinked"

    db.commit()
    db.refresh(memo)

    return {
        "success": True,
        "memo": {
            "id": memo.id,
            "title": memo.title,
            "content": memo.content,
            "notion_project_id": memo.notion_project_id,
            "notion_project_name": memo.notion_project_name,
            "classification_status": memo.classification_status,
            "synced_to_notion": memo.synced_to_notion,
        },
        "classification": classification,
    }


@router.patch("/api/memos/{memo_id}")
async def api_update_memo(memo_id: int, data: MemoUpdate, db: Session = Depends(get_db)):
    """メモ更新"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")

    if data.content is not None:
        memo.content = data.content
        # タイトル自動更新
        if not data.title:
            memo.title = data.content.split("\n")[0][:100] or "無題"
    if data.title is not None:
        memo.title = data.title

    memo.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"success": True}


@router.delete("/api/memos/{memo_id}")
async def api_delete_memo(memo_id: int, db: Session = Depends(get_db)):
    """メモ削除"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")
    db.delete(memo)
    db.commit()
    return {"success": True}


@router.post("/api/memos/{memo_id}/classify")
async def api_classify_memo(memo_id: int, db: Session = Depends(get_db)):
    """メモを再分類"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")

    classification = await classify_memo(memo.content)

    if classification["matched"] and classification["project_id"]:
        memo.notion_project_id = classification["project_id"]
        memo.notion_project_name = classification["project_name"]
        memo.classification_status = "classified"
    else:
        memo.notion_project_id = None
        memo.notion_project_name = None
        memo.classification_status = "unlinked"

    memo.synced_to_notion = 0
    db.commit()

    return {"success": True, "classification": classification}


@router.post("/api/memos/{memo_id}/link")
async def api_link_memo(memo_id: int, data: MemoLink, db: Session = Depends(get_db)):
    """メモを手動で案件に紐付け"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")

    memo.notion_project_id = data.project_id
    memo.notion_project_name = data.project_name
    memo.classification_status = "manual"
    memo.synced_to_notion = 0
    db.commit()

    return {"success": True}


@router.post("/api/memos/{memo_id}/unlink")
async def api_unlink_memo(memo_id: int, db: Session = Depends(get_db)):
    """メモの案件紐付けを解除"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")

    memo.notion_project_id = None
    memo.notion_project_name = None
    memo.classification_status = "unlinked"
    memo.synced_to_notion = 0
    db.commit()

    return {"success": True}


@router.post("/api/memos/{memo_id}/sync")
async def api_sync_memo(memo_id: int, db: Session = Depends(get_db)):
    """メモをNotionの案件ページに同期（追記）"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")
    if not memo.notion_project_id:
        raise HTTPException(status_code=400, detail="案件に紐付けされていません")

    success = await append_memo_to_project(
        memo.notion_project_id,
        memo.title,
        memo.content,
    )

    if success:
        memo.synced_to_notion = 1
        db.commit()
        return {"success": True}
    else:
        raise HTTPException(status_code=500, detail="Notionへの同期に失敗しました")

"""メモ管理ルーター - Simplenote風メモ + 案件自動紐付け + 録音議事録化"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timezone

from app.database import get_db
from app.models.memo import Memo
from app.services.memo_classifier import classify_memo, append_memo_to_project
from app.services.transcribe_service import transcribe_audio, TranscribeError
from app.services.minutes_service import transcript_to_minutes

router = APIRouter(tags=["memos"])


def _get_templates():
    from main import templates
    return templates


# ========== HTMLページ ==========

@router.get("/memos", response_class=HTMLResponse)
async def memos_page(request: Request, db: Session = Depends(get_db)):
    memos = db.query(Memo).order_by(desc(Memo.updated_at)).all()
    return _get_templates().TemplateResponse(request, "memos.html", {"memos": memos})


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


@router.post("/api/memos/transcribe")
async def api_transcribe_audio_new(
    audio: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """音声から新規メモを作成 (文字起こし結果をcontentに格納)"""
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="空の音声ファイルです")

    try:
        transcript = await transcribe_audio(
            audio_bytes, filename=audio.filename, content_type=audio.content_type,
        )
    except TranscribeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    title = transcript.split("\n")[0][:100] or "録音メモ"
    memo = Memo(
        content=transcript,
        title=title,
        classification_status="unlinked",
    )
    db.add(memo)
    db.commit()
    db.refresh(memo)

    return {
        "success": True,
        "memo": {
            "id": memo.id,
            "title": memo.title,
            "content": memo.content,
        },
        "transcript_chars": len(transcript),
    }


@router.post("/api/memos/{memo_id}/transcribe")
async def api_transcribe_audio_append(
    memo_id: int,
    audio: UploadFile = File(...),
    mode: str = Form("append"),  # append | replace
    db: Session = Depends(get_db),
):
    """既存メモに音声文字起こしを追記 or 置換"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="空の音声ファイルです")

    try:
        transcript = await transcribe_audio(
            audio_bytes, filename=audio.filename, content_type=audio.content_type,
        )
    except TranscribeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if mode == "replace" or not (memo.content or "").strip():
        memo.content = transcript
    else:
        memo.content = (memo.content or "").rstrip() + "\n\n---\n\n" + transcript

    if not memo.title or memo.title == "無題":
        memo.title = memo.content.split("\n")[0][:100] or "録音メモ"

    memo.updated_at = datetime.now(timezone.utc)
    memo.synced_to_notion = 0
    db.commit()
    db.refresh(memo)

    return {
        "success": True,
        "memo": {"id": memo.id, "title": memo.title, "content": memo.content},
        "transcript_chars": len(transcript),
    }


class MinutesRequest(BaseModel):
    project_hint: Optional[str] = None
    title_hint: Optional[str] = None
    mode: str = "replace"  # replace | append


@router.post("/api/memos/{memo_id}/to_minutes")
async def api_to_minutes(
    memo_id: int,
    data: MinutesRequest,
    db: Session = Depends(get_db),
):
    """メモ内容 (文字起こし) を議事録フォーマットに整形"""
    memo = db.query(Memo).filter(Memo.id == memo_id).first()
    if not memo:
        raise HTTPException(status_code=404, detail="メモが見つかりません")

    source = (memo.content or "").strip()
    if not source:
        raise HTTPException(status_code=400, detail="メモ内容が空です")

    project_hint = data.project_hint or memo.notion_project_name

    try:
        minutes_md = await transcript_to_minutes(
            source, project_hint=project_hint, title_hint=data.title_hint,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"議事録整形に失敗: {e}")

    if data.mode == "append":
        memo.content = source + "\n\n---\n\n" + minutes_md
    else:
        memo.content = minutes_md

    # 議事録の1行目(# 議事録: ...)からタイトル生成
    first_line = memo.content.split("\n", 1)[0].lstrip("# ").strip()
    if first_line:
        memo.title = first_line[:100]

    memo.updated_at = datetime.now(timezone.utc)
    memo.synced_to_notion = 0
    db.commit()
    db.refresh(memo)

    return {
        "success": True,
        "memo": {"id": memo.id, "title": memo.title, "content": memo.content},
    }


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

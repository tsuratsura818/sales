"""取引先の対応履歴 (customer_activities)。

Across デスクトップから「承認済みの要約1行」を受け取って貯める (Phase 3)。
それを Notion 案件へ昇格(追記)する (Phase 5)。
生のメッセージ本文は受け取らない — 来るのは要約テキストとメタ情報のみ。
認証は共通ミドルウェア(X-API-Key / Basic)で保護される。
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.activity import CustomerActivity

logger = logging.getLogger(__name__)
router = APIRouter(tags=["activities"])


def _parse_dt(value: str | None) -> datetime:
    """ISO8601 をパース。失敗/未指定は現在時刻。"""
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.utcnow()


@router.post("/api/activities")
async def create_activity(request: Request, db: Session = Depends(get_db)):
    """Across から承認済みの対応履歴(要約1行)を受け取る。

    body: {
      target: {lead_id?: int, client_site_id?: int},  # どちらか必須
      channel: str, summary: str, occurred_at?: iso, external_key?: str
    }
    external_key が既存なら二重送信とみなし、既存の id を返す(冪等)。
    """
    body = await request.json()
    target = body.get("target") or {}
    lead_id = target.get("lead_id")
    client_site_id = target.get("client_site_id")
    channel = (body.get("channel") or "").strip()
    summary = (body.get("summary") or "").strip()
    external_key = body.get("external_key")

    if lead_id is None and client_site_id is None:
        raise HTTPException(400, "target に lead_id か client_site_id が必要です")
    if not channel or not summary:
        raise HTTPException(400, "channel と summary は必須です")

    # 冪等化: 同じ external_key は作り直さない。
    if external_key:
        existing = (
            db.query(CustomerActivity)
            .filter(CustomerActivity.external_key == external_key)
            .first()
        )
        if existing:
            return {"id": existing.id, "duplicate": True}

    activity = CustomerActivity(
        lead_id=lead_id,
        client_site_id=client_site_id,
        channel=channel,
        summary=summary,
        occurred_at=_parse_dt(body.get("occurred_at")),
        source=body.get("source") or "across",
        external_key=external_key,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return {"id": activity.id, "duplicate": False}


@router.get("/api/activities")
async def list_activities(
    lead_id: int | None = None,
    client_site_id: int | None = None,
    db: Session = Depends(get_db),
):
    """取引先の対応履歴一覧(新しい順)。lead_id か client_site_id で絞り込み。"""
    q = db.query(CustomerActivity)
    if lead_id is not None:
        q = q.filter(CustomerActivity.lead_id == lead_id)
    if client_site_id is not None:
        q = q.filter(CustomerActivity.client_site_id == client_site_id)
    rows = q.order_by(CustomerActivity.occurred_at.desc()).limit(200).all()
    return [
        {
            "id": a.id,
            "lead_id": a.lead_id,
            "client_site_id": a.client_site_id,
            "channel": a.channel,
            "summary": a.summary,
            "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
            "notion_project_id": a.notion_project_id,
        }
        for a in rows
    ]


@router.post("/api/activities/{activity_id}/to-project")
async def promote_to_project(activity_id: int, request: Request, db: Session = Depends(get_db)):
    """対応履歴を Notion 案件ページへ追記(昇格)する (Phase 5)。

    body: {project_id: str}  # Notion 案件ID
    既存の append_memo_to_project レールを流用する。
    """
    from app.services.memo_classifier import append_memo_to_project

    body = await request.json()
    project_id = (body.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(400, "project_id は必須です")

    activity = db.query(CustomerActivity).filter(CustomerActivity.id == activity_id).first()
    if not activity:
        raise HTTPException(404, "対応履歴が見つかりません")

    title = f"[{activity.channel}] {activity.occurred_at:%Y-%m-%d}"
    ok = await append_memo_to_project(project_id, title, activity.summary)
    if not ok:
        raise HTTPException(502, "Notion への追記に失敗しました")

    activity.notion_project_id = project_id
    db.commit()
    return {"id": activity.id, "notion_project_id": project_id}

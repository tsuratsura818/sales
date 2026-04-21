"""配信停止リスト管理"""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.models.suppression import SuppressionEntry

log = logging.getLogger("suppression")


def is_suppressed(email: str, db: Session) -> bool:
    """宛先が配信停止リストに入っているか"""
    if not email:
        return False
    e = email.strip().lower()
    return db.query(SuppressionEntry.id).filter(SuppressionEntry.email == e).first() is not None


def add_suppression(
    email: str,
    db: Session,
    *,
    reason: str = "manual",
    source: str = "manual",
    detail: str | None = None,
) -> SuppressionEntry | None:
    """配信停止リストに追加(既にあれば何もしない)"""
    if not email:
        return None
    e = email.strip().lower()
    existing = db.query(SuppressionEntry).filter(SuppressionEntry.email == e).first()
    if existing:
        return existing
    entry = SuppressionEntry(email=e, reason=reason, source=source, detail=(detail or "")[:500])
    db.add(entry)
    try:
        db.commit()
        log.info(f"suppressed: {e} ({reason}/{source})")
        return entry
    except Exception as exc:
        db.rollback()
        log.warning(f"add_suppression failed: {exc}")
        return None


def remove_suppression(email: str, db: Session) -> bool:
    e = email.strip().lower()
    row = db.query(SuppressionEntry).filter(SuppressionEntry.email == e).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True

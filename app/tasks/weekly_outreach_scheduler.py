"""週次自動アウトリーチ: 毎週指定の曜日・時刻に
  1) 企業検索（バッチ収集 pipeline）を自動実行
  2) 分析・メールアドレス抽出・営業メール文面の下書きを自動生成（=リスト化）
  3) 準備完了を LINE 通知

実際の送信は行わない（ユーザーがレビューしてから手動送信＝「レビュー後に送信」方針）。
週1回だけ実行する（last_week = ISO週で管理）。
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_settings import AppSettings
from app.models.pipeline import PipelineRun, PipelineResult
from app.services import line_service

logger = logging.getLogger(__name__)
settings = get_settings()
JST = timezone(timedelta(hours=9))

BASE_URL = "https://sales-6g78.onrender.com"


def _iso_week(now: datetime) -> str:
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def _get_cfg() -> AppSettings | None:
    db = SessionLocal()
    try:
        return db.query(AppSettings).first()
    finally:
        db.close()


def _mark_run(week: str) -> None:
    db = SessionLocal()
    try:
        cfg = db.query(AppSettings).first()
        if cfg:
            cfg.weekly_outreach_last_week = week
            db.commit()
    finally:
        db.close()


async def run_weekly_outreach() -> dict:
    """週次アウトリーチを1回実行。収集→リスト化→提案文生成→LINE通知。

    返り値: {"started": bool, "run_id": int|None, "leads": int, "with_email": int, "ready": int}
    送信はしない（レビュー用リストを作るだけ）。
    """
    from app.services.pipeline.runner import run_pipeline

    db = SessionLocal()
    try:
        # 既に実行中なら二重起動しない
        running = db.query(PipelineRun).filter(PipelineRun.status == "running").first()
        if running:
            logger.info("週次アウトリーチ: 既にパイプライン実行中のためスキップ")
            return {"started": False, "run_id": running.id, "leads": 0, "with_email": 0, "ready": 0}

        # 週次は控えめな量で収集（送信上限 50件/週 を意識）
        sources = ["yahoo", "rakuten", "google", "duckduckgo"]
        run = PipelineRun(
            sources=json.dumps(sources),
            keywords_count=0,
            skip_mx=1,
            status="pending",
            mode="ec",
            category_config=None,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    logger.info(f"週次アウトリーチ開始: run_id={run_id}")
    await run_pipeline(run_id)

    # 結果を集計
    db = SessionLocal()
    try:
        results = db.query(PipelineResult).filter(PipelineResult.run_id == run_id).all()
        total = len(results)
        with_email = sum(1 for r in results if r.email)
        ready = sum(
            1 for r in results
            if r.email and (r.personalized_subject or r.personalized_body or r.proposal)
        )
        cap = 50
        cfg = db.query(AppSettings).first()
        if cfg:
            cap = getattr(cfg, "weekly_outreach_send_cap", 50) or 50
    finally:
        db.close()

    await _notify(total, with_email, ready, cap, run_id)
    return {"started": True, "run_id": run_id, "leads": total, "with_email": with_email, "ready": ready}


async def _notify(total: int, with_email: int, ready: int, cap: int, run_id: int) -> None:
    if not (settings.LINE_CHANNEL_ACCESS_TOKEN and settings.LINE_USER_ID):
        return
    lines = [
        "📬 今週の自動アウトリーチが準備できました",
        "",
        f"・収集した見込み客: {total}件",
        f"・メール取得済み: {with_email}件",
        f"・メール下書きあり: {ready}件",
        "",
        f"レビューして送信してください（送信目安 {cap}件/週・送信はあなたの操作で実行）:",
        f"{BASE_URL}/pipeline",
    ]
    try:
        await line_service.push_text_message("\n".join(lines)[:4900])
        logger.info("週次アウトリーチ: 準備完了をLINE通知")
    except Exception as e:
        logger.error(f"週次アウトリーチ通知エラー: {e}")


async def weekly_outreach_scheduler() -> None:
    """10分ごとにチェックし、指定曜日・時刻を過ぎていてその週が未実行なら実行する。"""
    await asyncio.sleep(45)
    logger.info("週次アウトリーチスケジューラ開始（DB設定で有効/無効を制御）")

    while True:
        try:
            cfg = _get_cfg()
            if cfg and getattr(cfg, "weekly_outreach_enabled", False):
                now = datetime.now(JST)
                week = _iso_week(now)
                target_wd = getattr(cfg, "weekly_outreach_weekday", 0)
                target_hh = getattr(cfg, "weekly_outreach_hour_jst", 9)
                last_week = getattr(cfg, "weekly_outreach_last_week", None)
                # 今週が未実行 かつ 指定曜日・時刻を過ぎている
                reached = (now.weekday() > target_wd) or (
                    now.weekday() == target_wd and now.hour >= target_hh
                )
                if last_week != week and reached:
                    # 先に「実行済み」を立ててから走らせる（重い処理中の二重起動防止）
                    _mark_run(week)
                    try:
                        await run_weekly_outreach()
                    except Exception as e:
                        logger.error(f"週次アウトリーチ実行エラー: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"週次アウトリーチスケジューラエラー: {e}")
        await asyncio.sleep(600)

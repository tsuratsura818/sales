"""週次自動アウトリーチ: 毎週指定の曜日・時刻に
  1) 企業検索（SerpAPI＝普通のGoogle検索）を登録キーワードで自動実行
  2) サイト分析・メールアドレス抽出・スコアリング（=関連性の高いリスト化）
  3) 準備完了を LINE 通知

「リスト収集(スクレイパー)」ではなく「企業検索」を使う（関連性が高く・安定）。
提案文(AI下書き)は背景ではローカルClaudeを使えないため生成しない。ユーザーが
/leads でレビューする際にローカルClaude(ブリッジ=課金ゼロ)で都度生成する方針。
実際の送信もレビュー後に手動。週1回だけ実行（last_week = ISO週で管理）。
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_settings import AppSettings
from app.models.search_job import SearchJob
from app.models.lead import Lead
from app.models.pipeline_keyword import PipelineKeyword
from app.services import line_service

# 週あたりに回す企業検索キーワード数（SerpAPI無料枠250/月を考慮）と1キーワードの取得件数
KW_PER_WEEK = 3
RESULTS_PER_KEYWORD = 25

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
    from app.tasks import task_queue

    # 登録キーワードから今週分をローテーション選択
    db = SessionLocal()
    try:
        kws = (
            db.query(PipelineKeyword)
            .filter(PipelineKeyword.enabled == 1)
            .order_by(PipelineKeyword.id)
            .all()
        )
        if not kws:
            await _notify_text(
                "📬 週次アウトリーチ\n検索キーワードが未登録です。\n"
                f"{BASE_URL}/pipeline/keywords で登録してください。"
            )
            return {"started": False, "run_id": None, "leads": 0, "with_email": 0, "ready": 0}

        total_kw = len(kws)
        _, week_no, _ = datetime.now(JST).isocalendar()
        offset = (week_no * KW_PER_WEEK) % total_kw
        selected = [kws[(offset + i) % total_kw] for i in range(min(KW_PER_WEEK, total_kw))]

        job_ids = []
        kw_labels = []
        for kw in selected:
            job = SearchJob(
                query=kw.keyword,
                industry=kw.industry,
                num_results=RESULTS_PER_KEYWORD,
                search_method="serpapi",
                status="pending",
                auto_generate_proposal=False,  # 背景ではローカルClaude不可。下書きはレビュー時に生成
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            job_ids.append(job.id)
            kw_labels.append(kw.keyword)

        cap = 50
        cfg = db.query(AppSettings).first()
        if cfg:
            cap = getattr(cfg, "weekly_outreach_send_cap", 50) or 50
    finally:
        db.close()

    logger.info(f"週次アウトリーチ(企業検索)開始: jobs={job_ids} kw={kw_labels}")

    # 各検索ジョブを順に実行（企業検索→サイト分析→スコアリング）
    for jid in job_ids:
        try:
            await task_queue._run_search_job(jid)
        except Exception as e:
            logger.error(f"週次アウトリーチ 検索ジョブ {jid} エラー: {e}")

    # 集計
    db = SessionLocal()
    try:
        leads = db.query(Lead).filter(Lead.search_job_id.in_(job_ids)).all()
        total = len(leads)
        with_email = sum(1 for l in leads if l.contact_email)
    finally:
        db.close()

    await _notify(total, with_email, kw_labels, cap)
    return {"started": True, "run_id": job_ids, "leads": total, "with_email": with_email, "ready": with_email}


async def _notify_text(text: str) -> None:
    if not (settings.LINE_CHANNEL_ACCESS_TOKEN and settings.LINE_USER_ID):
        return
    try:
        await line_service.push_text_message(text[:4900])
    except Exception as e:
        logger.error(f"週次アウトリーチ通知エラー: {e}")


async def _notify(total: int, with_email: int, kw_labels: list, cap: int) -> None:
    kw_str = "、".join(kw_labels) if kw_labels else "-"
    lines = [
        "📬 今週の自動アウトリーチ（企業検索）が完了しました",
        "",
        f"・検索キーワード: {kw_str}",
        f"・見込み客: {total}件",
        f"・メール取得済み: {with_email}件",
        "",
        f"/leads でレビュー → 提案文をローカルClaudeで生成 → 送信（目安 {cap}件/週）:",
        f"{BASE_URL}/leads",
    ]
    await _notify_text("\n".join(lines))
    logger.info("週次アウトリーチ: 完了をLINE通知")


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

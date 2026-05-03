import asyncio
import logging
import time
from datetime import datetime

from app.config import get_settings
from app.database import SessionLocal
from app.models.job_application import JobApplication
from app.models.job_listing import JobListing
from app.models.monitor_log import MonitorLog
from app.services import crowdworks_service, job_matcher, line_service

settings = get_settings()
logger = logging.getLogger(__name__)


async def job_monitor() -> None:
    """バックグラウンドでCrowdWorks/Lancersの案件を定期チェックしLINE通知する"""
    await asyncio.sleep(15)

    # LINE未設定の場合はスキップ
    if not settings.LINE_CHANNEL_ACCESS_TOKEN or not settings.LINE_USER_ID:
        logger.warning("LINE未設定のため、ジョブモニターをスキップ")
        _log_run("skipped", "LINE未設定")
        return

    # CW/LC認証が両方未設定の場合もスキップ
    if not settings.CROWDWORKS_EMAIL and not settings.LANCERS_EMAIL:
        logger.warning("CW/LC認証未設定のため、ジョブモニターをスキップ")
        _log_run("skipped", "CW/LC認証未設定")
        return

    logger.info("ジョブモニター開始")

    while True:
        from app.services.settings_service import get_monitor_settings
        ms = get_monitor_settings()
        interval_seconds = ms.monitor_interval_minutes * 60

        start = time.time()
        try:
            cw_count, lc_count, notified = await _monitor_cycle()
            duration = round(time.time() - start, 1)
            msg = f"CW:{cw_count} LC:{lc_count} 通知:{notified}"
            logger.info(f"モニターサイクル完了 ({duration}s): {msg}")
            _log_run("success", msg, cw_count, lc_count, notified, duration)
        except Exception as e:
            duration = round(time.time() - start, 1)
            logger.error(f"ジョブモニターエラー: {e}")
            _log_run("error", str(e)[:500], duration_sec=duration)

        await asyncio.sleep(interval_seconds)


def _log_run(
    status: str,
    message: str | None = None,
    cw_count: int | None = None,
    lc_count: int | None = None,
    notified_count: int | None = None,
    duration_sec: float | None = None,
) -> None:
    """モニター実行ログをDBに保存"""
    try:
        db = SessionLocal()
        log = MonitorLog(
            run_at=datetime.now(),
            status=status,
            message=message,
            cw_count=cw_count,
            lc_count=lc_count,
            notified_count=notified_count,
            duration_sec=duration_sec,
        )
        db.add(log)
        db.commit()
        db.close()
    except Exception as e:
        logger.error(f"モニターログ保存失敗: {e}")


async def _monitor_cycle() -> tuple[int, int, int]:
    """1回の監視サイクル: スクレイピング → AI評価 → LINE通知。件数を返す。"""
    db = SessionLocal()
    notified = 0
    try:
        known_ids = set(
            eid for (eid,) in db.query(JobListing.external_id).all()
        )
        known_titles = set(
            t for (t,) in db.query(JobListing.title).all()
        )

        # CrowdWorksのみ自動取得（LancersはクラウドIPブロックのため手動取得に変更）
        cw_jobs = []
        if settings.CROWDWORKS_EMAIL:
            cw_jobs = await _safe_fetch(crowdworks_service.fetch_new_jobs, known_ids, known_titles)

        all_new_jobs = cw_jobs
        if not all_new_jobs:
            logger.debug("新規案件なし")
            return len(cw_jobs), 0, 0

        logger.info(f"新規案件 {len(all_new_jobs)}件 (CW:{len(cw_jobs)})")

        for job_data in all_new_jobs:
            try:
                listing = JobListing(
                    platform=job_data["platform"],
                    external_id=job_data["external_id"],
                    url=job_data["url"],
                    title=job_data["title"],
                    description=job_data.get("description", ""),
                    category=job_data.get("category"),
                    budget_min=job_data.get("budget_min"),
                    budget_max=job_data.get("budget_max"),
                    budget_type=job_data.get("budget_type"),
                    deadline=job_data.get("deadline"),
                    client_name=job_data.get("client_name"),
                    client_rating=job_data.get("client_rating"),
                    client_review_count=job_data.get("client_review_count"),
                    status="analyzing",
                )
                db.add(listing)
                db.commit()
                db.refresh(listing)

                eval_result = await job_matcher.evaluate_job(
                    title=listing.title,
                    description=listing.description or "",
                    budget_min=listing.budget_min,
                    budget_max=listing.budget_max,
                    budget_type=listing.budget_type,
                    client_name=listing.client_name,
                    client_rating=listing.client_rating,
                    platform=listing.platform,
                )

                listing.match_score = eval_result["score"]
                listing.match_reason = eval_result["reason"]
                if eval_result.get("category"):
                    listing.category = eval_result["category"]

                from app.services.settings_service import get_monitor_settings
                ms = get_monitor_settings()
                if eval_result["score"] >= ms.match_threshold:
                    budget_text = "未定"
                    if listing.budget_min and listing.budget_max:
                        if listing.budget_min == listing.budget_max:
                            budget_text = f"{listing.budget_min:,}円"
                        else:
                            budget_text = f"{listing.budget_min:,}〜{listing.budget_max:,}円"

                    # 提案文を即生成 → 提案文付きでLINE通知（webhook不要、コピペ運用）
                    try:
                        proposal_text = await job_matcher.generate_proposal(
                            title=listing.title,
                            description=listing.description or "",
                            budget_min=listing.budget_min,
                            budget_max=listing.budget_max,
                            platform=listing.platform,
                        )
                        application = JobApplication(
                            job_listing_id=listing.id,
                            proposal_text=proposal_text,
                            result_status="pending",
                        )
                        db.add(application)
                        listing.status = "review"
                        await line_service.push_job_with_proposal(
                            title=listing.title[:80],
                            platform=listing.platform,
                            score=eval_result["score"],
                            reason=eval_result["reason"],
                            budget_text=budget_text,
                            job_url=listing.url,
                            proposal_text=proposal_text,
                            job_id=listing.id,
                        )
                    except Exception as gen_err:
                        logger.error(f"提案文生成失敗 (job_id={listing.id}): {gen_err}")
                        listing.status = "notified"
                        await line_service.push_text_message(
                            f"⚠️ 提案文生成失敗\n【{listing.platform}】{listing.title[:60]}\n"
                            f"スコア: {eval_result['score']} / {eval_result['reason']}\n"
                            f"{listing.url}"
                        )
                    listing.notified_at = datetime.now()
                    notified += 1
                else:
                    listing.status = "skipped"

                db.commit()
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"案件処理エラー ({job_data.get('title', '?')}): {e}")
                try:
                    listing.status = "error"
                    db.commit()
                except Exception:
                    pass

    finally:
        db.close()

    return len(cw_jobs), 0, notified


async def _safe_fetch(fetch_func, known_ids: set, known_titles: set) -> list[dict]:
    """エラー時は空リストを返す安全なfetch"""
    try:
        return await fetch_func(known_ids, known_titles)
    except Exception as e:
        logger.error(f"Fetchエラー ({fetch_func.__module__}): {e}")
        return []


async def _empty_list() -> list[dict]:
    return []

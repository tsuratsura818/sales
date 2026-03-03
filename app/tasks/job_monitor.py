import asyncio
import logging
from datetime import datetime

from app.config import get_settings
from app.database import SessionLocal
from app.models.job_listing import JobListing
from app.services import crowdworks_service, lancers_service, job_matcher, line_service

settings = get_settings()
logger = logging.getLogger(__name__)


async def job_monitor() -> None:
    """バックグラウンドでCrowdWorks/Lancersの案件を定期チェックしLINE通知する"""
    # 起動直後は少し待つ（DB初期化完了を待つ）
    await asyncio.sleep(15)

    # LINE未設定の場合はスキップ
    if not settings.LINE_CHANNEL_ACCESS_TOKEN or not settings.LINE_USER_ID:
        logger.warning("LINE未設定のため、ジョブモニターをスキップ")
        return

    # CW/LC認証が両方未設定の場合もスキップ
    if not settings.CROWDWORKS_EMAIL and not settings.LANCERS_EMAIL:
        logger.warning("CW/LC認証未設定のため、ジョブモニターをスキップ")
        return

    logger.info("ジョブモニター開始")
    interval_seconds = settings.JOB_MONITOR_INTERVAL_MINUTES * 60

    while True:
        try:
            await _monitor_cycle()
        except Exception as e:
            logger.error(f"ジョブモニターエラー: {e}")

        await asyncio.sleep(interval_seconds)


async def _monitor_cycle() -> None:
    """1回の監視サイクル: スクレイピング → AI評価 → LINE通知"""
    db = SessionLocal()
    try:
        # 既知のexternal_idを取得（重複防止）
        known_ids = set(
            eid for (eid,) in db.query(JobListing.external_id).all()
        )

        # CW/LCから並行して新着を取得
        tasks = []
        if settings.CROWDWORKS_EMAIL:
            tasks.append(_safe_fetch(crowdworks_service.fetch_new_jobs, known_ids))
        else:
            tasks.append(_empty_list())
        if settings.LANCERS_EMAIL:
            tasks.append(_safe_fetch(lancers_service.fetch_new_jobs, known_ids))
        else:
            tasks.append(_empty_list())

        results = await asyncio.gather(*tasks)
        cw_jobs = results[0]
        lc_jobs = results[1]

        all_new_jobs = cw_jobs + lc_jobs
        if not all_new_jobs:
            logger.debug("新規案件なし")
            return

        logger.info(f"新規案件 {len(all_new_jobs)}件 (CW:{len(cw_jobs)} LC:{len(lc_jobs)})")

        for job_data in all_new_jobs:
            try:
                # DBに保存
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

                # Claudeで評価
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

                # 閾値以上ならLINE通知
                if eval_result["score"] >= settings.JOB_MATCH_THRESHOLD:
                    listing.status = "notified"

                    budget_text = "未定"
                    if listing.budget_min and listing.budget_max:
                        if listing.budget_min == listing.budget_max:
                            budget_text = f"{listing.budget_min:,}円"
                        else:
                            budget_text = f"{listing.budget_min:,}〜{listing.budget_max:,}円"

                    deadline_text = "期限なし"
                    if listing.deadline:
                        deadline_text = listing.deadline.strftime("%Y/%m/%d")

                    msg_id = await line_service.push_job_flex_message(
                        job_id=listing.id,
                        title=listing.title[:60],
                        platform=listing.platform,
                        budget_text=budget_text,
                        deadline_text=deadline_text,
                        match_score=eval_result["score"],
                        match_reason=eval_result["reason"],
                        job_url=listing.url,
                    )
                    listing.line_message_id = msg_id
                    listing.notified_at = datetime.now()
                else:
                    listing.status = "skipped"

                db.commit()

                # AI評価のレート制限
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


async def _safe_fetch(fetch_func, known_ids: set) -> list[dict]:
    """エラー時は空リストを返す安全なfetch"""
    try:
        return await fetch_func(known_ids)
    except Exception as e:
        logger.error(f"Fetchエラー ({fetch_func.__module__}): {e}")
        return []


async def _empty_list() -> list[dict]:
    return []

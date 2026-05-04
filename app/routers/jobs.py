import asyncio
import json as json_mod
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db, SessionLocal
from app.models.job_listing import JobListing
from app.models.job_application import JobApplication
from app.models.monitor_settings import MonitorSettings
from app.models.heartbeat import Heartbeat
from app.config import get_settings
from app.services.settings_service import get_monitor_settings

settings = get_settings()
logger = logging.getLogger(__name__)
router = APIRouter(tags=["jobs"])


def _get_templates():
    from main import templates
    return templates


# ---------- HTMLページ ----------

@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    status: str | None = None,
    platform: str | None = None,
    db: Session = Depends(get_db),
):
    """案件モニターダッシュボード"""
    query = db.query(JobListing)
    if status:
        query = query.filter(JobListing.status == status)
    if platform:
        query = query.filter(JobListing.platform == platform)

    listings = query.order_by(desc(JobListing.created_at)).limit(100).all()

    counts = {
        "total": db.query(JobListing).count(),
        "new": db.query(JobListing).filter(JobListing.status == "new").count(),
        "notified": db.query(JobListing).filter(JobListing.status == "notified").count(),
        "approved": db.query(JobListing).filter(JobListing.status == "approved").count(),
        "review": db.query(JobListing).filter(JobListing.status == "review").count(),
        "applied": db.query(JobListing).filter(JobListing.status == "applied").count(),
        "skipped": db.query(JobListing).filter(JobListing.status == "skipped").count(),
    }

    return _get_templates().TemplateResponse(request, "jobs.html", {
        "listings": listings,
        "counts": counts,
        "current_status": status,
        "current_platform": platform,
    })


# ---------- JSON API ----------

@router.get("/api/jobs")
async def list_jobs(
    status: str | None = None,
    platform: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """案件一覧を返す"""
    query = db.query(JobListing)
    if status:
        query = query.filter(JobListing.status == status)
    if platform:
        query = query.filter(JobListing.platform == platform)

    listings = query.order_by(desc(JobListing.created_at)).limit(limit).all()
    return [
        {
            "id": j.id,
            "platform": j.platform,
            "title": j.title,
            "url": j.url,
            "category": j.category,
            "budget_min": j.budget_min,
            "budget_max": j.budget_max,
            "status": j.status,
            "match_score": j.match_score,
            "match_reason": j.match_reason,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in listings
    ]


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: int, db: Session = Depends(get_db)):
    """案件詳細を返す"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="案件が見つかりません")

    application = None
    if job.application:
        application = {
            "id": job.application.id,
            "proposal_text": job.application.proposal_text,
            "applied_at": job.application.applied_at.isoformat() if job.application.applied_at else None,
            "result_status": job.application.result_status,
        }

    return {
        "id": job.id,
        "platform": job.platform,
        "external_id": job.external_id,
        "url": job.url,
        "title": job.title,
        "description": job.description,
        "category": job.category,
        "budget_min": job.budget_min,
        "budget_max": job.budget_max,
        "budget_type": job.budget_type,
        "deadline": job.deadline.isoformat() if job.deadline else None,
        "client_name": job.client_name,
        "client_rating": job.client_rating,
        "status": job.status,
        "match_score": job.match_score,
        "match_reason": job.match_reason,
        "notified_at": job.notified_at.isoformat() if job.notified_at else None,
        "application": application,
    }


@router.post("/api/jobs/{job_id}/approve")
async def approve_job(job_id: int, db: Session = Depends(get_db)):
    """案件を承認して応募処理を開始"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="案件が見つかりません")
    if job.status == "applied":
        raise HTTPException(status_code=400, detail="既に応募済みです")

    job.status = "approved"
    db.commit()

    asyncio.create_task(_apply_to_job(job_id))
    return {"success": True, "message": "応募処理を開始しました"}


@router.post("/api/jobs/{job_id}/skip")
async def skip_job(job_id: int, db: Session = Depends(get_db)):
    """案件をスキップ"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="案件が見つかりません")
    job.status = "skipped"
    db.commit()
    return {"success": True}


@router.get("/api/jobs/{job_id}/proposal")
async def get_proposal(job_id: int, db: Session = Depends(get_db)):
    """提案文を取得"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="案件が見つかりません")

    application = db.query(JobApplication).filter(
        JobApplication.job_listing_id == job_id
    ).first()

    return {
        "job_id": job.id,
        "title": job.title,
        "status": job.status,
        "proposal_text": application.proposal_text if application else None,
        "result_status": application.result_status if application else None,
    }


@router.post("/api/jobs/{job_id}/confirm")
async def confirm_proposal(job_id: int, db: Session = Depends(get_db)):
    """提案文を承認して応募を実行"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="案件が見つかりません")
    if job.status == "applied":
        raise HTTPException(status_code=400, detail="既に応募済みです")
    if job.status != "review":
        raise HTTPException(status_code=400, detail="確認待ち状態ではありません")

    asyncio.create_task(_submit_application(job_id))
    return {"success": True, "message": "応募を送信します"}


@router.post("/api/jobs/{job_id}/regenerate")
async def regenerate_proposal(job_id: int, db: Session = Depends(get_db)):
    """提案文を再生成"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="案件が見つかりません")
    if job.status == "applied":
        raise HTTPException(status_code=400, detail="既に応募済みです")

    job.status = "approved"
    db.commit()

    asyncio.create_task(_apply_to_job(job_id))
    return {"success": True, "message": "提案文を再生成します"}


# ---------- Lancers手動取得（ローカルPC→サーバー） ----------

@router.get("/api/job-monitor/known")
async def get_known_jobs(db: Session = Depends(get_db)):
    """既知の案件IDとタイトルを返す（ローカルスクリプト用）"""
    known_ids = [
        eid for (eid,) in db.query(JobListing.external_id).all()
    ]
    known_titles = [
        t for (t,) in db.query(JobListing.title).all()
    ]
    return {"external_ids": known_ids, "titles": known_titles}


@router.post("/api/job-monitor/import")
async def import_jobs(request: Request, db: Session = Depends(get_db)):
    """ローカルPCから送信された案件データを受け取ってAI評価→LINE通知"""
    from app.services import job_matcher, line_service

    body = await request.json()
    jobs = body.get("jobs", [])

    if not jobs:
        return {"success": True, "new_count": 0, "notified_count": 0, "message": "新規案件なし"}

    notified = 0
    for job_data in jobs:
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

            ms = get_monitor_settings(db)
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
            logger.error(f"Lancers案件処理エラー ({job_data.get('title', '?')}): {e}")
            try:
                listing.status = "error"
                db.commit()
            except Exception:
                pass

    return {
        "success": True,
        "new_count": len(jobs),
        "notified_count": notified,
        "message": f"Lancers {len(jobs)}件取得、{notified}件LINE通知",
    }


# ---------- 半自動応募キュー（apply_helper.py 用） ----------

@router.post("/api/jobs/{job_id}/request-open")
async def request_open(job_id: int, db: Session = Depends(get_db)):
    """ユーザーが「🚀 応募ページを開く」を押した。ローカルapply_helperが拾う"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(404, "案件が見つかりません")
    job.status = "open_requested"
    db.commit()
    return {"success": True}


@router.get("/api/jobs/open-queue")
async def get_open_queue(db: Session = Depends(get_db)):
    """ローカルapply_helperが定期取得するキュー"""
    jobs = db.query(JobListing).filter(JobListing.status == "open_requested").all()
    result = []
    for j in jobs:
        application = db.query(JobApplication).filter(JobApplication.job_listing_id == j.id).first()
        result.append({
            "id": j.id,
            "platform": j.platform,
            "title": j.title,
            "url": j.url,
            "proposal_text": application.proposal_text if application else "",
        })
    return result


@router.post("/api/jobs/{job_id}/mark-opened")
async def mark_opened(job_id: int, db: Session = Depends(get_db)):
    """apply_helperがブラウザ起動完了を報告"""
    job = db.query(JobListing).filter(JobListing.id == job_id).first()
    if not job:
        raise HTTPException(404, "見つかりません")
    if job.status == "open_requested":
        job.status = "opened"
    db.commit()
    return {"success": True}


# ---------- Heartbeat API（ローカル実行バッチの生存確認） ----------

@router.post("/api/heartbeat/{name}")
async def post_heartbeat(name: str, request: Request, db: Session = Depends(get_db)):
    """ローカル実行バッチからの生存確認 (POST body: {status, message?, count?})"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    status_text = (body.get("status") or "ok")[:40]
    message = (body.get("message") or "")[:500]
    count_val = body.get("count")
    if isinstance(count_val, (int, float)):
        count_val = int(count_val)
    else:
        count_val = None

    row = db.query(Heartbeat).filter(Heartbeat.name == name).first()
    if not row:
        row = Heartbeat(name=name)
        db.add(row)
    row.last_at = datetime.now()
    row.last_status = status_text
    row.last_message = message
    row.last_count = count_val
    db.commit()
    return {"success": True, "name": name, "last_at": row.last_at.isoformat()}


@router.get("/api/heartbeat")
async def list_heartbeats(db: Session = Depends(get_db)):
    """全heartbeatの一覧（ダッシュボード用）"""
    rows = db.query(Heartbeat).all()
    return [
        {
            "name": r.name,
            "last_at": r.last_at.isoformat() if r.last_at else None,
            "last_status": r.last_status,
            "last_message": r.last_message,
            "last_count": r.last_count,
            "age_sec": int((datetime.now() - r.last_at).total_seconds()) if r.last_at else None,
        }
        for r in rows
    ]


# ---------- モニター設定 API ----------

@router.get("/api/monitor-settings")
async def get_settings_api(db: Session = Depends(get_db)):
    """モニター設定を取得"""
    from app.services.job_matcher import EVALUATE_SYSTEM_PROMPT

    ms = get_monitor_settings(db)
    return {
        "match_threshold": ms.match_threshold,
        "monitor_interval_minutes": ms.monitor_interval_minutes,
        "user_profile_text": ms.user_profile_text,
        "cw_categories": ms.cw_categories,
        "lc_categories": ms.lc_categories,
        "evaluate_system_prompt": ms.evaluate_system_prompt,
        "default_evaluate_prompt": EVALUATE_SYSTEM_PROMPT,
    }


@router.put("/api/monitor-settings")
async def update_settings_api(request: Request, db: Session = Depends(get_db)):
    """モニター設定を更新（upsert）"""
    body = await request.json()

    row = db.query(MonitorSettings).first()
    if not row:
        row = MonitorSettings()
        db.add(row)

    if "match_threshold" in body:
        val = int(body["match_threshold"])
        if not (0 <= val <= 100):
            raise HTTPException(400, "閾値は0〜100の範囲で指定してください")
        row.match_threshold = val

    if "monitor_interval_minutes" in body:
        val = int(body["monitor_interval_minutes"])
        if val < 10:
            raise HTTPException(400, "間隔は10分以上を指定してください")
        row.monitor_interval_minutes = val

    if "user_profile_text" in body:
        row.user_profile_text = str(body["user_profile_text"])[:5000]

    if "cw_categories" in body or "lc_categories" in body:
        existing = {}
        if row.search_categories:
            try:
                existing = json_mod.loads(row.search_categories)
            except (json_mod.JSONDecodeError, TypeError):
                pass
        if "cw_categories" in body:
            existing["crowdworks"] = [int(c) for c in body["cw_categories"]]
        if "lc_categories" in body:
            existing["lancers"] = [int(c) for c in body["lc_categories"]]
        row.search_categories = json_mod.dumps(existing)

    if "evaluate_system_prompt" in body:
        row.evaluate_system_prompt = str(body["evaluate_system_prompt"])[:10000]

    db.commit()
    return {"success": True, "message": "設定を保存しました"}


# ---------- 応募バックグラウンド処理 ----------

async def _regenerate_with_new_format(job_id: int) -> None:
    """提案文を再生成 → 新フォーマット（テキスト+ボタンFlex）でLINE再送信"""
    from app.services import job_matcher, line_service

    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job:
            return

        try:
            proposal_text = await job_matcher.generate_proposal(
                title=job.title,
                description=job.description or "",
                budget_min=job.budget_min,
                budget_max=job.budget_max,
                platform=job.platform,
            )
            application = db.query(JobApplication).filter(JobApplication.job_listing_id == job_id).first()
            if application:
                application.proposal_text = proposal_text
            else:
                application = JobApplication(
                    job_listing_id=job_id,
                    proposal_text=proposal_text,
                    result_status="pending",
                )
                db.add(application)
            job.status = "review"
            db.commit()

            budget_text = "未定"
            if job.budget_min and job.budget_max:
                if job.budget_min == job.budget_max:
                    budget_text = f"{job.budget_min:,}円"
                else:
                    budget_text = f"{job.budget_min:,}〜{job.budget_max:,}円"

            await line_service.push_job_with_proposal(
                title=job.title[:80],
                platform=job.platform,
                score=job.match_score or 0,
                reason=job.match_reason or "",
                budget_text=budget_text,
                job_url=job.url,
                proposal_text=proposal_text,
                job_id=job.id,
            )
        except Exception as e:
            logger.error(f"再生成エラー (job_id={job_id}): {e}")
            await line_service.push_text_message(f"⚠️ 再生成失敗: {job.title[:40]}\n{str(e)[:100]}")
    finally:
        db.close()


async def _apply_to_job(job_id: int) -> None:
    """提案文を生成してLINEで確認を求める（送信はユーザー承認後）"""
    from app.services import job_matcher, line_service

    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        if not job or job.status != "approved":
            return

        job.status = "generating"
        db.commit()

        # 応募レコード作成
        application = JobApplication(
            job_listing_id=job.id,
            result_status="pending",
        )
        db.add(application)
        db.commit()
        db.refresh(application)

        try:
            # Claude で提案文を生成
            proposal_text = await job_matcher.generate_proposal(
                title=job.title,
                description=job.description or "",
                budget_min=job.budget_min,
                budget_max=job.budget_max,
                platform=job.platform,
            )
            application.proposal_text = proposal_text
            job.status = "review"
            db.commit()

            # LINEで提案文を送信して確認を求める
            await line_service.push_proposal_review(
                job_id=job.id,
                title=job.title[:50],
                proposal_text=proposal_text,
            )

        except Exception as e:
            logger.error(f"提案文生成エラー (job_id={job_id}): {e}")
            job.status = "error"
            db.commit()
            await line_service.push_text_message(
                f"提案文生成エラー: {job.title[:40]}\n{str(e)[:100]}"
            )

    finally:
        db.close()


async def _submit_application(job_id: int) -> None:
    """承認済みの提案文をPlaywrightで送信する"""
    from app.services import crowdworks_service, lancers_service, line_service

    db = SessionLocal()
    try:
        job = db.query(JobListing).filter(JobListing.id == job_id).first()
        application = db.query(JobApplication).filter(
            JobApplication.job_listing_id == job_id
        ).first()
        if not job or not application or not application.proposal_text:
            return

        job.status = "applying"
        db.commit()

        try:
            if job.platform == "crowdworks":
                success = await crowdworks_service.submit_application(
                    job.url, application.proposal_text, application.proposed_budget
                )
            else:
                success = await lancers_service.submit_application(
                    job.url, application.proposal_text, application.proposed_budget
                )

            if success:
                application.result_status = "submitted"
                application.applied_at = datetime.now()
                job.status = "applied"
                db.commit()
                await line_service.push_text_message(
                    f"応募完了: {job.title[:40]}\n提案文を送信しました。"
                )
            else:
                application.result_status = "pending"
                application.error_message = "送信確認ができませんでした"
                job.status = "error"
                db.commit()
                await line_service.push_text_message(
                    f"応募エラー: {job.title[:40]}\n手動で確認してください:\n{job.url}"
                )

        except Exception as e:
            logger.error(f"応募送信エラー (job_id={job_id}): {e}")
            application.error_message = str(e)[:500]
            job.status = "error"
            db.commit()
            await line_service.push_text_message(
                f"応募エラー: {job.title[:40]}\n{str(e)[:100]}"
            )

    finally:
        db.close()

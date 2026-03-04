import asyncio
import time
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.search_job import SearchJob
from app.models.lead import Lead
from app.services import serpapi_service, analyzer
from app.tasks import progress_store
from app.config import get_settings

settings = get_settings()

_queue: asyncio.Queue = asyncio.Queue()

# 1件あたりの分析タイムアウト（秒）
LEAD_TIMEOUT = 30
# 検索結果枯渇と判断するページ上限
MAX_PAGES = 50
# 連続して新規リードが0件のページ数でストップ
MAX_EMPTY_PAGES = 3


def enqueue(job_id: int) -> None:
    _queue.put_nowait(job_id)


async def worker() -> None:
    """アプリ起動時から常駐するバックグラウンドワーカー"""
    while True:
        job_id = await _queue.get()
        try:
            await _run_search_job(job_id)
        except Exception as e:
            db = SessionLocal()
            try:
                job = db.query(SearchJob).filter(SearchJob.id == job_id).first()
                if job:
                    job.status = "failed"
                    job.error_message = str(e)[:500]
                    db.commit()
            finally:
                db.close()
        finally:
            _queue.task_done()


async def _analyze_one(lead_id: int, url: str) -> float:
    """1件のリードを分析し、所要時間（秒）を返す"""
    t0 = time.time()
    analyze_db = SessionLocal()
    try:
        await asyncio.wait_for(
            analyzer.analyze_lead(lead_id, analyze_db),
            timeout=LEAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        try:
            stuck = analyze_db.query(Lead).filter(Lead.id == lead_id).first()
            if stuck and stuck.status == "analyzing":
                stuck.status = "error"
                stuck.analysis_error = f"Timeout ({LEAD_TIMEOUT}s)"
                analyze_db.commit()
        except Exception:
            pass
    except Exception:
        pass
    finally:
        analyze_db.close()
    return time.time() - t0


def _url_exists_in_db(db: Session, url: str) -> bool:
    """全ジョブ横断でURL重複チェック"""
    return db.query(Lead).filter(Lead.url == url).first() is not None


async def _run_search_job(job_id: int) -> None:
    db: Session = SessionLocal()
    try:
        job = db.query(SearchJob).filter(SearchJob.id == job_id).first()
        if not job:
            return

        job.status = "running"
        db.commit()

        target = job.num_results  # ユーザー指定の有効件数
        lead_count = 0  # 作成したリード数（分析成功+エラー問わず）
        calls_used = 0
        page = 0
        elapsed_sum = 0.0
        analyzed_count = 0
        empty_page_streak = 0  # 連続して新規リードが0のページ数

        # 地域・業界を含む最適化クエリを構築
        optimized_query = serpapi_service.build_query(
            job.query, region=job.region, industry=job.industry
        )

        # 進捗ストア初期化
        progress_store.init_job(job_id, target)

        while lead_count < target and page < MAX_PAGES:
            # SerpAPI 1ページ取得（最適化クエリ使用）
            items, has_next = await serpapi_service.fetch_one_page(
                query=optimized_query, start=page * 10
            )
            calls_used += 1
            job.serpapi_calls_used = calls_used
            db.commit()

            if not items and not has_next:
                break  # 検索結果完全枯渇

            # セマフォで並列数制限
            semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_ANALYSIS)
            page_tasks = []
            page_new_leads = 0

            for item in items:
                url = item["url"]

                # DB全体で重複チェック
                if _url_exists_in_db(db, url):
                    continue

                # Lead作成
                lead = Lead(
                    search_job_id=job_id,
                    url=url,
                    title=item.get("title", ""),
                    status="new",
                )
                db.add(lead)
                db.commit()
                db.refresh(lead)
                page_new_leads += 1

                async def process_lead(lead_obj: Lead) -> None:
                    nonlocal lead_count, elapsed_sum, analyzed_count
                    async with semaphore:
                        await progress_store.update(
                            job_id, current_url=lead_obj.url
                        )
                        elapsed = await _analyze_one(lead_obj.id, lead_obj.url)

                        analyzed_count += 1
                        elapsed_sum += elapsed

                        # 分析成功・エラー問わずカウント（リストには表示する）
                        lead_count += 1

                        # 進捗更新
                        avg = elapsed_sum / analyzed_count if analyzed_count else 0
                        remaining = target - lead_count
                        concurrency = min(
                            settings.MAX_CONCURRENT_ANALYSIS, max(remaining, 1)
                        )
                        eta = int(avg * remaining / concurrency) if remaining > 0 else 0

                        job.analyzed_count = lead_count
                        job.total_urls = target
                        db.commit()

                        await progress_store.update(
                            job_id,
                            completed=lead_count,
                            total=target,
                            eta_seconds=eta,
                            avg_seconds=round(avg, 1),
                        )

                page_tasks.append(process_lead(lead))

            # このページの分析を並列実行
            if page_tasks:
                await asyncio.gather(*page_tasks, return_exceptions=True)

            # 連続空ページ判定（新規リードが0のページが続いたら停止）
            if page_new_leads == 0:
                empty_page_streak += 1
                if empty_page_streak >= MAX_EMPTY_PAGES:
                    break
            else:
                empty_page_streak = 0

            if not has_next:
                break  # SerpAPIに次ページなし

            page += 1
            await asyncio.sleep(0.5)

        job.status = "completed"
        job.total_urls = lead_count
        job.analyzed_count = lead_count
        job.completed_at = datetime.now()
        db.commit()

        await progress_store.update(
            job_id,
            status="completed",
            completed=lead_count,
            total=target,
            eta_seconds=0,
        )

    finally:
        db.close()

"""パイプライン実行オーケストレーター

コレクターの実行、スコアリング、結果保存、MailForgeインポートを一貫管理。
"""
import asyncio
import json
import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.pipeline import PipelineRun, PipelineResult
from .config import EC_PRIORITY, PROPOSAL_MAP, DEFAULT_PROPOSAL
from . import yahoo_collector, rakuten_collector, google_collector

log = logging.getLogger("pipeline.runner")


def _generate_proposal(platform: str, ec_status: str, industry: str) -> str:
    """ローカルで提案切り口を生成"""
    ec_lower = (ec_status or "").lower()
    ind_lower = (industry or platform or "").lower()

    for key, proposal in PROPOSAL_MAP.items():
        if key in ec_lower or key in ind_lower:
            return proposal
    return DEFAULT_PROPOSAL


def _score_lead(ec_status: str, email: str, company: str, location: str) -> tuple[int, str]:
    """リードスコアリング → (score, rank)

    S: 80+ (モール出店中 + 情報充実)
    A: 60-79 (モール出店 or 外部サービス)
    B: 40-59 (自社ECあり、情報やや不足)
    C: 0-39 (情報不足)
    """
    score = 0

    # EC状態
    priority = EC_PRIORITY.get(ec_status, 3)
    if priority == 0:
        score += 40  # モール出店のみ = 最優先
    elif priority == 1:
        score += 30  # BASE/STORES/カラーミー
    elif priority == 2:
        score += 15  # 自社ECあり

    # 情報充実度
    if email:
        score += 15
    if company and len(company) > 2:
        score += 15
    if location and len(location) > 5:
        score += 15
    if "@" in email and not email.startswith("info@"):
        score += 5  # 個人メールアドレスの方が返信率高い

    # ランク判定
    if score >= 80:
        rank = "S"
    elif score >= 60:
        rank = "A"
    elif score >= 40:
        rank = "B"
    else:
        rank = "C"

    return score, rank


async def _import_to_mailforge(leads: list[PipelineResult], db: Session) -> int:
    """ランクA以上のリードをMailForgeにインポート"""
    try:
        from app.services.mailforge_client import upsert_contacts, get_contacts
    except ImportError:
        log.warning("mailforge_client インポート不可、スキップ")
        return 0

    a_plus_leads = [l for l in leads if l.rank in ("S", "A")]
    if not a_plus_leads:
        return 0

    contacts = []
    for lead in a_plus_leads:
        contacts.append({
            "email": lead.email,
            "company": lead.company or "",
            "name": lead.company or "",
            "industry": lead.industry or "",
            "source": f"pipeline:{lead.source}",
            "notes": f"{lead.ec_status} | {lead.platform} | {lead.proposal or ''}",
        })

    try:
        result = await upsert_contacts(contacts)
        imported = len(contacts)
        log.info(f"MailForgeインポート: {imported}件 (S/Aランク)")

        for lead in a_plus_leads:
            lead.imported_to_mailforge = 1
        db.commit()

        return imported
    except Exception as e:
        log.error(f"MailForgeインポートエラー: {e}")
        return 0


async def run_pipeline(run_id: int):
    """パイプライン実行メイン"""
    db: Session = SessionLocal()
    start_time = time.time()

    try:
        run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
        if not run:
            log.error(f"PipelineRun {run_id} not found")
            return

        run.status = "running"
        run.progress_pct = 0
        run.progress_message = "初期化中..."
        db.commit()

        sources = json.loads(run.sources)
        seen_emails: set[str] = set()

        # 既存のパイプライン結果からメール重複除外
        existing = db.query(PipelineResult.email).all()
        for (email,) in existing:
            seen_emails.add(email.lower())
        log.info(f"既存メール: {len(seen_emails)}件をスキップ")

        all_leads = []
        source_breakdown: dict[str, int] = {}

        def on_progress(msg: str):
            run.progress_message = msg
            try:
                db.commit()
            except Exception:
                pass

        # Yahoo!
        if "yahoo" in sources:
            run.progress_pct = 5
            on_progress("Yahoo!ショッピング収集中...")
            yahoo_leads = await yahoo_collector.collect(seen_emails, on_progress)
            all_leads.extend(yahoo_leads)
            source_breakdown["yahoo"] = len(yahoo_leads)

        # 楽天
        if "rakuten" in sources:
            run.progress_pct = 35
            on_progress("楽天市場収集中...")
            rakuten_leads = await rakuten_collector.collect(seen_emails, on_progress)
            all_leads.extend(rakuten_leads)
            source_breakdown["rakuten"] = len(rakuten_leads)

        # Google
        if "google" in sources:
            run.progress_pct = 65
            on_progress("Google検索収集中...")
            google_leads = await google_collector.collect(seen_emails, on_progress)
            all_leads.extend(google_leads)
            source_breakdown["google"] = len(google_leads)

        # 重複排除（メールアドレスベース）
        run.progress_pct = 85
        on_progress("スコアリング中...")
        unique_emails: set[str] = set()
        deduped = []
        for lead in all_leads:
            if lead.email.lower() not in unique_emails:
                unique_emails.add(lead.email.lower())
                deduped.append(lead)
        all_leads = deduped

        # スコアリング + 提案生成 + DB保存
        pipeline_results: list[PipelineResult] = []
        for lead in all_leads:
            proposal = _generate_proposal(lead.platform, lead.ec_status, lead.industry)
            score, rank = _score_lead(lead.ec_status, lead.email, lead.company, lead.location)

            result = PipelineResult(
                run_id=run_id,
                email=lead.email,
                company=lead.company,
                industry=lead.industry,
                location=lead.location,
                website=lead.website,
                platform=lead.platform,
                ec_status=lead.ec_status,
                proposal=proposal,
                source=lead.source,
                shop_code=lead.shop_code,
                score=score,
                rank=rank,
            )
            db.add(result)
            pipeline_results.append(result)

        db.commit()

        # MailForgeインポート（ランクA以上）
        run.progress_pct = 90
        on_progress("MailForgeインポート中...")
        imported_count = await _import_to_mailforge(pipeline_results, db)

        # EC優先度でソート
        pipeline_results.sort(key=lambda r: EC_PRIORITY.get(r.ec_status or "", 3))

        # 実行結果を記録
        duration = int(time.time() - start_time)
        run.status = "completed"
        run.progress_pct = 100
        run.progress_message = f"完了: {len(all_leads)}件収集"
        run.total_found = len(all_leads)
        run.total_imported = imported_count
        run.duration_sec = duration
        run.source_breakdown = json.dumps(source_breakdown, ensure_ascii=False)
        run.completed_at = datetime.now()
        db.commit()

        log.info(f"パイプライン完了: {len(all_leads)}件 ({duration}秒)")
        log.info(f"  内訳: {source_breakdown}")
        log.info(f"  MailForgeインポート: {imported_count}件")

    except Exception as e:
        log.error(f"パイプラインエラー: {e}")
        try:
            run = db.query(PipelineRun).filter(PipelineRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.error_message = str(e)[:500]
                run.duration_sec = int(time.time() - start_time)
                run.completed_at = datetime.now()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()

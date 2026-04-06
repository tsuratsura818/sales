"""パイプライン実行オーケストレーター

コレクターの並列実行、ドメイン重複排除、スコアリング、
Shopify除外、MailForge非同期インポートを一貫管理。
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

# Shopify構築済みの場合は営業不要
SHOPIFY_INDICATORS = {"Shopify構築済み", "Shopify"}


def _generate_proposal(platform: str, ec_status: str, industry: str) -> str:
    """ローカルで提案切り口を生成"""
    ec_lower = (ec_status or "").lower()
    ind_lower = (industry or platform or "").lower()

    for key, proposal in PROPOSAL_MAP.items():
        if key in ec_lower or key in ind_lower:
            return proposal
    return DEFAULT_PROPOSAL


def _score_lead(ec_status: str, email: str, company: str, location: str, industry: str) -> tuple[int, str]:
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
        score += 40
    elif priority == 1:
        score += 30
    elif priority == 2:
        score += 15

    # 情報充実度
    if email:
        score += 15
    if company and len(company) > 2:
        score += 15
    if location and len(location) > 5:
        score += 15
    if "@" in email and not email.startswith("info@"):
        score += 5

    # 業種ボーナス（ギフト需要/EC親和性が高い業種）
    ind_lower = (industry or "").lower()
    high_value_keywords = ["和菓子", "洋菓子", "酒", "茶", "アパレル", "化粧品", "コスメ"]
    if any(kw in ind_lower for kw in high_value_keywords):
        score += 5

    if score >= 80:
        rank = "S"
    elif score >= 60:
        rank = "A"
    elif score >= 40:
        rank = "B"
    else:
        rank = "C"

    return score, rank


def _deduplicate(leads: list) -> list:
    """メールアドレス + ドメインレベルの重複排除"""
    seen_emails: set[str] = set()
    seen_domains: dict[str, int] = {}  # domain → best score index
    result: list = []

    for lead in leads:
        email_lower = lead.email.lower()
        if email_lower in seen_emails:
            continue
        seen_emails.add(email_lower)

        # ドメインレベル重複チェック（同一ドメインの複数アドレスを排除）
        domain = email_lower.split("@")[1] if "@" in email_lower else ""
        if domain in seen_domains:
            # 既存のリードとスコア比較（会社名の長さで暫定判定）
            existing_idx = seen_domains[domain]
            existing = result[existing_idx]
            if len(lead.company or "") > len(existing.company or ""):
                result[existing_idx] = lead  # より情報が多い方で上書き
            continue

        seen_domains[domain] = len(result)
        result.append(lead)

    removed = len(leads) - len(result)
    if removed > 0:
        log.info(f"重複排除: {removed}件削除 ({len(leads)} → {len(result)})")
    return result


async def _import_to_mailforge(leads: list[PipelineResult], db: Session) -> int:
    """ランクA以上のリードをMailForgeに非同期インポート"""
    try:
        from app.services.mailforge_client import upsert_contacts
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
            "company_name": lead.company or "",
            "industry": lead.industry or "",
            "website_url": lead.website or "",
            "notes": f"{lead.ec_status} | {lead.platform} | {lead.proposal or ''}",
        })

    try:
        # 同期関数なのでスレッドプールで実行してイベントループをブロックしない
        result = await asyncio.to_thread(upsert_contacts, contacts)
        imported = result.get("inserted", 0)
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

        # DBからキーワードを取得（有効なもののみ）
        from app.models.pipeline_keyword import PipelineKeyword
        db_keywords = db.query(PipelineKeyword).filter(PipelineKeyword.enabled == 1).all()
        keyword_list = [(kw.keyword, kw.industry) for kw in db_keywords]
        log.info(f"キーワード: {len(keyword_list)}件（DB）")

        # 既存の結果からメール重複除外（直近5回分に制限してメモリ節約）
        recent_run_ids = [
            r.id for r in db.query(PipelineRun.id)
            .filter(PipelineRun.status == "completed")
            .order_by(PipelineRun.created_at.desc())
            .limit(5).all()
        ]
        if recent_run_ids:
            existing = db.query(PipelineResult.email).filter(
                PipelineResult.run_id.in_(recent_run_ids)
            ).all()
            for (email,) in existing:
                seen_emails.add(email.lower())
        log.info(f"既存メール: {len(seen_emails)}件をスキップ")

        source_breakdown: dict[str, int] = {}

        # コレクターを並列実行（DBキーワードを渡す）
        tasks = []
        if "yahoo" in sources:
            run.progress_pct = 5
            run.progress_message = "Yahoo!ショッピング収集中..."
            db.commit()
            yahoo_kw = [(k, i) for k, i in keyword_list]
            tasks.append(("yahoo", yahoo_collector.collect(seen_emails, keywords=yahoo_kw)))
        if "rakuten" in sources:
            rakuten_kw = [(k, i) for k, i in keyword_list]
            tasks.append(("rakuten", rakuten_collector.collect(seen_emails, keywords=rakuten_kw)))
        if "google" in sources:
            tasks.append(("google", google_collector.collect(seen_emails)))

        all_leads = []
        if tasks:
            run.progress_message = "収集中（並列実行）..."
            db.commit()

            results = await asyncio.gather(
                *[coro for _, coro in tasks],
                return_exceptions=True,
            )

            for (source_name, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    log.error(f"{source_name} コレクターエラー: {result}")
                    source_breakdown[source_name] = 0
                else:
                    all_leads.extend(result)
                    source_breakdown[source_name] = len(result)

        # Shopify構築済みを除外
        before_shopify = len(all_leads)
        all_leads = [l for l in all_leads if l.ec_status not in SHOPIFY_INDICATORS]
        shopify_excluded = before_shopify - len(all_leads)
        if shopify_excluded > 0:
            log.info(f"Shopify構築済み除外: {shopify_excluded}件")

        # ドメインレベル重複排除
        run.progress_pct = 85
        run.progress_message = "スコアリング中..."
        db.commit()
        all_leads = _deduplicate(all_leads)

        # スコアリング + 提案生成 + DB保存
        pipeline_results: list[PipelineResult] = []
        for lead in all_leads:
            proposal = _generate_proposal(lead.platform, lead.ec_status, lead.industry)
            score, rank = _score_lead(lead.ec_status, lead.email, lead.company, lead.location, lead.industry)

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

        # MailForge非同期インポート（ランクA以上）
        run.progress_pct = 90
        run.progress_message = "MailForgeインポート中..."
        db.commit()
        imported_count = await _import_to_mailforge(pipeline_results, db)

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
            db.rollback()
    finally:
        db.close()

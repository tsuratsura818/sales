"""パイプライン実行オーケストレーター

コレクターの並列実行、ドメイン重複排除、スコアリング、
Shopify除外、MailForge非同期インポートを一貫管理。
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.pipeline import PipelineRun, PipelineResult
from .config import EC_PRIORITY, PROPOSAL_MAP, DEFAULT_PROPOSAL
from . import (
    yahoo_collector, rakuten_collector, google_collector,
    duckduckgo_collector, category_collector,
)
from .site_analyzer import (
    analyze_and_extract_email, detect_issues, build_personalized_proposal,
)

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
    """メールアドレス + eTLD+1ドメイン正規化で重複排除"""
    from .domain_util import normalize_domain

    seen_emails: set[str] = set()
    seen_domains: dict[str, int] = {}  # normalized domain → index in result
    result: list = []

    for lead in leads:
        email_lower = lead.email.lower()
        if email_lower in seen_emails:
            continue
        seen_emails.add(email_lower)

        # eTLD+1正規化でドメインを決定（website > email）
        website_domain = normalize_domain(getattr(lead, "website", "") or "")
        email_domain_raw = email_lower.split("@", 1)[1] if "@" in email_lower else ""
        email_domain = normalize_domain("http://" + email_domain_raw) if email_domain_raw else ""
        domain = website_domain or email_domain

        if domain and domain in seen_domains:
            existing_idx = seen_domains[domain]
            existing = result[existing_idx]
            if len(lead.company or "") > len(existing.company or ""):
                result[existing_idx] = lead  # 情報量で上書き
            continue

        if domain:
            seen_domains[domain] = len(result)
        result.append(lead)

    removed = len(leads) - len(result)
    if removed > 0:
        log.info(f"重複排除: {removed}件削除 ({len(leads)} → {len(result)})")
    return result


def _filter_cross_table_duplicates(leads: list, db: Session) -> list:
    """sales.db leads と pipeline_results を横断し、同じ正規化ドメインを持つリードを除外。

    単発検索(`/`) と バッチ収集(`/pipeline`) で同じ企業が重複登録されるのを防ぐ。
    """
    from .domain_util import normalize_domain, domain_exists_anywhere

    if not leads:
        return leads

    survivors: list = []
    skipped = 0
    for lead in leads:
        domain = normalize_domain(getattr(lead, "website", "") or "")
        if domain and domain_exists_anywhere(domain, db):
            skipped += 1
            continue
        survivors.append(lead)

    if skipped:
        log.info(f"クロステーブル重複: {skipped}件削除 ({len(leads)} → {len(survivors)})")
    return survivors


async def _enrich_with_proposals(leads: list[PipelineResult], db: Session) -> None:
    """各リードのサイトを分析し、提案文を生成する。

    フロー:
      1) HTMLスクレイピングで site analysis (並列)
      2) ローカル Claude Code が利用可能ならバッチで高品質提案文を生成
      3) Claude CLI不在の環境(Render等)では site_analyzer のテンプレートにフォールバック
    """
    import httpx
    from dataclasses import asdict
    from app.services import local_claude, proposal_service

    # category モード以外でも website があれば再生成対象に含める
    cat_leads = [l for l in leads if l.website]
    if not cat_leads:
        return

    log.info(f"サイト分析開始: {len(cat_leads)}件")
    sem = asyncio.Semaphore(10)
    ua = "Mozilla/5.0 (compatible; TSURATSURA-ResearchBot/3.1; +https://tsuratsura.co.jp/bot)"

    analyzed_pairs: list[tuple[PipelineResult, Any]] = []

    async def _analyze(lead: PipelineResult, client: httpx.AsyncClient):
        async with sem:
            try:
                analysis, _email = await analyze_and_extract_email(lead.website, client, ua)
                analysis.issues = detect_issues(analysis, lead.category or "B")
                lead.site_analysis = json.dumps(asdict(analysis), ensure_ascii=False, default=str)
                return lead, analysis
            except Exception as e:
                log.debug(f"サイト分析エラー {lead.website}: {e}")
                return lead, None

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            results = await asyncio.gather(
                *[_analyze(l, client) for l in cat_leads],
                return_exceptions=True,
            )
        for r in results:
            if isinstance(r, Exception):
                continue
            lead, analysis = r
            if analysis is not None:
                analyzed_pairs.append((lead, analysis))
        db.commit()
    except Exception as e:
        log.error(f"サイト分析バッチエラー: {e}")
        return

    if not analyzed_pairs:
        return

    use_local_claude = local_claude.is_available()
    engine = "local_claude" if use_local_claude else "template"
    log.info(f"提案文生成: {len(analyzed_pairs)}件 engine={engine}")

    if use_local_claude:
        from dataclasses import asdict as _asdict
        targets = [
            {
                "url": lead.website,
                "company": lead.company or "",
                "industry": lead.industry or "",
                "category": lead.category or "B",
                "prefecture": lead.location or "",
                "analysis": _asdict(analysis),
            }
            for lead, analysis in analyzed_pairs
        ]
        try:
            proposals = await proposal_service.generate_batch_proposals(targets)
        except Exception as e:
            log.error(f"Claude CLI バッチ生成エラー: {e}")
            proposals = [{"subject": "", "body": ""}] * len(analyzed_pairs)

        for (lead, _analysis), prop in zip(analyzed_pairs, proposals):
            if prop.get("subject") and prop.get("body"):
                lead.personalized_subject = prop["subject"]
                lead.personalized_body = prop["body"]
    else:
        # Render 等 CLI不在環境: テンプレート版でフォールバック
        for lead, analysis in analyzed_pairs:
            try:
                proposal = build_personalized_proposal(
                    company=lead.company or "",
                    industry=lead.industry or "",
                    category=lead.category or "B",
                    prefecture=lead.location or "",
                    analysis=analysis,
                )
                lead.personalized_subject = proposal["subject"]
                lead.personalized_body = proposal["body"]
            except Exception as e:
                log.debug(f"テンプレ提案文エラー {lead.website}: {e}")

    try:
        db.commit()
    except Exception as e:
        log.error(f"提案文DB保存エラー: {e}")


async def _import_to_mailforge(leads: list[PipelineResult], db: Session) -> int:
    """ランクA以上のリードをMailForgeに非同期インポート"""
    try:
        from app.services.mailforge_client import upsert_contacts
    except ImportError:
        log.warning("mailforge_client インポート不可、スキップ")
        return 0

    # 対象: rank S/A 又は カテゴリ分類済み（confidence >= 0.4）
    a_plus_leads = [
        l for l in leads
        if l.rank in ("S", "A") or (l.category and (l.confidence or 0) >= 0.4)
    ]
    if not a_plus_leads:
        return 0

    contacts = []
    for lead in a_plus_leads:
        cf = {
            "category": lead.category or "",
            "ec_status": lead.ec_status or "",
            "platform": lead.platform or "",
        }
        if lead.personalized_subject:
            cf["proposal_subject"] = lead.personalized_subject
        if lead.personalized_body:
            cf["proposal_body"] = lead.personalized_body

        notes_parts = []
        if lead.category:
            notes_parts.append(f"[{lead.category}]")
        if lead.ec_status:
            notes_parts.append(lead.ec_status)
        if lead.platform:
            notes_parts.append(lead.platform)

        contacts.append({
            "email": lead.email,
            "company_name": lead.company or "",
            "industry": lead.industry or "",
            "website_url": lead.website or "",
            "notes": " | ".join(notes_parts) or lead.proposal or "",
            "custom_fields": cf,
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
        mode = getattr(run, "mode", None) or "ec"
        try:
            cat_config = json.loads(run.category_config) if getattr(run, "category_config", None) else {}
        except Exception:
            cat_config = {}
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

        all_leads = []

        def update_progress(pct: int, msg: str):
            run.progress_pct = pct
            run.progress_message = msg
            try:
                db.commit()
            except Exception:
                pass

        # コレクターを直列実行（seen_emailsの共有安全性 + 進捗更新）
        source_count = len([s for s in ["yahoo", "rakuten", "google", "duckduckgo"] if s in sources])
        pct_per_source = 80 // max(source_count, 1)
        current_pct = 5

        if "yahoo" in sources:
            update_progress(current_pct, "Yahoo!ショッピング収集中...")
            try:
                yahoo_kw = [(k, i) for k, i in keyword_list]
                yahoo_leads = await yahoo_collector.collect(seen_emails, keywords=yahoo_kw)
                all_leads.extend(yahoo_leads)
                source_breakdown["yahoo"] = len(yahoo_leads)
                log.info(f"Yahoo! 完了: {len(yahoo_leads)}件")
            except Exception as e:
                log.error(f"Yahoo! コレクターエラー: {e}")
                source_breakdown["yahoo"] = 0
            current_pct += pct_per_source

        if "rakuten" in sources:
            update_progress(current_pct, "楽天市場収集中...")
            try:
                rakuten_kw = [(k, i) for k, i in keyword_list]
                rakuten_leads = await rakuten_collector.collect(seen_emails, keywords=rakuten_kw)
                all_leads.extend(rakuten_leads)
                source_breakdown["rakuten"] = len(rakuten_leads)
                log.info(f"楽天 完了: {len(rakuten_leads)}件")
            except Exception as e:
                log.error(f"楽天 コレクターエラー: {e}")
                source_breakdown["rakuten"] = 0
            current_pct += pct_per_source

        if "google" in sources:
            update_progress(current_pct, "Google検索収集中...")
            try:
                google_leads = await google_collector.collect(seen_emails)
                all_leads.extend(google_leads)
                source_breakdown["google"] = len(google_leads)
                log.info(f"Google 完了: {len(google_leads)}件")
            except Exception as e:
                log.error(f"Google コレクターエラー: {e}")
                source_breakdown["google"] = 0
            current_pct += pct_per_source

        if "duckduckgo" in sources:
            update_progress(current_pct, "DuckDuckGo収集中（無料）...")
            try:
                ddg_kw = [(k, i) for k, i in keyword_list]
                ddg_leads = await duckduckgo_collector.collect(seen_emails, keywords=ddg_kw)
                all_leads.extend(ddg_leads)
                source_breakdown["duckduckgo"] = len(ddg_leads)
                log.info(f"DuckDuckGo 完了: {len(ddg_leads)}件")
            except Exception as e:
                log.error(f"DuckDuckGo コレクターエラー: {e}")
                source_breakdown["duckduckgo"] = 0
            current_pct += pct_per_source

        # === カテゴリモード（全国×業種A/B/C/D） ===
        if mode in ("category", "both") and "category" in sources:
            categories = cat_config.get("categories", ["A", "B", "C", "D"])
            prefs = cat_config.get("prefectures", None)
            max_q = cat_config.get("max_queries_per_category", 50)
            max_u = cat_config.get("max_urls_per_category", 150)
            for cat in categories:
                update_progress(current_pct, f"カテゴリ{cat} 収集中（全国）...")
                try:
                    cat_leads = await category_collector.collect(
                        seen_emails,
                        category=cat,
                        prefectures=prefs,
                        max_queries=max_q,
                        max_urls=max_u,
                    )
                    all_leads.extend(cat_leads)
                    source_breakdown[f"category_{cat}"] = len(cat_leads)
                    log.info(f"カテゴリ{cat} 完了: {len(cat_leads)}件")
                except Exception as e:
                    log.error(f"カテゴリ{cat} エラー: {e}")
                    source_breakdown[f"category_{cat}"] = 0

        # Shopify構築済みを除外
        before_shopify = len(all_leads)
        all_leads = [l for l in all_leads if l.ec_status not in SHOPIFY_INDICATORS]
        shopify_excluded = before_shopify - len(all_leads)
        if shopify_excluded > 0:
            log.info(f"Shopify構築済み除外: {shopify_excluded}件")

        # ドメインレベル重複排除 + sales.db leads とのクロステーブル照合
        run.progress_pct = 85
        run.progress_message = "スコアリング中..."
        db.commit()
        all_leads = _deduplicate(all_leads)
        all_leads = _filter_cross_table_duplicates(all_leads, db)

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
                category=getattr(lead, "category", None),
                confidence=getattr(lead, "confidence", None),
            )
            db.add(result)
            pipeline_results.append(result)

        db.commit()

        # ローカル個別提案文生成（categoryモードで収集したリードに対して）
        if cat_config.get("generate_proposals", True) and mode in ("category", "both"):
            update_progress(88, "個別提案文生成中...")
            await _enrich_with_proposals(pipeline_results, db)

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

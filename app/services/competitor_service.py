import asyncio
import json
import logging
from urllib.parse import urlparse
import httpx
from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.models.competitor import CompetitorAnalysis
from app.services.serpapi_service import fetch_one_page
from app.services.checks.https_check import check_https
from app.services.checks.html_check import check_html
from app.services.checks.pagespeed_check import check_pagespeed
from app.services.checks.seo_check import check_seo
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# 比較対象の機能一覧
COMPARISON_FEATURES = [
    ("https", "is_https", "HTTPS対応"),
    ("mobile", "has_viewport", "スマートフォン対応"),
    ("og_image", "has_og_image", "OGP画像"),
    ("favicon", "has_favicon", "ファビコン"),
    ("sitemap", "has_sitemap", "sitemap.xml"),
    ("structured_data", "has_structured_data", "構造化データ"),
    ("robots_txt", "has_robots_txt", "robots.txt"),
]


async def run_competitor_analysis(lead_id: int, db: Session) -> CompetitorAnalysis:
    """競合検索→分析→比較→保存のメイン処理"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError("リードが見つかりません")

    # 検索ジョブからindustry/regionを取得
    job = lead.search_job
    industry = job.industry or ""
    region = job.region or ""

    # 検索クエリ構築
    query = _build_competitor_query(lead, industry, region)

    # CompetitorAnalysis レコード作成
    analysis = CompetitorAnalysis(
        lead_id=lead_id,
        search_query=query,
        status="analyzing",
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    try:
        # SerpAPIで競合サイトを検索
        results, has_next = await fetch_one_page(query)
        analysis.serpapi_calls_used = 1

        # ターゲットと同じドメインを除外
        target_domain = urlparse(lead.url).hostname or ""
        competitor_urls = []
        for r in results:
            comp_domain = urlparse(r["url"]).hostname or ""
            if comp_domain != target_domain:
                competitor_urls.append(r)
            if len(competitor_urls) >= 5:
                break

        if not competitor_urls:
            analysis.status = "completed"
            analysis.competitor_count = 0
            analysis.comparison_summary = json.dumps(
                {"competitor_count": 0, "message": "競合サイトが見つかりませんでした"},
                ensure_ascii=False,
            )
            db.commit()
            return analysis

        # 各競合サイトを並列分析
        tasks = [_analyze_competitor(c["url"]) for c in competitor_urls]
        competitor_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 有効な分析結果のみ抽出
        valid_competitors = []
        for i, result in enumerate(competitor_results):
            if isinstance(result, dict):
                result["url"] = competitor_urls[i]["url"]
                result["title"] = competitor_urls[i].get("title", "")
                valid_competitors.append(result)

        # 比較データ生成
        comparison = _build_comparison(lead, valid_competitors)

        analysis.competitor_count = len(valid_competitors)
        analysis.competitor_data = json.dumps(valid_competitors, ensure_ascii=False)
        analysis.comparison_summary = json.dumps(comparison, ensure_ascii=False)
        analysis.status = "completed"
        db.commit()

        logger.info(f"競合分析完了: lead={lead_id} competitors={len(valid_competitors)}")
        return analysis

    except Exception as e:
        analysis.status = "error"
        analysis.error_message = str(e)[:500]
        db.commit()
        raise


def _build_competitor_query(lead: Lead, industry: str, region: str) -> str:
    """リード情報から競合検索クエリを構築"""
    parts = []
    if industry:
        parts.append(industry)
    if region:
        parts.append(region)

    # industry/regionがない場合、検索ジョブのクエリをそのまま使う
    if not parts:
        parts.append(lead.search_job.query)

    return " ".join(parts)


async def _analyze_competitor(url: str) -> dict:
    """1サイトを軽量分析する（スクリーンショット・連絡先抽出は省略）"""
    analysis = {}

    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SalesBot/1.0)"},
            follow_redirects=True,
        ) as client:
            results = await asyncio.wait_for(
                asyncio.gather(
                    check_https(url, client),
                    check_html(url, client),
                    check_pagespeed(url),
                    check_seo(url, client),
                    return_exceptions=True,
                ),
                timeout=20,
            )

        for r in results:
            if isinstance(r, dict):
                analysis.update(r)

    except Exception as e:
        logger.warning(f"競合分析エラー ({url}): {e}")

    return analysis


def _build_comparison(target_lead: Lead, competitors: list[dict]) -> dict:
    """ターゲット vs 競合平均の比較データを生成"""
    if not competitors:
        return {"competitor_count": 0, "features": {}, "gap_count": 0}

    comp_count = len(competitors)
    features = {}
    gaps = []
    advantages = []

    # 各機能の対応率を計算
    for key, field, label in COMPARISON_FEATURES:
        target_val = getattr(target_lead, field, None)
        target_has = bool(target_val) if target_val is not None else False

        comp_has_count = sum(
            1 for c in competitors
            if c.get(field) is True
        )
        comp_rate = round(comp_has_count / comp_count * 100)

        is_gap = (not target_has) and comp_rate >= 50
        is_advantage = target_has and comp_rate < 50

        features[key] = {
            "label": label,
            "target": target_has,
            "competitors_rate": comp_rate,
            "gap": is_gap,
        }

        if is_gap:
            gaps.append(label)
        if is_advantage:
            advantages.append(label)

    # PageSpeed比較
    target_ps = target_lead.pagespeed_score
    comp_ps_scores = [
        c.get("pagespeed_score")
        for c in competitors
        if c.get("pagespeed_score") is not None
    ]
    if comp_ps_scores:
        avg_ps = round(sum(comp_ps_scores) / len(comp_ps_scores))
        ps_gap = (target_ps is not None and target_ps < avg_ps - 10)
        features["pagespeed"] = {
            "label": "表示速度スコア",
            "target": target_ps,
            "competitors_avg": avg_ps,
            "gap": ps_gap,
        }
        if ps_gap:
            gaps.append(f"表示速度（御社{target_ps}点 vs 競合平均{avg_ps}点）")

    # 競合サイト一覧（概要のみ）
    comp_summaries = []
    for c in competitors:
        comp_summaries.append({
            "url": c.get("url", ""),
            "title": c.get("title", ""),
            "is_https": c.get("is_https"),
            "has_viewport": c.get("has_viewport"),
            "pagespeed_score": c.get("pagespeed_score"),
            "has_sitemap": c.get("has_sitemap"),
        })

    return {
        "competitor_count": comp_count,
        "features": features,
        "gap_count": len(gaps),
        "gaps": gaps,
        "target_advantages": advantages,
        "competitors": comp_summaries,
    }

import asyncio
import json
from urllib.parse import urlparse
import httpx
from sqlalchemy.orm import Session

from app.models.lead import Lead
from app.services.checks.https_check import check_https
from app.services.checks.domain_check import check_domain
from app.services.checks.html_check import check_html
from app.services.checks.pagespeed_check import check_pagespeed
from app.services.checks.seo_check import check_seo
from app.services.checks.form_check import check_form
from app.services.checks.company_check import check_company
from app.services.contact_extractor import extract_contact
from app.services.scorer import calculate_score, calculate_conversion_rank
from app.services.screenshot_service import capture_screenshots
from app.config import get_settings

settings = get_settings()


async def analyze_lead(lead_id: int, db: Session) -> None:
    """1件のリードを全チェックモジュールで並列分析し、DBに保存する"""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return

    lead.status = "analyzing"
    db.commit()

    url = lead.url
    analysis = {}

    try:
        async with httpx.AsyncClient(
            timeout=settings.ANALYSIS_TIMEOUT_SEC,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SalesBot/1.0)"},
            follow_redirects=True,
        ) as client:
            # 全チェックを並列実行（全体タイムアウト付き）
            results = await asyncio.wait_for(
                asyncio.gather(
                    check_https(url, client),
                    check_domain(url),
                    check_html(url, client),
                    check_pagespeed(url),
                    check_seo(url, client),
                    extract_contact(url, client),
                    check_form(url, client),
                    check_company(url, client),
                    return_exceptions=True,
                ),
                timeout=settings.ANALYSIS_TIMEOUT_SEC + 5,
            )

        for r in results:
            if isinstance(r, dict):
                analysis.update(r)

        # スコア計算
        score, breakdown = calculate_score(analysis)

        # ドメイン名取得
        parsed = urlparse(url)
        domain = parsed.hostname or ""

        # DBに保存
        lead.domain = domain
        lead.is_https = analysis.get("is_https")
        lead.ssl_expiry_days = analysis.get("ssl_expiry_days")
        lead.domain_age_years = analysis.get("domain_age_years")
        lead.copyright_year = analysis.get("copyright_year")
        lead.has_viewport = analysis.get("has_viewport")
        lead.has_flash = analysis.get("has_flash")
        lead.cms_type = analysis.get("cms_type")
        lead.cms_version = analysis.get("cms_version")
        lead.pagespeed_score = analysis.get("pagespeed_score")
        lead.contact_email = analysis.get("contact_email")
        lead.contact_page_url = analysis.get("contact_page_url")
        # Phase 1 追加: デザイン系
        lead.has_og_image = analysis.get("has_og_image")
        lead.has_favicon = analysis.get("has_favicon")
        lead.has_table_layout = analysis.get("has_table_layout")
        lead.missing_alt_count = analysis.get("missing_alt_count")
        # Phase 1 追加: EC系
        lead.is_ec_site = analysis.get("is_ec_site")
        lead.ec_platform = analysis.get("ec_platform")
        lead.has_site_search = analysis.get("has_site_search")
        lead.has_product_schema = analysis.get("has_product_schema")
        # Phase 1 追加: SEO系
        lead.has_structured_data = analysis.get("has_structured_data")
        lead.has_breadcrumb = analysis.get("has_breadcrumb")
        lead.has_sitemap = analysis.get("has_sitemap")
        lead.has_robots_txt = analysis.get("has_robots_txt")
        # Phase 5: スマートスコアリング
        lead.has_contact_form = analysis.get("has_contact_form")
        lead.form_field_count = analysis.get("form_field_count")
        lead.has_file_upload = analysis.get("has_file_upload")
        lead.estimated_page_count = analysis.get("estimated_page_count")
        lead.company_size_estimate = analysis.get("company_size_estimate")
        lead.industry_category = analysis.get("industry_category")
        lead.score = score
        lead.score_breakdown = json.dumps(breakdown, ensure_ascii=False)
        # 成約期待度ランク算出
        rank_data = {
            "score": score,
            "company_size_estimate": analysis.get("company_size_estimate"),
            "has_contact_form": analysis.get("has_contact_form"),
            "contact_email": analysis.get("contact_email"),
            "industry_category": analysis.get("industry_category"),
        }
        lead.conversion_rank = calculate_conversion_rank(rank_data)
        lead.status = "analyzed"

        # Phase 2: スクリーンショット取得（分析完了後、非ブロッキング）
        try:
            await asyncio.wait_for(
                capture_screenshots(lead_id, url),
                timeout=30,
            )
        except Exception:
            pass  # スクリーンショット失敗は分析結果に影響しない

    except Exception as e:
        lead.status = "error"
        lead.analysis_error = str(e)[:500]

    db.commit()

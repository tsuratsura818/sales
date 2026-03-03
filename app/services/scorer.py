from datetime import datetime

# WordPress メジャーバージョンのリリース日マッピング
WP_VERSION_DATES = {
    "6.7": "2024-11-12",
    "6.6": "2024-07-16",
    "6.5": "2024-04-02",
    "6.4": "2023-11-07",
    "6.3": "2023-08-08",
    "6.2": "2023-03-29",
    "6.1": "2022-11-01",
    "6.0": "2022-05-24",
    "5.9": "2022-01-25",
    "5.8": "2021-07-20",
    "5.7": "2021-03-09",
    "5.6": "2020-12-08",
    "5.5": "2020-08-11",
    "5.4": "2020-03-31",
    "5.3": "2019-11-12",
    "5.2": "2019-05-07",
    "5.1": "2019-02-21",
    "5.0": "2018-12-06",
    "4.9": "2017-11-15",
    "4.8": "2017-06-08",
    "4.7": "2016-12-06",
    "4.6": "2016-08-16",
    "4.5": "2016-04-12",
    "4.4": "2015-12-08",
    "4.3": "2015-08-18",
    "4.2": "2015-04-23",
    "4.1": "2014-12-18",
    "4.0": "2014-09-04",
    "3.9": "2014-04-16",
}


def _wp_version_age_days(version: str) -> int | None:
    """WordPressバージョンからリリースからの経過日数を返す。不明なら None。"""
    if not version:
        return None
    # "6.4.1" → "6.4" にマッピング
    parts = version.split(".")
    major_minor = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
    release_str = WP_VERSION_DATES.get(major_minor)
    if not release_str:
        # マッチしない場合、メジャーバージョンだけで試す
        release_str = WP_VERSION_DATES.get(parts[0] + ".0")
    if not release_str:
        return None
    release_date = datetime.strptime(release_str, "%Y-%m-%d")
    return (datetime.now() - release_date).days


SCORE_WEIGHTS = {
    # 既存項目
    "no_https": 30,
    "old_copyright_3yr": 25,
    "no_mobile": 20,
    "old_domain_10yr": 15,
    "has_flash": 15,
    "ssl_expiry_90days": 10,
    "low_pagespeed": 10,
    "old_wordpress": 15,
    # Phase 1 追加: デザイン系
    "no_og_image": 10,
    "no_favicon": 10,
    "table_layout": 15,
    "many_missing_alt": 10,
    # Phase 1 追加: EC系
    "ec_no_product_schema": 10,
    "ec_no_site_search": 5,
    # Phase 1 追加: SEO系
    "no_structured_data": 10,
    "no_sitemap": 10,
}


def calculate_score(analysis: dict) -> tuple[int, dict]:
    """分析結果からスコアと内訳を計算する"""
    score = 0
    breakdown = {}
    current_year = datetime.now().year

    # HTTPSなし
    if analysis.get("is_https") is False:
        breakdown["no_https"] = SCORE_WEIGHTS["no_https"]
        score += SCORE_WEIGHTS["no_https"]

    # コピーライト3年以上前
    copyright_year = analysis.get("copyright_year")
    if copyright_year and (current_year - copyright_year) >= 3:
        breakdown["old_copyright_3yr"] = SCORE_WEIGHTS["old_copyright_3yr"]
        score += SCORE_WEIGHTS["old_copyright_3yr"]

    # モバイル非対応
    if analysis.get("has_viewport") is False:
        breakdown["no_mobile"] = SCORE_WEIGHTS["no_mobile"]
        score += SCORE_WEIGHTS["no_mobile"]

    # ドメイン10年以上
    domain_age = analysis.get("domain_age_years")
    if domain_age and domain_age >= 10:
        breakdown["old_domain_10yr"] = SCORE_WEIGHTS["old_domain_10yr"]
        score += SCORE_WEIGHTS["old_domain_10yr"]

    # Flash使用
    if analysis.get("has_flash"):
        breakdown["has_flash"] = SCORE_WEIGHTS["has_flash"]
        score += SCORE_WEIGHTS["has_flash"]

    # SSL証明書90日以内に期限切れ
    ssl_days = analysis.get("ssl_expiry_days")
    if ssl_days is not None and 0 <= ssl_days <= 90:
        breakdown["ssl_expiry_90days"] = SCORE_WEIGHTS["ssl_expiry_90days"]
        score += SCORE_WEIGHTS["ssl_expiry_90days"]

    # PageSpeedスコアが50未満
    ps_score = analysis.get("pagespeed_score")
    if ps_score is not None and ps_score < 50:
        breakdown["low_pagespeed"] = SCORE_WEIGHTS["low_pagespeed"]
        score += SCORE_WEIGHTS["low_pagespeed"]

    # 古いWordPress（リリースから1年以上経過）
    cms_type = analysis.get("cms_type", "")
    cms_version = analysis.get("cms_version", "")
    if cms_type == "WordPress" and cms_version:
        age_days = _wp_version_age_days(cms_version)
        if age_days is not None and age_days > 365:
            breakdown["old_wordpress"] = SCORE_WEIGHTS["old_wordpress"]
            breakdown["wp_version_age_days"] = age_days
            score += SCORE_WEIGHTS["old_wordpress"]

    # --- Phase 1 追加: デザイン系 ---

    # OGP画像なし
    if analysis.get("has_og_image") is False:
        breakdown["no_og_image"] = SCORE_WEIGHTS["no_og_image"]
        score += SCORE_WEIGHTS["no_og_image"]

    # ファビコンなし
    if analysis.get("has_favicon") is False:
        breakdown["no_favicon"] = SCORE_WEIGHTS["no_favicon"]
        score += SCORE_WEIGHTS["no_favicon"]

    # テーブルレイアウト（古いHTML構造）
    if analysis.get("has_table_layout"):
        breakdown["table_layout"] = SCORE_WEIGHTS["table_layout"]
        score += SCORE_WEIGHTS["table_layout"]

    # alt属性欠落が5個以上
    missing_alt = analysis.get("missing_alt_count")
    if missing_alt is not None and missing_alt >= 5:
        breakdown["many_missing_alt"] = SCORE_WEIGHTS["many_missing_alt"]
        score += SCORE_WEIGHTS["many_missing_alt"]

    # --- Phase 1 追加: EC系 ---

    # ECサイトなのに商品構造化データなし
    if analysis.get("is_ec_site") and analysis.get("has_product_schema") is False:
        breakdown["ec_no_product_schema"] = SCORE_WEIGHTS["ec_no_product_schema"]
        score += SCORE_WEIGHTS["ec_no_product_schema"]

    # ECサイトなのにサイト内検索なし
    if analysis.get("is_ec_site") and analysis.get("has_site_search") is False:
        breakdown["ec_no_site_search"] = SCORE_WEIGHTS["ec_no_site_search"]
        score += SCORE_WEIGHTS["ec_no_site_search"]

    # --- Phase 1 追加: SEO系 ---

    # 構造化データなし
    if analysis.get("has_structured_data") is False:
        breakdown["no_structured_data"] = SCORE_WEIGHTS["no_structured_data"]
        score += SCORE_WEIGHTS["no_structured_data"]

    # サイトマップなし
    if analysis.get("has_sitemap") is False:
        breakdown["no_sitemap"] = SCORE_WEIGHTS["no_sitemap"]
        score += SCORE_WEIGHTS["no_sitemap"]

    return score, breakdown


# --- Phase 5: 成約期待度ランク ---

# Web依存度の高い業種（営業が刺さりやすい）
HIGH_WEB_DEPENDENCY = {"飲食", "美容", "建設/不動産", "小売/EC", "医療/介護"}
MID_WEB_DEPENDENCY = {"サービス", "教育", "製造", "士業"}
LOW_WEB_DEPENDENCY = {"IT/Web"}  # 自社で対応可能


def calculate_conversion_rank(analysis: dict) -> str:
    """成約期待度ランク（S/A/B/C）を算出する"""
    conv_score = 0

    # 技術的負債（max 40点）: score高い → 改善余地大 → 成約しやすい
    tech_score = analysis.get("score", 0)
    if tech_score >= 50:
        conv_score += 40
    elif tech_score >= 30:
        conv_score += 25
    elif tech_score >= 15:
        conv_score += 15

    # 会社規模（max 25点）: 中小企業が最もターゲット
    size = analysis.get("company_size_estimate")
    if size == "medium":
        conv_score += 25
    elif size == "small":
        conv_score += 20
    elif size == "mid_large":
        conv_score += 15
    elif size == "large":
        conv_score += 5

    # フォーム・連絡先（max 20点）
    if analysis.get("has_contact_form"):
        conv_score += 10
    if analysis.get("contact_email"):
        conv_score += 10

    # 業種（max 15点）
    industry = analysis.get("industry_category", "その他")
    if industry in HIGH_WEB_DEPENDENCY:
        conv_score += 15
    elif industry in MID_WEB_DEPENDENCY:
        conv_score += 10
    elif industry in LOW_WEB_DEPENDENCY:
        conv_score += 0
    else:
        conv_score += 5  # その他

    # ランク判定
    if conv_score >= 80:
        return "S"
    elif conv_score >= 60:
        return "A"
    elif conv_score >= 40:
        return "B"
    else:
        return "C"

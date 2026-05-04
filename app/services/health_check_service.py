"""クライアントサイトの月次健康診断サービス

既存の checks/ サービスを組み合わせて、クライアント1社の SSL/PageSpeed/フォーム生存
/CMS Version をチェックし、問題を検出する。
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models.client_site import ClientSite, HealthCheckResult
from app.services.checks.https_check import check_https
from app.services.checks.pagespeed_check import check_pagespeed
from app.services.checks.form_check import check_form
from app.services.checks.html_check import check_html

logger = logging.getLogger(__name__)


# 検出ルール: 値 → "warning" or "critical" 判定
CRITICAL_RULES = {
    "ssl_days_left_lt": 14,        # SSL期限14日未満は critical
    "pagespeed_mobile_lt": 30,      # モバイル30未満は critical
    "form_missing": True,           # フォーム消失は critical
    "https_missing": True,          # HTTPS化されていない=critical
}
WARNING_RULES = {
    "ssl_days_left_lt": 45,         # SSL期限45日未満は warning
    "pagespeed_mobile_lt": 50,      # モバイル50未満は warning
}


async def run_health_check(client_site: ClientSite) -> dict[str, Any]:
    """1サイトの健康診断を実行。検出した問題と数値を返す"""
    url = client_site.url
    issues: list[dict] = []
    result: dict[str, Any] = {
        "ssl_days_left": None,
        "pagespeed_mobile": None,
        "pagespeed_desktop": None,
        "has_form": None,
        "cms": None,
        "cms_version": None,
        "is_https": None,
    }

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # 1. HTTPS / SSL
        try:
            https_data = await check_https(url, client)
            result["is_https"] = https_data.get("is_https")
            result["ssl_days_left"] = https_data.get("ssl_days_left")

            if not result["is_https"]:
                issues.append({"level": "critical", "key": "https", "msg": "HTTPS化されていません"})
            elif result["ssl_days_left"] is not None:
                if result["ssl_days_left"] < CRITICAL_RULES["ssl_days_left_lt"]:
                    issues.append({"level": "critical", "key": "ssl",
                                   "msg": f"SSL証明書が{result['ssl_days_left']}日後に失効します"})
                elif result["ssl_days_left"] < WARNING_RULES["ssl_days_left_lt"]:
                    issues.append({"level": "warning", "key": "ssl",
                                   "msg": f"SSL証明書が{result['ssl_days_left']}日後に失効します"})
        except Exception as e:
            logger.warning(f"https check error ({url}): {e}")

        # 2. フォーム生存確認
        try:
            form_data = await check_form(url, client)
            result["has_form"] = form_data.get("has_contact_form")
            if result["has_form"] is False:
                issues.append({"level": "warning", "key": "form",
                               "msg": "問い合わせフォームが見つかりません"})
        except Exception as e:
            logger.warning(f"form check error ({url}): {e}")

        # 3. CMS 検出
        try:
            html_data = await check_html(url, client)
            result["cms"] = html_data.get("ec_platform") or html_data.get("cms")
            result["cms_version"] = html_data.get("cms_version")
        except Exception as e:
            logger.warning(f"html check error ({url}): {e}")

    # 4. PageSpeed (別接続)
    try:
        ps_data = await check_pagespeed(url)
        result["pagespeed_mobile"] = ps_data.get("mobile_score")
        result["pagespeed_desktop"] = ps_data.get("desktop_score")
        if result["pagespeed_mobile"] is not None:
            if result["pagespeed_mobile"] < CRITICAL_RULES["pagespeed_mobile_lt"]:
                issues.append({"level": "critical", "key": "pagespeed",
                               "msg": f"モバイル PageSpeed が {result['pagespeed_mobile']}/100 と低スコアです"})
            elif result["pagespeed_mobile"] < WARNING_RULES["pagespeed_mobile_lt"]:
                issues.append({"level": "warning", "key": "pagespeed",
                               "msg": f"モバイル PageSpeed が {result['pagespeed_mobile']}/100 です"})
    except Exception as e:
        logger.warning(f"pagespeed check error ({url}): {e}")

    # 全体ステータス
    levels = {i["level"] for i in issues}
    if "critical" in levels:
        result["status"] = "critical"
    elif "warning" in levels:
        result["status"] = "warning"
    else:
        result["status"] = "ok"

    result["issues"] = issues
    return result


async def check_and_save(client_site: ClientSite, db: Session) -> HealthCheckResult:
    """1サイトをチェックしてDBに結果を保存"""
    result = await run_health_check(client_site)

    record = HealthCheckResult(
        client_site_id=client_site.id,
        status=result["status"],
        ssl_days_left=result.get("ssl_days_left"),
        pagespeed_mobile=result.get("pagespeed_mobile"),
        pagespeed_desktop=result.get("pagespeed_desktop"),
        has_form=result.get("has_form"),
        cms=result.get("cms"),
        cms_version=result.get("cms_version"),
        is_https=result.get("is_https"),
        issues_json=json.dumps(result.get("issues", []), ensure_ascii=False),
    )
    db.add(record)

    # ClientSite側の最終更新
    client_site.last_checked_at = datetime.now()
    client_site.last_status = result["status"]
    db.commit()
    db.refresh(record)
    return record


def format_alert_message(client: ClientSite, record: HealthCheckResult) -> str:
    """LINE通知用の問題サマリー文字列"""
    issues = []
    if record.issues_json:
        try:
            issues = json.loads(record.issues_json)
        except Exception:
            pass

    icon = "🚨" if record.status == "critical" else "⚠️"
    lines = [f"{icon} 健康診断アラート: {client.name}", f"URL: {client.url}", ""]
    for i in issues:
        emoji = "🔴" if i["level"] == "critical" else "🟡"
        lines.append(f"{emoji} {i['msg']}")
    if record.pagespeed_mobile is not None:
        lines.append(f"\n📱 PageSpeed: モバイル {record.pagespeed_mobile} / デスクトップ {record.pagespeed_desktop or '?'}")
    if record.ssl_days_left is not None:
        lines.append(f"🔒 SSL残: {record.ssl_days_left}日")
    return "\n".join(lines)

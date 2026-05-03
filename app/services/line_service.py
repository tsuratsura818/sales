import hashlib
import hmac
import base64
import logging
from typing import Optional

import httpx
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def verify_signature(body: bytes, signature: str) -> bool:
    """LINE Webhook署名をHMAC-SHA256で検証"""
    hash_value = hmac.new(
        settings.LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(expected, signature)


async def push_job_flex_message(
    job_id: int,
    title: str,
    platform: str,
    budget_text: str,
    deadline_text: str,
    match_score: int,
    match_reason: str,
    job_url: str,
) -> Optional[str]:
    """案件カードをFlex Messageで送信。応募/スキップ/詳細ボタン付き"""
    platform_color = "#F16722" if platform == "crowdworks" else "#0CBBF0"
    platform_label = "CrowdWorks" if platform == "crowdworks" else "Lancers"

    if match_score >= 80:
        score_color = "#27ae60"
    elif match_score >= 60:
        score_color = "#f39c12"
    else:
        score_color = "#e74c3c"

    flex_message = {
        "type": "flex",
        "altText": f"[{platform_label}] {title}",
        "contents": {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": platform_color,
                "paddingAll": "15px",
                "contents": [
                    {
                        "type": "text",
                        "text": platform_label,
                        "color": "#ffffff",
                        "size": "xs",
                        "weight": "bold",
                    },
                    {
                        "type": "text",
                        "text": title,
                        "color": "#ffffff",
                        "size": "md",
                        "weight": "bold",
                        "wrap": True,
                        "maxLines": 3,
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "15px",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "予算", "size": "sm",
                             "color": "#888888", "flex": 2},
                            {"type": "text", "text": budget_text, "size": "sm",
                             "weight": "bold", "flex": 5},
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "期限", "size": "sm",
                             "color": "#888888", "flex": 2},
                            {"type": "text", "text": deadline_text, "size": "sm",
                             "flex": 5},
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "マッチ度", "size": "sm",
                             "color": "#888888", "flex": 2},
                            {
                                "type": "text",
                                "text": f"{match_score}点",
                                "size": "sm",
                                "weight": "bold",
                                "color": score_color,
                                "flex": 5,
                            },
                        ],
                    },
                    {"type": "separator"},
                    {
                        "type": "text",
                        "text": match_reason,
                        "size": "xs",
                        "color": "#666666",
                        "wrap": True,
                        "maxLines": 4,
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "paddingAll": "15px",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "応募する",
                            "data": f"action=apply&job_id={job_id}",
                            "displayText": "応募します！",
                        },
                        "style": "primary",
                        "color": "#27ae60",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "スキップ",
                            "data": f"action=skip&job_id={job_id}",
                            "displayText": "スキップします",
                        },
                        "style": "secondary",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "詳細",
                            "uri": job_url,
                        },
                        "style": "secondary",
                    },
                ],
            },
        },
    }

    payload = {
        "to": settings.LINE_USER_ID,
        "messages": [flex_message],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            msg_id = data.get("sentMessages", [{}])[0].get("id")
            logger.info(f"LINE push成功: job_id={job_id}")
            return msg_id
        else:
            logger.error(f"LINE push失敗: {resp.status_code} {resp.text}")
            return None


async def push_proposal_review(
    job_id: int,
    title: str,
    proposal_text: str,
) -> None:
    """提案文をLINEに送信し、送信/再生成ボタンを表示"""
    # 提案文（LINEメッセージ上限5000文字に収める）
    truncated = proposal_text[:4500]

    messages = [
        {
            "type": "text",
            "text": f"[提案文プレビュー]\n{title}\n\n{truncated}",
        },
        {
            "type": "template",
            "altText": "提案文を確認してください",
            "template": {
                "type": "confirm",
                "text": "この内容で応募しますか？",
                "actions": [
                    {
                        "type": "postback",
                        "label": "この内容で送信",
                        "data": f"action=confirm_proposal&job_id={job_id}",
                        "displayText": "この内容で応募します",
                    },
                    {
                        "type": "postback",
                        "label": "再生成",
                        "data": f"action=regenerate&job_id={job_id}",
                        "displayText": "提案文を再生成します",
                    },
                ],
            },
        },
    ]

    payload = {"to": settings.LINE_USER_ID, "messages": messages}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"LINE proposal review push失敗: {resp.status_code} {resp.text}")


async def push_text_message(text: str) -> None:
    """テキストメッセージを送信"""
    payload = {
        "to": settings.LINE_USER_ID,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"LINE text push失敗: {resp.status_code} {resp.text}")


async def push_job_with_proposal(
    title: str,
    platform: str,
    score: int,
    reason: str,
    budget_text: str,
    job_url: str,
    proposal_text: str,
    job_id: int | None = None,
) -> None:
    """マッチ案件 + 提案文 + URL を送信。後続でアクションボタンFlexも送る"""
    text = (
        f"🎯 新着案件マッチ (スコア {score})\n\n"
        f"【{platform}】{title}\n"
        f"予算: {budget_text}\n"
        f"評価: {reason}\n\n"
        f"━━━━━━━━━━━━\n"
        f"📝 提案文（コピペ用）\n"
        f"━━━━━━━━━━━━\n\n"
        f"{proposal_text}\n\n"
        f"━━━━━━━━━━━━\n"
        f"🔗 応募URL\n{job_url}"
    )
    if len(text) > 4900:
        text = text[:4900] + "\n...(省略)"

    messages: list[dict] = [{"type": "text", "text": text}]
    if job_id is not None:
        messages.append(_action_buttons_flex(job_id, title))

    payload = {"to": settings.LINE_USER_ID, "messages": messages}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error(f"LINE push (proposal+buttons) 失敗: {resp.status_code} {resp.text}")


def _action_buttons_flex(job_id: int, title: str) -> dict:
    """応募完了/再生成/スキップ ボタンのFlexメッセージ"""
    return {
        "type": "flex",
        "altText": "案件アクション",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": title[:40], "size": "xs", "color": "#888888", "wrap": True},
                    {"type": "button", "style": "primary", "color": "#10b981", "height": "sm",
                     "action": {"type": "postback", "label": "✅ 応募完了", "data": f"action=mark_applied&job_id={job_id}",
                                "displayText": f"応募完了: {title[:20]}"}},
                    {"type": "button", "style": "secondary", "height": "sm",
                     "action": {"type": "postback", "label": "🔄 再生成", "data": f"action=regenerate_v2&job_id={job_id}",
                                "displayText": f"再生成: {title[:20]}"}},
                    {"type": "button", "style": "secondary", "height": "sm",
                     "action": {"type": "postback", "label": "⏭ スキップ", "data": f"action=mark_skipped&job_id={job_id}",
                                "displayText": f"スキップ: {title[:20]}"}},
                ],
            },
        },
    }


async def push_reply_notification(
    lead_id: int,
    lead_domain: str,
    lead_title: str,
    from_email: str,
    subject: str,
    body_preview: str,
) -> None:
    """返信検知時のFlex Message通知。返信内容サマリー + 次アクション提案"""
    # 本文プレビュー（長すぎる場合は切り詰め）
    preview = body_preview[:300] + "..." if len(body_preview) > 300 else body_preview
    title_text = lead_title or lead_domain

    flex_message = {
        "type": "flex",
        "altText": f"返信あり: {title_text}",
        "contents": {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#27ae60",
                "paddingAll": "15px",
                "contents": [
                    {
                        "type": "text",
                        "text": "返信検知",
                        "color": "#ffffff",
                        "size": "xs",
                        "weight": "bold",
                    },
                    {
                        "type": "text",
                        "text": title_text,
                        "color": "#ffffff",
                        "size": "md",
                        "weight": "bold",
                        "wrap": True,
                        "maxLines": 2,
                    },
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "15px",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "送信元", "size": "sm",
                             "color": "#888888", "flex": 2},
                            {"type": "text", "text": from_email, "size": "sm",
                             "weight": "bold", "flex": 5, "wrap": True},
                        ],
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "件名", "size": "sm",
                             "color": "#888888", "flex": 2},
                            {"type": "text", "text": subject or "(件名なし)", "size": "sm",
                             "flex": 5, "wrap": True},
                        ],
                    },
                    {"type": "separator"},
                    {
                        "type": "text",
                        "text": preview or "(本文なし)",
                        "size": "xs",
                        "color": "#666666",
                        "wrap": True,
                        "maxLines": 8,
                    },
                    {"type": "separator"},
                    {
                        "type": "text",
                        "text": "次のアクション: 24時間以内に返信しましょう",
                        "size": "xs",
                        "color": "#27ae60",
                        "weight": "bold",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "paddingAll": "15px",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "postback",
                            "label": "商談設定",
                            "data": f"action=set_meeting&lead_id={lead_id}",
                            "displayText": "商談日程を設定します",
                        },
                        "style": "primary",
                        "color": "#27ae60",
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "詳細",
                            "uri": f"{settings.RENDER_BASE_URL or 'https://sales-6g78.onrender.com'}/leads/{lead_id}",
                        },
                        "style": "secondary",
                    },
                ],
            },
        },
    }

    payload = {
        "to": settings.LINE_USER_ID,
        "messages": [flex_message],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/push",
            headers=_headers(),
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"返信通知LINE送信成功: lead_id={lead_id}")
        else:
            logger.error(f"返信通知LINE送信失敗: {resp.status_code} {resp.text}")


async def push_inbound_notification(
    lead_id: int,
    email: str,
    name: str,
    company: str,
    source: str,
    message: str,
) -> None:
    """インバウンドリード受信時のLINE通知"""
    source_labels = {
        "wordpress": "WordPress問い合わせ",
        "diagnostic": "診断ツール",
        "landing_page": "LP",
    }
    source_label = source_labels.get(source, source)
    preview = message[:200] + "..." if len(message) > 200 else message

    flex_message = {
        "type": "flex",
        "altText": f"インバウンドリード: {name or email}",
        "contents": {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#8e44ad",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": f"インバウンド ({source_label})", "color": "#ffffff", "size": "xs", "weight": "bold"},
                    {"type": "text", "text": name or email, "color": "#ffffff", "size": "md", "weight": "bold", "wrap": True},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "15px",
                "contents": [
                    {"type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "メール", "size": "sm", "color": "#888888", "flex": 2},
                        {"type": "text", "text": email, "size": "sm", "flex": 5, "wrap": True},
                    ]},
                    {"type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "会社", "size": "sm", "color": "#888888", "flex": 2},
                        {"type": "text", "text": company or "-", "size": "sm", "flex": 5},
                    ]},
                    {"type": "separator"},
                    {"type": "text", "text": preview or "(メッセージなし)", "size": "xs", "color": "#666666", "wrap": True, "maxLines": 6},
                    {"type": "separator"},
                    {"type": "text", "text": "1時間以内に返信で成約率3倍UP", "size": "xs", "color": "#8e44ad", "weight": "bold"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "md",
                "paddingAll": "15px",
                "contents": [
                    {"type": "button", "action": {"type": "uri", "label": "詳細", "uri": f"{settings.RENDER_BASE_URL or 'https://sales-6g78.onrender.com'}/inbound"}, "style": "primary", "color": "#8e44ad"},
                ],
            },
        },
    }

    payload = {"to": settings.LINE_USER_ID, "messages": [flex_message]}
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{LINE_API_BASE}/message/push", headers=_headers(), json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info(f"インバウンドLINE通知成功: lead_id={lead_id}")
        else:
            logger.error(f"インバウンドLINE通知失敗: {resp.status_code} {resp.text}")


async def push_weekly_report(report_data: dict) -> None:
    """週次レポートをLINE Flex Messageで送信"""
    d = report_data
    flex_message = {
        "type": "flex",
        "altText": f"週次レポート: {d.get('period', '')}",
        "contents": {
            "type": "bubble",
            "size": "giga",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#2c3e50",
                "paddingAll": "15px",
                "contents": [
                    {"type": "text", "text": "週次レポート", "color": "#ffffff", "size": "xs", "weight": "bold"},
                    {"type": "text", "text": d.get("period", ""), "color": "#ffffff", "size": "md", "weight": "bold"},
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "paddingAll": "15px",
                "contents": [
                    _report_row("リード", d.get("leads", 0), d.get("leads_prev", 0)),
                    _report_row("送信", d.get("sent", 0), d.get("sent_prev", 0)),
                    _report_row("返信", d.get("replies", 0), d.get("replies_prev", 0)),
                    _report_row("商談", d.get("meetings", 0), d.get("meetings_prev", 0)),
                    _report_row("成約", d.get("closed", 0), d.get("closed_prev", 0)),
                    {"type": "separator"},
                    {"type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "返信率", "size": "sm", "color": "#888888", "flex": 3},
                        {"type": "text", "text": f"{d.get('reply_rate', 0)}%", "size": "sm", "weight": "bold", "flex": 2},
                    ]},
                    {"type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "着地予測(月)", "size": "sm", "color": "#888888", "flex": 3},
                        {"type": "text", "text": f"送信{d.get('forecast_sent', '-')} / 返信{d.get('forecast_replies', '-')}", "size": "sm", "flex": 4},
                    ]},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "📥 案件取得（CW / LC）", "size": "sm", "weight": "bold", "color": "#4f46e5", "margin": "md"},
                    _report_row("CW検知", d.get("cw_detected", 0), d.get("cw_detected_prev", 0)),
                    _report_row("CW提案文生成", d.get("cw_review", 0), d.get("cw_review_prev", 0)),
                    _report_row("LC検知", d.get("lc_detected", 0), d.get("lc_detected_prev", 0)),
                    _report_row("LC提案文生成", d.get("lc_review", 0), d.get("lc_review_prev", 0)),
                    {"type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "平均スコア", "size": "sm", "color": "#888888", "flex": 3},
                        {"type": "text", "text": f"CW {d.get('cw_avg_score', 0)} / LC {d.get('lc_avg_score', 0)}", "size": "sm", "flex": 4},
                    ]},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "paddingAll": "15px",
                "contents": [
                    {"type": "button", "action": {"type": "uri", "label": "ダッシュボード", "uri": f"{settings.RENDER_BASE_URL or 'https://sales-6g78.onrender.com'}/dashboard"}, "style": "secondary"},
                ],
            },
        },
    }

    payload = {"to": settings.LINE_USER_ID, "messages": [flex_message]}
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{LINE_API_BASE}/message/push", headers=_headers(), json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("週次レポートLINE送信成功")
        else:
            logger.error(f"週次レポートLINE送信失敗: {resp.status_code} {resp.text}")


def _report_row(label: str, current: int, prev: int) -> dict:
    """レポート行ヘルパー"""
    diff = current - prev
    diff_text = f"+{diff}" if diff > 0 else str(diff)
    diff_color = "#27ae60" if diff > 0 else "#e74c3c" if diff < 0 else "#888888"
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": "#888888", "flex": 3},
            {"type": "text", "text": str(current), "size": "sm", "weight": "bold", "flex": 2},
            {"type": "text", "text": diff_text, "size": "xs", "color": diff_color, "flex": 2, "align": "end"},
        ],
    }


async def reply_text(reply_token: str, text: str) -> None:
    """Webhookイベントにテキストで返信"""
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{LINE_API_BASE}/message/reply",
            headers=_headers(),
            json=payload,
            timeout=10,
        )

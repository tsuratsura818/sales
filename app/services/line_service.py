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

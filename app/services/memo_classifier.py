"""メモ→案件 AI自動分類サービス"""

import json
from app.config import get_settings
from app.services import notion_service

import httpx

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


async def classify_memo(memo_content: str) -> dict:
    """メモ内容をAIで分析し、最適な案件にマッチングする

    Returns:
        {
            "matched": True/False,
            "project_id": "xxx" or None,
            "project_name": "xxx" or None,
            "confidence": "high"/"medium"/"low",
            "reason": "マッチング理由"
        }
    """
    if not memo_content.strip():
        return {"matched": False, "project_id": None, "project_name": None, "confidence": "low", "reason": "空のメモ"}

    projects = await notion_service.list_projects()
    if not projects:
        return {"matched": False, "project_id": None, "project_name": None, "confidence": "low", "reason": "案件DBが空"}

    project_list = "\n".join(
        f"- ID: {p['id']} | 案件名: {p['name']} | クライアント: {p.get('client', '')} | ステータス: {p.get('status', '')}"
        for p in projects
    )

    settings = get_settings()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "messages": [
                    {
                        "role": "user",
                        "content": f"""以下のメモが、どの案件に関するものか判定してください。

【案件一覧】
{project_list}

【メモ内容】
{memo_content[:2000]}

JSONで回答してください（コードブロック不要）:
- matched: boolean (該当する案件があるか)
- project_id: string (該当案件のID。なければnull)
- project_name: string (該当案件名。なければnull)
- confidence: string (high/medium/low)
- reason: string (判定理由を1行で)

該当する案件がない場合は matched: false にしてください。"""
                    }
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    text = data["content"][0]["text"].strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        result = json.loads(text)
        return {
            "matched": result.get("matched", False),
            "project_id": result.get("project_id"),
            "project_name": result.get("project_name"),
            "confidence": result.get("confidence", "low"),
            "reason": result.get("reason", ""),
        }
    except json.JSONDecodeError:
        return {"matched": False, "project_id": None, "project_name": None, "confidence": "low", "reason": "分類エラー"}


async def append_memo_to_project(project_id: str, memo_title: str, memo_content: str) -> bool:
    """メモ内容をNotionの案件ページに追記する"""
    settings = get_settings()

    blocks: list[dict] = [
        {
            "object": "block",
            "type": "divider",
            "divider": {},
        },
        {
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": [{"type": "text", "text": {"content": f"📝 {memo_title}"}}],
            },
        },
    ]

    for line in memo_content.split("\n"):
        if not line.strip():
            continue
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": line[:2000]}}],
            },
        })

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                f"{NOTION_API_BASE}/blocks/{project_id}/children",
                headers={
                    "Authorization": f"Bearer {settings.NOTION_API_KEY}",
                    "Notion-Version": NOTION_VERSION,
                    "Content-Type": "application/json",
                },
                json={"children": blocks[:100]},
            )
            resp.raise_for_status()
            return True
    except Exception:
        return False

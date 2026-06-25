"""秘書AIチャット ルーター。

claude 実行はユーザーPC上のローカルブリッジ(claude_bridge.py)が行う。
このサーバーは prepare(プロンプト生成) と execute(アクション実行) のみ担当。
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.services import assistant_service

router = APIRouter(tags=["assistant"])


def _get_templates():
    from main import templates
    return templates


@router.get("/assistant", response_class=HTMLResponse)
async def assistant_page(request: Request):
    """秘書チャット画面"""
    return _get_templates().TemplateResponse(request, "assistant.html", {})


class PrepareRequest(BaseModel):
    messages: list[dict]


class ExecuteRequest(BaseModel):
    raw: str


@router.post("/api/assistant/prepare")
async def api_prepare(data: PrepareRequest):
    """会話履歴 → claude に渡すプロンプトを生成"""
    return await assistant_service.prepare(data.messages or [])


@router.post("/api/assistant/execute")
async def api_execute(data: ExecuteRequest):
    """claude の出力を解釈してタスク操作を実行"""
    return await assistant_service.execute_raw(data.raw or "")

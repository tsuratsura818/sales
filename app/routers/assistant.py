"""秘書AIチャット ルーター（ローカル実行時のみ機能）"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.services import assistant_service, local_claude

router = APIRouter(tags=["assistant"])


def _get_templates():
    from main import templates
    return templates


@router.get("/assistant", response_class=HTMLResponse)
async def assistant_page(request: Request):
    """秘書チャット画面"""
    return _get_templates().TemplateResponse(request, "assistant.html", {
        "available": local_claude.is_available(),
    })


class ChatRequest(BaseModel):
    messages: list[dict]


@router.post("/api/assistant/chat")
async def api_assistant_chat(data: ChatRequest):
    """会話を1ターン処理し、返答とアクション実行結果を返す"""
    return await assistant_service.chat(data.messages or [])

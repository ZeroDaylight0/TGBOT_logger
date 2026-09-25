from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import DATA_DIR, HOST, PORT, STATIC_DIR
from .database import (
    bind_sent_message,
    get_bot_stats,
    get_bot_token,
    get_empty_chat_diagnostics,
    init_db,
    list_bots,
    list_chats,
    list_messages,
    record_message,
    upsert_bot,
)
from .telegram_service import BotManager


class BotCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    token: str = Field(..., min_length=1)


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1)


async def send_telegram_message(bot_id: int, chat_id: str, text: str) -> dict[str, Any]:
    token = get_bot_token(bot_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise ValueError(payload.get("description") or "Telegram send failed")
        return payload["result"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    app.state.bot_manager = BotManager()
    await app.state.bot_manager.bootstrap()
    try:
        yield
    finally:
        await app.state.bot_manager.shutdown()


app = FastAPI(title="TGbot_tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bots")
def get_bots() -> list[dict[str, Any]]:
    return list_bots()


@app.post("/api/bots")
def add_bot(payload: BotCreateRequest) -> dict[str, Any]:
    name = payload.name.strip()
    token = payload.token.strip()
    if not name or not token:
        raise HTTPException(status_code=400, detail="Both name and token are required")
    try:
        bot = upsert_bot(name, token)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return bot


@app.get("/api/bots/{bot_id}/chats")
def get_chats(bot_id: int) -> list[dict[str, Any]]:
    return list_chats(bot_id)


@app.get("/api/bots/{bot_id}/chats/{chat_id}/diagnostics")
def chat_diagnostics(bot_id: int, chat_id: str) -> dict[str, Any]:
    rows = list_messages(bot_id=bot_id, chat_id=chat_id, limit=20)
    return {
        "chat_id": chat_id,
        "has_history": bool(rows),
        "note": "Telegram does not expose history from before the bot started polling. Only messages seen while the bot was active, or messages sent through this app, are archived.",
    }


@app.get("/api/bots/{bot_id}/diagnostics")
def root_diagnostics(bot_id: int) -> dict[str, Any]:
    return get_empty_chat_diagnostics(bot_id)


@app.get("/api/bots/{bot_id}/messages")
def get_messages(bot_id: int, chat_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return list_messages(bot_id=bot_id, chat_id=chat_id, limit=limit)


@app.post("/api/bots/{bot_id}/chats/{chat_id}/messages")
async def send_message(bot_id: int, chat_id: str, payload: SendMessageRequest) -> dict[str, Any]:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text cannot be empty")
    try:
        local_message_id = int(time.time() * 1000) % 1000000000
        saved = record_message(
            bot_id=bot_id,
            chat_id=chat_id,
            message_id=local_message_id,
            event_type="outgoing_message",
            payload={"chat": {"id": chat_id, "type": "private"}, "text": text, "date": int(time.time())},
            direction="outgoing",
            sender_name="Bot",
            recipient_name=chat_id,
        )
        if saved is None:
            raise RuntimeError("Outgoing message could not be persisted")
        telegram_result = await send_telegram_message(bot_id, chat_id, text)
        linked = bind_sent_message(bot_id, chat_id, local_message_id, telegram_result)
        if linked is None:
            raise RuntimeError("Outgoing message record was not linked to Telegram result")
        return linked
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to send Telegram message: {exc}") from exc


@app.get("/api/bots/{bot_id}/stats")
def bot_stats(bot_id: int) -> dict[str, Any]:
    return get_bot_stats(bot_id)


@app.get("/api/media/{bot_id}/{file_path:path}")
def media_file(bot_id: int, file_path: str) -> FileResponse:
    target = (DATA_DIR / str(bot_id) / file_path).resolve()
    if not target.exists() or not str(target).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(target)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)

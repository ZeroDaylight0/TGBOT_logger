from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher
from aiogram.types import Message

from .config import DATA_DIR
from .database import get_bot_token, list_active_bots, record_message, upsert_chat


class BotManager:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._running: bool = False

    async def bootstrap(self) -> None:
        if self._running:
            return
        self._running = True
        for bot in list_active_bots():
            await self.start_bot(bot["id"], bot["token"], bot["name"])

    async def start_bot(self, bot_id: int, token: str, name: str) -> None:
        if bot_id in self._tasks:
            return

        async def runner() -> None:
            bot = Bot(token=token)
            dispatcher = Dispatcher()

            @dispatcher.message()
            async def on_message(message: Message) -> None:
                await self._archive_message(bot_id, message, "message")

            @dispatcher.edited_message()
            async def on_edited_message(message: Message) -> None:
                await self._archive_message(bot_id, message, "edited_message", is_edited=True)

            @dispatcher.channel_post()
            async def on_channel_post(message: Message) -> None:
                await self._archive_message(bot_id, message, "channel_post")

            @dispatcher.edited_channel_post()
            async def on_edited_channel_post(message: Message) -> None:
                await self._archive_message(bot_id, message, "edited_channel_post", is_edited=True)

            try:
                await dispatcher.start_polling(bot)
            finally:
                await bot.session.close()

        task = asyncio.create_task(runner())
        self._tasks[bot_id] = task

    async def register_and_start(self, name: str, token: str) -> dict[str, object]:
        await self._ensure_valid_token(token)
        bot = await asyncio.to_thread(self._persist_bot, name, token)
        await self.start_bot(int(bot["id"]), token, name)
        return bot

    def _persist_bot(self, name: str, token: str) -> dict[str, object]:
        from .database import upsert_bot

        return upsert_bot(name, token)

    async def shutdown(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self._running = False

    async def _archive_message(self, bot_id: int, message: Message, event_type: str, *, is_edited: bool = False, is_deleted: bool = False) -> None:
        payload = message.model_dump(mode="json")
        chat = payload.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        title = chat.get("title") or chat.get("username") or chat.get("first_name") or chat.get("last_name")
        upsert_chat(bot_id, str(chat_id), title, chat.get("type"))
        media_path = await self._save_media_if_needed(bot_id, payload, message)
        avatar_path = await self._assign_avatar_from_sender(bot_id, payload)
        record_message(
            bot_id=bot_id,
            chat_id=str(chat_id),
            message_id=int(payload.get("message_id") or payload.get("id") or 0),
            event_type=event_type,
            payload=payload,
            media_path=media_path,
            avatar_path=avatar_path,
            direction="incoming",
            is_edited=is_edited,
            is_deleted=is_deleted,
        )

    @staticmethod
    def _first_file_id(media_value: object) -> str | None:
        if isinstance(media_value, list):
            for item in reversed(media_value):
                file_id = BotManager._first_file_id(item)
                if file_id:
                    return file_id
            return None
        if not isinstance(media_value, dict):
            return None
        file_id = media_value.get("file_id")
        if isinstance(file_id, str) and file_id:
            return file_id
        return None

    async def _assign_avatar_from_sender(self, bot_id: int, payload: dict[str, object]) -> str | None:
        sender = payload.get("from")
        if not isinstance(sender, dict):
            return None
        user_id = sender.get("id")
        if not user_id:
            return None
        token = get_bot_token(bot_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://api.telegram.org/bot{token}/getUserProfilePhotos",
                params={"user_id": user_id, "limit": 1},
            )
            response.raise_for_status()
            data = response.json()
            photos = (data.get("result") or {}).get("photos") or []
            if not photos:
                return None
            file_id = self._first_file_id(photos[0])
            if not file_id:
                return None
            file_response = await client.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
            file_response.raise_for_status()
            file_payload = file_response.json()
            file_path = (file_payload.get("result") or {}).get("file_path")
            if not file_path:
                return None
            media_response = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
            media_response.raise_for_status()
            storage_dir = DATA_DIR / str(bot_id)
            storage_dir.mkdir(parents=True, exist_ok=True)
            filename = f"avatar_{user_id}_{Path(file_path).name}"
            destination = storage_dir / filename
            destination.write_bytes(media_response.content)
            return str(destination.relative_to(DATA_DIR)).replace("\\", "/")

    async def _save_media_if_needed(self, bot_id: int, payload: dict[str, object], message: Message) -> str | None:
        media_candidates = [
            payload.get("photo"),
            payload.get("document"),
            payload.get("video"),
            payload.get("voice"),
            payload.get("audio"),
            payload.get("animation"),
            payload.get("sticker"),
        ]
        file_id = None
        for media in media_candidates:
            file_id = self._first_file_id(media)
            if file_id:
                break
        if not file_id:
            return None
        token = get_bot_token(bot_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
            response.raise_for_status()
            file_data = response.json()
            file_path = (file_data.get("result") or {}).get("file_path")
            if not file_path:
                return None
            file_response = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
            file_response.raise_for_status()
            file_name = Path(file_path).name or f"{message.message_id}.bin"
            storage_dir = DATA_DIR / str(bot_id)
            storage_dir.mkdir(parents=True, exist_ok=True)
            destination = storage_dir / file_name
            destination.write_bytes(file_response.content)
            return str(destination.relative_to(DATA_DIR)).replace("\\", "/")

    @staticmethod
    async def _ensure_valid_token(token: str) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise ValueError("Telegram token validation failed")

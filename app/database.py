from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .security import decrypt_value, encrypt_value


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_event_ts(value: Any) -> str:
    if value is None:
        return utc_now()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(int(value), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                return value
    return str(value)


def get_db_path() -> Path:
    return Path(config.DB_PATH)


def _ensure_message_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT,
            token_cipher TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            chat_id TEXT NOT NULL,
            title TEXT,
            chat_type TEXT,
            last_seen_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bot_id, chat_id),
            FOREIGN KEY(bot_id) REFERENCES bots(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            chat_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'incoming',
            message_text TEXT,
            raw_json TEXT NOT NULL,
            media_path TEXT,
            avatar_path TEXT,
            sender_name TEXT,
            sender_username TEXT,
            sender_id INTEGER,
            recipient_name TEXT,
            recipient_username TEXT,
            recipient_id INTEGER,
            telegram_message_id INTEGER,
            is_edited INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            edited_at TEXT,
            deleted_at TEXT,
            UNIQUE(bot_id, chat_id, message_id, event_type),
            FOREIGN KEY(bot_id) REFERENCES bots(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_bot_chat_created ON messages(bot_id, chat_id, created_at DESC);
        """
    )

    message_columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)").fetchall()}
    for column_name, column_sql in {
        "direction": "direction TEXT NOT NULL DEFAULT 'incoming'",
        "message_text": "message_text TEXT",
        "raw_json": "raw_json TEXT NOT NULL DEFAULT '{}'",
        "media_path": "media_path TEXT",
        "avatar_path": "avatar_path TEXT",
        "sender_name": "sender_name TEXT",
        "sender_username": "sender_username TEXT",
        "sender_id": "sender_id INTEGER",
        "recipient_name": "recipient_name TEXT",
        "recipient_username": "recipient_username TEXT",
        "recipient_id": "recipient_id INTEGER",
        "telegram_message_id": "telegram_message_id INTEGER",
    }.items():
        if column_name not in message_columns:
            db.execute(f"ALTER TABLE messages ADD COLUMN {column_sql}")

    db.commit()


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _ensure_message_schema(conn)
    return conn


def init_db() -> None:
    db = open_db()
    db.close()


def upsert_bot(name: str, token: str) -> dict[str, Any]:
    encrypted = encrypt_value(token)
    db = open_db()
    cursor = db.execute(
        "INSERT INTO bots (name, token_cipher, enabled, created_at) VALUES (?, ?, 1, ?)",
        (name, encrypted, utc_now()),
    )
    row = db.execute("SELECT * FROM bots WHERE id = ?", (cursor.lastrowid,)).fetchone()
    db.commit()
    db.close()
    return dict(row)


def list_bots() -> list[dict[str, Any]]:
    db = open_db()
    rows = db.execute(
        "SELECT id, name, username, enabled, created_at FROM bots ORDER BY id ASC"
    ).fetchall()
    db.close()
    return [dict(row) for row in rows]


def get_bot_by_id(bot_id: int) -> dict[str, Any] | None:
    db = open_db()
    row = db.execute("SELECT * FROM bots WHERE id = ?", (bot_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def get_bot_token(bot_id: int) -> str:
    row = get_bot_by_id(bot_id)
    if row is None:
        raise KeyError(f"Bot {bot_id} does not exist")
    return decrypt_value(row["token_cipher"])


def list_active_bots() -> list[dict[str, Any]]:
    db = open_db()
    rows = db.execute(
        "SELECT * FROM bots WHERE enabled = 1 ORDER BY id ASC"
    ).fetchall()
    db.close()
    active = []
    for row in rows:
        payload = dict(row)
        payload["token"] = decrypt_value(payload["token_cipher"])
        active.append(payload)
    return active


def upsert_chat(bot_id: int, chat_id: str, title: str | None, chat_type: str | None) -> None:
    db = open_db()
    db.execute(
        """
        INSERT INTO chats (bot_id, chat_id, title, chat_type, last_seen_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(bot_id, chat_id)
        DO UPDATE SET title = excluded.title, chat_type = excluded.chat_type, last_seen_at = excluded.last_seen_at
        """,
        (bot_id, str(chat_id), title, chat_type, utc_now(), utc_now()),
    )
    db.commit()
    db.close()


def _infer_identity(payload: dict[str, Any], direction: str) -> dict[str, Any]:
    chat = payload.get("chat") or {}
    from_user = payload.get("from") or {}
    if direction == "outgoing":
        sender_name = "Bot"
        sender_username = None
        sender_id = None
        recipient_name = chat.get("title") or chat.get("username") or chat.get("first_name") or chat.get("last_name") or "Unknown chat"
        recipient_username = chat.get("username") or None
        recipient_id = chat.get("id")
    else:
        sender_name = from_user.get("first_name") or from_user.get("username") or from_user.get("last_name") or "Unknown user"
        sender_username = from_user.get("username") or None
        sender_id = from_user.get("id")
        recipient_name = chat.get("title") or chat.get("username") or chat.get("first_name") or chat.get("last_name") or "Bot"
        recipient_username = chat.get("username") or None
        recipient_id = chat.get("id")
    return {
        "sender_name": sender_name,
        "sender_username": sender_username,
        "sender_id": sender_id,
        "recipient_name": recipient_name,
        "recipient_username": recipient_username,
        "recipient_id": recipient_id,
    }


def record_message(
    bot_id: int,
    chat_id: str,
    message_id: int,
    event_type: str,
    payload: dict[str, Any],
    media_path: str | None = None,
    *,
    direction: str = "incoming",
    sender_name: str | None = None,
    sender_username: str | None = None,
    sender_id: int | None = None,
    recipient_name: str | None = None,
    recipient_username: str | None = None,
    recipient_id: int | None = None,
    avatar_path: str | None = None,
    telegram_message_id: int | None = None,
    is_edited: bool = False,
    is_deleted: bool = False,
) -> dict[str, Any] | None:
    message_text = payload.get("text") or payload.get("caption") or ""
    raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    created_at = normalize_event_ts(payload.get("date") or utc_now())
    direction_name = (direction or "incoming").lower()
    identity = _infer_identity(payload, direction_name)
    sender_name = sender_name or identity["sender_name"]
    sender_username = sender_username or identity["sender_username"]
    sender_id = sender_id if sender_id is not None else identity["sender_id"]
    recipient_name = recipient_name or identity["recipient_name"]
    recipient_username = recipient_username or identity["recipient_username"]
    recipient_id = recipient_id if recipient_id is not None else identity["recipient_id"]
    db = open_db()
    row = db.execute(
        "SELECT id FROM messages WHERE bot_id = ? AND chat_id = ? AND message_id = ? AND event_type = ? LIMIT 1",
        (bot_id, str(chat_id), int(message_id), event_type),
    ).fetchone()
    row_data = {
        "bot_id": bot_id,
        "chat_id": str(chat_id),
        "message_id": int(message_id),
        "event_type": event_type,
        "direction": direction_name,
        "message_text": message_text,
        "raw_json": raw_json,
        "media_path": media_path,
        "avatar_path": avatar_path,
        "sender_name": sender_name,
        "sender_username": sender_username,
        "sender_id": sender_id,
        "recipient_name": recipient_name,
        "recipient_username": recipient_username,
        "recipient_id": recipient_id,
        "telegram_message_id": telegram_message_id,
        "is_edited": int(is_edited),
        "is_deleted": int(is_deleted),
        "created_at": created_at,
        "edited_at": utc_now() if is_edited else None,
        "deleted_at": utc_now() if is_deleted else None,
    }
    if row is not None:
        db.execute(
            """
            UPDATE messages SET
                direction = ?, message_text = ?, raw_json = ?, media_path = ?, avatar_path = ?,
                sender_name = ?, sender_username = ?, sender_id = ?, recipient_name = ?,
                recipient_username = ?, recipient_id = ?, telegram_message_id = ?, is_edited = ?,
                is_deleted = ?, created_at = ?, edited_at = COALESCE(?, edited_at), deleted_at = COALESCE(?, deleted_at)
            WHERE id = ?
            """,
            (
                row_data["direction"],
                row_data["message_text"],
                row_data["raw_json"],
                row_data["media_path"],
                row_data["avatar_path"],
                row_data["sender_name"],
                row_data["sender_username"],
                row_data["sender_id"],
                row_data["recipient_name"],
                row_data["recipient_username"],
                row_data["recipient_id"],
                row_data["telegram_message_id"],
                row_data["is_edited"],
                row_data["is_deleted"],
                row_data["created_at"],
                row_data["edited_at"],
                row_data["deleted_at"],
                row["id"],
            ),
        )
        updated = db.execute("SELECT * FROM messages WHERE id = ?", (row["id"],)).fetchone()
        db.commit()
        db.close()
        return dict(updated)

    cursor = db.execute(
        """
        INSERT INTO messages (
            bot_id, chat_id, message_id, event_type, direction, message_text, raw_json, media_path, avatar_path,
            sender_name, sender_username, sender_id, recipient_name, recipient_username, recipient_id,
            telegram_message_id, is_edited, is_deleted, created_at, edited_at, deleted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row_data["bot_id"],
            row_data["chat_id"],
            row_data["message_id"],
            row_data["event_type"],
            row_data["direction"],
            row_data["message_text"],
            row_data["raw_json"],
            row_data["media_path"],
            row_data["avatar_path"],
            row_data["sender_name"],
            row_data["sender_username"],
            row_data["sender_id"],
            row_data["recipient_name"],
            row_data["recipient_username"],
            row_data["recipient_id"],
            row_data["telegram_message_id"],
            row_data["is_edited"],
            row_data["is_deleted"],
            row_data["created_at"],
            row_data["edited_at"],
            row_data["deleted_at"],
        ),
    )
    db.commit()
    created = db.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
    db.close()
    return dict(created)


def bind_sent_message(bot_id: int, chat_id: str, local_message_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    message_text = payload.get("text") or payload.get("caption") or ""
    telegram_message_id = int(payload.get("message_id") or payload.get("id") or local_message_id)
    db = open_db()
    row = db.execute(
        "SELECT * FROM messages WHERE bot_id = ? AND chat_id = ? AND message_id = ? AND event_type = 'outgoing_message' ORDER BY id DESC LIMIT 1",
        (bot_id, str(chat_id), int(local_message_id)),
    ).fetchone()
    if row is None:
        db.close()
        return None
    db.execute(
        """
        UPDATE messages
        SET message_id = ?, telegram_message_id = ?, message_text = ?, raw_json = ?, direction = 'outgoing',
            sender_name = COALESCE(sender_name, 'Bot'), recipient_name = COALESCE(recipient_name, 'Bot'),
            created_at = COALESCE(created_at, ?)
        WHERE id = ?
        """,
        (
            telegram_message_id,
            telegram_message_id,
            message_text,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            normalize_event_ts(payload.get("date") or utc_now()),
            row["id"],
        ),
    )
    refreshed = db.execute("SELECT * FROM messages WHERE id = ?", (row["id"],)).fetchone()
    db.commit()
    db.close()
    return dict(refreshed)


def list_chats(bot_id: int | None = None) -> list[dict[str, Any]]:
    db = open_db()
    if bot_id is None:
        rows = db.execute(
            "SELECT bot_id, chat_id, title, chat_type, last_seen_at, created_at FROM chats ORDER BY last_seen_at DESC, chat_id ASC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT bot_id, chat_id, title, chat_type, last_seen_at, created_at FROM chats WHERE bot_id = ? ORDER BY last_seen_at DESC, chat_id ASC",
            (bot_id,),
        ).fetchall()
    db.close()
    return [dict(row) for row in rows]


def list_messages(bot_id: int | None = None, chat_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    db = open_db()
    sql = "SELECT * FROM messages"
    params: list[Any] = []
    clauses: list[str] = []
    if bot_id is not None:
        clauses.append("bot_id = ?")
        params.append(bot_id)
    if chat_id is not None:
        clauses.append("chat_id = ?")
        params.append(str(chat_id))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    db.close()
    return [dict(row) for row in rows]


def get_bot_stats(bot_id: int) -> dict[str, Any]:
    db = open_db()
    total = db.execute("SELECT COUNT(*) AS total FROM messages WHERE bot_id = ?", (bot_id,)).fetchone()["total"]
    edited = db.execute("SELECT COUNT(*) AS total FROM messages WHERE bot_id = ? AND is_edited = 1", (bot_id,)).fetchone()["total"]
    deleted = db.execute("SELECT COUNT(*) AS total FROM messages WHERE bot_id = ? AND is_deleted = 1", (bot_id,)).fetchone()["total"]
    chats = db.execute("SELECT COUNT(*) AS total FROM chats WHERE bot_id = ?", (bot_id,)).fetchone()["total"]
    db.close()
    return {"total_messages": total, "edited_messages": edited, "deleted_messages": deleted, "chats": chats}


def get_empty_chat_diagnostics(bot_id: int) -> dict[str, Any]:
    chats = list_chats(bot_id)
    empty = []
    for chat in chats:
        if not list_messages(bot_id=bot_id, chat_id=str(chat["chat_id"]), limit=20):
            empty.append(str(chat["chat_id"]))
    return {
        "total_chats": len(chats),
        "empty_chats": empty,
        "note": "Telegram does not provide pre-start history; only messages seen while the bot is polling, or messages sent through this app, are archived.",
    }

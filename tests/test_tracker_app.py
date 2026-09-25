import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.database import get_bot_token, init_db, list_messages, open_db, record_message, upsert_bot
from app.main import app
from app.security import decrypt_value, encrypt_value


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "tracker.db"
    key_path = tmp_path / "tracker.key"
    monkeypatch.setattr('app.config.DB_PATH', db_path)
    monkeypatch.setattr('app.config.KEY_PATH', key_path)
    init_db()
    yield
    if db_path.exists():
        db_path.unlink()
    if key_path.exists():
        key_path.unlink()


def test_encryption_roundtrip_and_token_storage(isolated_db):
    token = "123456:ABCDEF"
    cipher = encrypt_value(token)
    assert token == decrypt_value(cipher)
    assert token not in cipher
    bot = upsert_bot("demo", token)
    assert get_bot_token(bot["id"]) == token


def test_message_recording_and_flags(isolated_db):
    bot = upsert_bot("demo", "123456:ABCDEF")
    record_message(
        bot_id=bot["id"],
        chat_id="-100123",
        message_id=42,
        event_type="message",
        payload={"text": "hello", "date": 1700000000},
    )
    record_message(
        bot_id=bot["id"],
        chat_id="-100123",
        message_id=42,
        event_type="edited_message",
        payload={"text": "hello edited", "date": 1700000100},
        is_edited=True,
    )
    rows = list_messages(bot_id=bot["id"], chat_id="-100123")
    assert len(rows) == 2
    edited = next(item for item in rows if item["event_type"] == "edited_message")
    assert edited["is_edited"] == 1
    assert edited["message_text"] == "hello edited"


def test_web_api_creates_bot_and_reads_stats(isolated_db):
    client = TestClient(app)
    response = client.post('/api/bots', json={"name": "demo", "token": "123456:ABCDEF"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "demo"

    stats = client.get(f"/api/bots/{payload['id']}/stats")
    assert stats.status_code == 200
    assert stats.json()["total_messages"] == 0


def test_send_message_route_records_outgoing_message_and_binds_telegram_id(isolated_db, monkeypatch):
    client = TestClient(app)
    bot = client.post('/api/bots', json={"name": "demo", "token": "123456:ABCDEF"}).json()

    async def fake_send(bot_id, chat_id, text):
        assert bot_id == bot["id"]
        assert chat_id == "-555"
        assert text == "hello from UI"
        return {"message_id": 99, "chat": {"id": "-555", "type": "private"}, "date": 1700000200, "text": text}

    monkeypatch.setattr('app.main.send_telegram_message', fake_send)
    response = client.post(f"/api/bots/{bot['id']}/chats/-555/messages", json={"text": "hello from UI"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["direction"] == "outgoing"
    assert body["telegram_message_id"] == 99
    assert body["message_text"] == "hello from UI"


def test_legacy_database_schema_is_migrated_on_open(tmp_path, monkeypatch):
    legacy_db = tmp_path / 'legacy_tracker.db'
    legacy_key = tmp_path / 'legacy.key'
    monkeypatch.setattr('app.config.DB_PATH', legacy_db)
    monkeypatch.setattr('app.config.KEY_PATH', legacy_key)

    conn = sqlite3.connect(str(legacy_db))
    conn.execute("CREATE TABLE bots (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, username TEXT, token_cipher TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE chats (id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER NOT NULL, chat_id TEXT NOT NULL, title TEXT, chat_type TEXT, last_seen_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(bot_id, chat_id))")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER NOT NULL, chat_id TEXT NOT NULL, message_id INTEGER NOT NULL, event_type TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.commit()
    conn.close()

    conn = open_db()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    assert 'direction' in columns
    assert 'message_text' in columns
    conn.close()


def test_media_save_handles_telegram_photo_list(isolated_db, monkeypatch):
    from types import SimpleNamespace

    import app.config
    from app.telegram_service import BotManager

    class DummyResult:
        def __init__(self, json_data, content=b'file-bytes'):
            self._json = json_data
            self.content = content
        def json(self):
            return self._json
        def raise_for_status(self):
            return None

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url, params=None):
            if 'getFile' in url:
                return DummyResult({"result": {"file_path": "photos/file.jpg"}})
            return DummyResult({"ok": True}, content=b'photo-bytes')

    monkeypatch.setattr('app.telegram_service.httpx.AsyncClient', DummyClient)
    monkeypatch.setattr('app.telegram_service.get_bot_token', lambda bot_id: 'token')

    payload = {"photo": [{"file_id": "small"}, {"file_id": "large"}]}
    result = asyncio.run(BotManager()._save_media_if_needed(1, payload, SimpleNamespace(message_id=7)))
    assert result is not None
    assert result.endswith('file.jpg')

<div align="center">

# TGbot_tracker

### A local archive for everything your Telegram bots receive

Messages, photos, videos and voice messages sent to your bots are saved to a
local SQLite database and browsed in a Telegram-style web UI.

[![CI](https://github.com/ZeroDaylight0/TGBOT_logger/actions/workflows/ci.yml/badge.svg)](https://github.com/ZeroDaylight0/TGBOT_logger/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-aiogram_3-009688?logo=fastapi&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## Features

- **Multiple bots.** Add any number of bot tokens from the web UI; each bot is polled in its own background task.
- **Encrypted tokens.** Tokens are encrypted with a Fernet key stored next to the app (`tracker.key`).
- **Full archive.** Raw Telegram update JSON goes to SQLite, and media files are downloaded into a per-bot folder under `data/`.
- **Immutable history.** Message records are never overwritten; edits and deletions are flagged where Telegram exposes them.
- **Conversation view.** Incoming and outgoing direction, sender and recipient metadata, cached avatars and a Telegram-like chat layout.
- **Reply from the UI.** Outgoing messages are saved as pending, sent with `sendMessage`, then linked to the Telegram `message_id`.
- **Local only.** The FastAPI server binds to `127.0.0.1`.

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/ZeroDaylight0/TGBOT_logger.git
cd TGBOT_logger
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>, then add a bot name and the token you got from [@BotFather](https://t.me/BotFather).

On Windows you can also run [`start_tracker.bat`](start_tracker.bat).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TG_TRACKER_HOST` | `127.0.0.1` | Listen address. |
| `TG_TRACKER_PORT` | `8000` | HTTP port. |
| `TG_TRACKER_DB_PATH` | `./tracker.db` | SQLite database file. |
| `TG_TRACKER_KEY_PATH` | `./tracker.key` | Fernet key used to encrypt bot tokens. |

## Project structure

```text
TGBOT_logger/
├── app/
│   ├── main.py              # FastAPI app and REST API
│   ├── telegram_service.py  # aiogram polling workers and media download
│   ├── database.py          # SQLite schema and queries
│   ├── security.py          # Token encryption
│   └── config.py            # Paths, host and port
├── static/index.html        # Web UI
├── tests/                   # pytest suite
└── start_tracker.bat        # Windows launcher
```

## Tests

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

## Limitations

- Telegram does not give bots message history from before they started polling, so only updates seen while the tracker runs are archived, plus messages sent from the UI.
- A bot token can be used by one polling client at a time. Stop other scripts that poll the same bot.

## Privacy and security

- Keep `tracker.key`, `tracker.db` and `data/` private: together they contain the decrypted tokens and every archived message. All three are in `.gitignore`.
- Do not expose the server to the internet: the web UI has no authentication.
- Archive only bots you own, and let the people writing to them know their messages are stored.

## License

[MIT](LICENSE) © 2026 ZeroDaylight0

# TGbot_tracker

TGbot_tracker is a local-only Telegram activity tracker that stores multiple bot tokens in a local SQLite database, encrypts each token with a Fernet key stored next to the app, and archives Telegram message payloads plus any downloaded media.

## Features

- FastAPI web UI and REST API on 127.0.0.1 only.
- Support for multiple bot tokens added through the web UI.
- SQLite-backed storage of bot metadata, chats, and message records.
- Encrypted token persistence using a local key file (`tracker.key`).
- Durable archive of raw Telegram payloads and downloaded media under `data/`.
- Immutable message records with edited/deleted flags where Telegram exposes them.
- Chat and message browsing via the bundled static frontend.
- Incoming/outgoing direction, sender/recipient metadata, avatar caching, and Telegram-like conversation UI.
- Outgoing message send flow: save pending record, call Telegram `sendMessage`, then bind the Telegram `message_id`.
- Windows launch helper for local development and simple startup.

## Quick start

1. Install dependencies:

   python -m pip install -r requirements.txt

2. Start the app:

   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

3. Open the browser at http://127.0.0.1:8000/

4. Add bot tokens from the dashboard.

## Windows startup

Run the included helper:

start_tracker.bat

This launches the app with the local-only host and port configuration from the app config.

## Notes

- The app intentionally binds to `127.0.0.1` and should not be exposed externally.
- The Telegram library used by the polling worker keeps each configured bot alive in a background task.
- Telegram does not expose message history created before the bot started polling. The app therefore archives only updates seen while polling is active, plus outgoing messages created through the app UI.
- The raw Telegram update JSON is retained in SQLite, while media files are saved under the bot-specific data directory.

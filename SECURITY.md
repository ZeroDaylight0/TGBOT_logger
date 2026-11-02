# Security Policy

## Supported versions

Only the latest version on the `main` branch receives fixes.

## Threat model

TGbot_tracker is a **local-only** tool:

- The FastAPI server binds to `127.0.0.1` and is not meant to be exposed to the internet.
  If you put it behind a reverse proxy, add authentication in front of it.
- Bot tokens are encrypted at rest with a Fernet key stored in `tracker.key`.
  Anyone with access to both `tracker.key` and the SQLite database can decrypt the tokens,
  so keep the data directory private and back it up securely.
- Archived messages and media in `data/` may contain personal data of your bot users.

Never commit `tracker.key`, `*.db` files or the `data/` folder.

## Reporting a vulnerability

Please do **not** open a public issue for security problems.
Use [GitHub private vulnerability reporting](https://github.com/ZeroDaylight0/TGBOT_logger/security/advisories/new)
with steps to reproduce. If a bot token was leaked, revoke it via [@BotFather](https://t.me/BotFather) first.

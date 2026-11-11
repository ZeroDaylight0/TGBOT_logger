# Contributing

Thanks for helping improve TGbot_tracker!

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Tests

```bash
python -m pytest -q
```

CI runs the suite on Python 3.10 – 3.13, so avoid syntax newer than 3.10.

## Guidelines

- One logical change per pull request.
- Add tests for database and Telegram update parsing changes.
- Never include real bot tokens, `tracker.key` or archived user data in commits or issues.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, `chore:`).

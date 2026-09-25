from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from . import config


def ensure_key(path: Path | None = None) -> bytes:
    target = Path(path) if path is not None else Path(config.KEY_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(Fernet.generate_key())
    return target.read_bytes()


def encrypt_value(value: str, key: bytes | None = None) -> str:
    active_key = ensure_key() if key is None else key
    return Fernet(active_key).encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(cipher_text: str, key: bytes | None = None) -> str:
    active_key = ensure_key() if key is None else key
    return Fernet(active_key).decrypt(cipher_text.encode("utf-8")).decode("utf-8")

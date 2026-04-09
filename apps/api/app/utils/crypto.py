"""Symmetric encryption helpers for sensitive DB columns.

Usage
-----
Messages are stored encrypted when MESSAGES_ENCRYPTION_KEY is set in .env.

Generate a key once (keep it secret, store in .env):

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Storage format
--------------
Encrypted messages are stored in the JSONB column as a JSON *string* value:

    "enc:v1:<base64-fernet-token>"

On read the column value is parsed with json.loads().  If the result is a
Python *list* it is legacy unencrypted data.  If it is a *string* that starts
with the prefix it is decrypted before use.

Backward compatibility
----------------------
- If MESSAGES_ENCRYPTION_KEY is empty the functions store/return plain data.
- Existing unencrypted rows continue to work after the key is added.
- Re-encryption of existing rows is NOT performed automatically; rows are
  re-encrypted in place the next time they are written.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.settings import settings

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet | None:
    key = settings.messages_encryption_key
    if not key:
        return None
    return Fernet(key.encode())


def is_encryption_enabled() -> bool:
    """Return True when a valid encryption key is configured."""
    return bool(settings.messages_encryption_key)


def encrypt_messages(messages: list[dict]) -> str:
    """Encrypt a messages list to a storable JSON string.

    Returns a JSON-encodable string ``"enc:v1:<token>"`` when a key is
    configured, or a plain JSON array string when it is not.
    """
    f = _fernet()
    if f is None:
        return json.dumps(messages)
    token = f.encrypt(json.dumps(messages).encode()).decode()
    return f"{_PREFIX}{token}"


def decrypt_messages(raw: object) -> list[dict]:
    """Decrypt a stored messages value back to a list of message dicts.

    Handles three input shapes:
    - ``list``   — legacy unencrypted JSONB array; returned as-is.
    - ``str`` starting with *_PREFIX* — Fernet-encrypted; decrypted.
    - ``str`` without prefix — plain JSON string (no key was set at write
      time); parsed and returned.
    """
    if isinstance(raw, list):
        return raw

    if not isinstance(raw, str):
        return []

    if raw.startswith(_PREFIX):
        f = _fernet()
        if f is None:
            raise ValueError(
                "Encrypted messages were found in the database but "
                "MESSAGES_ENCRYPTION_KEY is not configured. "
                "Set the key in .env to decrypt existing data."
            )
        try:
            return json.loads(f.decrypt(raw[len(_PREFIX) :].encode()))
        except InvalidToken as exc:
            logger.error("Message decryption failed — wrong key or corrupted data: %s", exc)
            return []

    # Plain (unencrypted) JSON string
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (ValueError, TypeError):
        return []

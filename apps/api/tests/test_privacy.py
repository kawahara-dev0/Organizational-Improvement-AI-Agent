"""Tests for PII masking and message encryption utilities.

Covers:
- pii.mask_pii()              — all regex patterns + no-op on clean text
- crypto.encrypt_messages()   — produces enc:v1: prefix when key set
- crypto.decrypt_messages()   — roundtrip, legacy list, plain JSON, wrong key
- crypto.is_encryption_enabled()
- repository: encrypted append_message / get_consultation roundtrip (DB)

Run with:
    docker compose run --rm api uv run pytest tests/test_privacy.py -v
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.utils.crypto import _fernet, decrypt_messages, encrypt_messages, is_encryption_enabled
from app.utils.pii import mask_pii

# ── Helpers ────────────────────────────────────────────────────────────────


def _with_key(key: str):
    """Context manager: patch settings.messages_encryption_key and clear cache."""

    class _Ctx:
        def __enter__(self):
            self._patcher = patch("app.utils.crypto.settings")
            mock_s = self._patcher.start()
            mock_s.messages_encryption_key = key
            _fernet.cache_clear()
            return mock_s

        def __exit__(self, *_):
            self._patcher.stop()
            _fernet.cache_clear()

    return _Ctx()


# ── PII masking ────────────────────────────────────────────────────────────


def test_mask_pii_email() -> None:
    result = mask_pii("Please contact alice@example.com for details.")
    assert result == "Please contact [EMAIL] for details."


def test_mask_pii_japanese_mobile_dash() -> None:
    assert mask_pii("Tel: 090-1234-5678") == "Tel: [PHONE]"
    assert mask_pii("Tel: 080-9876-5432") == "Tel: [PHONE]"
    assert mask_pii("Tel: 070-0000-1111") == "Tel: [PHONE]"


def test_mask_pii_japanese_landline() -> None:
    assert mask_pii("03-1234-5678") == "[PHONE]"
    assert mask_pii("06-9999-0000") == "[PHONE]"
    assert mask_pii("0120-123-456") == "[PHONE]"


def test_mask_pii_international_phone() -> None:
    assert mask_pii("+81-3-1234-5678") == "[PHONE]"
    assert mask_pii("+1.800.123.4567") == "[PHONE]"


def test_mask_pii_multiple_patterns_in_one_string() -> None:
    text = "Mail me at bob@corp.jp or call 090-1111-2222"
    result = mask_pii(text)
    assert "[EMAIL]" in result
    assert "[PHONE]" in result
    assert "bob@corp.jp" not in result
    assert "090-1111-2222" not in result


def test_mask_pii_clean_text_unchanged() -> None:
    clean = "I feel stressed about my workload."
    assert mask_pii(clean) == clean


def test_mask_pii_empty_string() -> None:
    assert mask_pii("") == ""


# ── Encryption (unit — no DB) ──────────────────────────────────────────────


def test_is_encryption_enabled_false_when_no_key() -> None:
    with _with_key(""):
        assert is_encryption_enabled() is False


def test_is_encryption_enabled_true_when_key_set() -> None:
    key = Fernet.generate_key().decode()
    with _with_key(key):
        assert is_encryption_enabled() is True


def test_encrypt_messages_returns_prefix_when_key_set() -> None:
    key = Fernet.generate_key().decode()
    with _with_key(key):
        result = encrypt_messages([{"role": "user", "content": "Hello"}])
    assert result.startswith("enc:v1:")


def test_encrypt_messages_returns_plain_json_when_no_key() -> None:
    with _with_key(""):
        result = encrypt_messages([{"role": "user", "content": "Hello"}])
    # Should be a valid JSON array string, not encrypted.
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert parsed[0]["content"] == "Hello"


def test_encrypt_decrypt_roundtrip() -> None:
    key = Fernet.generate_key().decode()
    messages = [
        {"role": "user", "content": "I have a complaint."},
        {"role": "assistant", "content": "I understand.", "mode": "personal"},
    ]
    with _with_key(key):
        encrypted = encrypt_messages(messages)
        decrypted = decrypt_messages(encrypted)
    assert decrypted == messages


def test_decrypt_messages_legacy_list() -> None:
    """A Python list (legacy unencrypted JSONB) is returned as-is."""
    msgs = [{"role": "user", "content": "old message"}]
    assert decrypt_messages(msgs) == msgs


def test_decrypt_messages_plain_json_string() -> None:
    """A plain JSON string (no key at write time) is parsed and returned."""
    msgs = [{"role": "user", "content": "plain text"}]
    json_str = json.dumps(msgs)
    with _with_key(""):
        result = decrypt_messages(json_str)
    assert result == msgs


def test_decrypt_messages_wrong_key_returns_empty() -> None:
    """Decrypting with the wrong key logs an error and returns an empty list."""
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()
    messages = [{"role": "user", "content": "secret"}]
    with _with_key(key1):
        encrypted = encrypt_messages(messages)
    with _with_key(key2):
        result = decrypt_messages(encrypted)
    assert result == []


def test_decrypt_messages_no_key_for_encrypted_data_raises() -> None:
    """Receiving encrypted data without a configured key raises ValueError."""
    key = Fernet.generate_key().decode()
    messages = [{"role": "user", "content": "secret"}]
    with _with_key(key):
        encrypted = encrypt_messages(messages)
    with _with_key(""), pytest.raises(ValueError, match="MESSAGES_ENCRYPTION_KEY"):
        decrypt_messages(encrypted)


# ── Encryption — DB integration (repository layer) ────────────────────────


@pytest.mark.asyncio
async def test_encrypted_messages_roundtrip_in_db(db_conn) -> None:
    """When encryption is enabled, messages stored in DB are ciphertext
    but round-trip correctly through get_consultation()."""
    from app.consultations.repository import (
        append_message,
        create_consultation,
        get_consultation,
    )

    key = Fernet.generate_key().decode()

    # Patch both the crypto module's settings AND the repository's helpers
    # so the same key is used for writes and reads.
    with (
        patch("app.utils.crypto.settings") as mock_s,
        patch("app.consultations.repository.is_encryption_enabled", return_value=True),
        patch(
            "app.consultations.repository.encrypt_messages",
            side_effect=lambda msgs: __import__(
                "app.utils.crypto", fromlist=["encrypt_messages"]
            ).encrypt_messages(msgs),
        ),
        patch(
            "app.consultations.repository.decrypt_messages",
            side_effect=lambda raw: __import__(
                "app.utils.crypto", fromlist=["decrypt_messages"]
            ).decrypt_messages(raw),
        ),
    ):
        mock_s.messages_encryption_key = key
        _fernet.cache_clear()

        try:
            cid = await create_consultation(db_conn)
            await append_message(db_conn, cid, "user", "I need help with harassment.")
            await append_message(db_conn, cid, "assistant", "I understand.", mode="personal")

            # Verify raw DB value is encrypted (should NOT be a JSON array).
            raw_json = await db_conn.fetchval(
                "SELECT messages::text FROM consultations WHERE id = $1", cid
            )
            raw_python = json.loads(raw_json)
            # DB should contain an encrypted string, not a plain array.
            assert isinstance(raw_python, str)
            assert raw_python.startswith("enc:v1:")

            # get_consultation should decrypt transparently.
            session = await get_consultation(db_conn, cid)
            assert session is not None
            msgs = session["messages"]
            assert len(msgs) == 2
            assert msgs[0]["content"] == "I need help with harassment."
            assert msgs[1]["content"] == "I understand."
            assert msgs[1]["mode"] == "personal"
        finally:
            _fernet.cache_clear()

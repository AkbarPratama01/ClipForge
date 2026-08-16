"""Fernet token encryption (§10 encrypted token storage)."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

import app.core.crypto as crypto


@pytest.fixture(autouse=True)
def _fresh_fernet(monkeypatch):
    monkeypatch.setattr(crypto, "_fernet", None)
    yield


def test_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(crypto.settings, "token_encryption_key", Fernet.generate_key().decode())
    secret = '{"refresh_token": "abc123", "token": "xyz"}'
    encrypted = crypto.encrypt_token(secret)
    assert encrypted != secret
    assert crypto.decrypt_token(encrypted) == secret


def test_wrong_key_fails(monkeypatch) -> None:
    monkeypatch.setattr(crypto.settings, "token_encryption_key", Fernet.generate_key().decode())
    encrypted = crypto.encrypt_token("top-secret")

    monkeypatch.setattr(crypto.settings, "token_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        crypto.decrypt_token(encrypted)


def test_ephemeral_key_without_setting(monkeypatch) -> None:
    monkeypatch.setattr(crypto.settings, "token_encryption_key", None)
    encrypted = crypto.encrypt_token("dev-secret")
    assert crypto.decrypt_token(encrypted) == "dev-secret"

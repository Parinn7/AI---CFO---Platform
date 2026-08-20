"""Unit tests for password hashing and JWT helpers — no DB or HTTP needed."""

from datetime import timedelta

from app.auth.security import (
    create_access_token,
    create_password_reset_token,
    decode_access_token,
    decode_password_reset_token,
    hash_password,
    password_fingerprint,
    verify_password,
)


def test_hash_is_not_plaintext_and_verifies():
    hashed = hash_password("s3cret-passphrase")
    assert hashed != "s3cret-passphrase"
    assert verify_password("s3cret-passphrase", hashed) is True


def test_verify_rejects_wrong_password():
    hashed = hash_password("correct horse")
    assert verify_password("wrong horse", hashed) is False


def test_hash_is_salted_unique_per_call():
    assert hash_password("same") != hash_password("same")


def test_verify_handles_garbage_hash_without_raising():
    assert verify_password("anything", "not-a-real-hash") is False


def test_token_round_trip():
    token = create_access_token(subject="user-123")
    assert decode_access_token(token) == "user-123"


def test_expired_token_returns_none():
    token = create_access_token(subject="user-123", expires_delta=timedelta(seconds=-1))
    assert decode_access_token(token) is None


def test_tampered_token_returns_none():
    token = create_access_token(subject="user-123")
    assert decode_access_token(token + "tampered") is None


# --- password reset tokens (task 2.4) ---


def test_reset_token_round_trip():
    pwh = hash_password("current-pw")
    token = create_password_reset_token("user-123", pwh)
    decoded = decode_password_reset_token(token)
    assert decoded == ("user-123", password_fingerprint(pwh))


def test_expired_reset_token_returns_none():
    pwh = hash_password("current-pw")
    token = create_password_reset_token("u", pwh, expires_delta=timedelta(seconds=-1))
    assert decode_password_reset_token(token) is None


def test_access_token_is_not_accepted_as_reset_token():
    """A session token must never be usable to reset a password."""
    token = create_access_token(subject="user-123")
    assert decode_password_reset_token(token) is None


def test_reset_token_is_not_accepted_as_access_token():
    """A reset token must never be usable as a session token."""
    token = create_password_reset_token("user-123", hash_password("pw"))
    assert decode_access_token(token) is None


def test_fingerprint_changes_when_hash_changes():
    assert password_fingerprint(hash_password("a")) != password_fingerprint(
        hash_password("b")
    )

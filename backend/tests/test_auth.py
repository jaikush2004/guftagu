from datetime import datetime, timedelta, timezone

import jwt

import auth


def test_password_hash_and_verify():
    hashed = auth.hash_password("secret123")
    assert hashed != "secret123"  # password seedha save nahi hota
    assert auth.verify_password("secret123", hashed)
    assert not auth.verify_password("galat-password", hashed)


def test_same_password_gives_different_hashes():
    # bcrypt har baar random "namak" milata hai
    assert auth.hash_password("secret123") != auth.hash_password("secret123")


def test_token_roundtrip():
    token = auth.create_token("jai")
    assert auth.decode_token(token) == "jai"


def test_garbage_token_is_rejected():
    assert auth.decode_token("yeh-token-nahi-hai") is None
    assert auth.decode_token("") is None


def test_expired_token_is_rejected():
    expired = jwt.encode(
        {"sub": "jai", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        auth.SECRET_KEY,
        algorithm=auth.ALGORITHM,
    )
    assert auth.decode_token(expired) is None


def test_token_signed_with_wrong_key_is_rejected():
    fake = jwt.encode(
        {"sub": "jai", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "x" * 40,
        algorithm=auth.ALGORITHM,
    )
    assert auth.decode_token(fake) is None
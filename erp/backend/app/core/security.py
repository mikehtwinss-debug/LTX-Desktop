"""Password hashing (argon2id) and JWT access tokens."""

from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError

_ALGORITHM = "HS256"
_hasher = PasswordHasher()
# Verified when the username is unknown so that response time does not reveal which accounts exist.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_dummy_password(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = utcnow()
    claims = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(claims, settings.secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> int:
    """Return the user id of a valid token; raise a 401 `AppError` otherwise."""
    try:
        claims = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        return int(claims["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise AppError("TOKEN_EXPIRED", "Oturum süreniz doldu. Lütfen tekrar giriş yapın.", 401) from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AppError("INVALID_TOKEN", "Oturum bilgisi geçersiz. Lütfen tekrar giriş yapın.", 401) from exc

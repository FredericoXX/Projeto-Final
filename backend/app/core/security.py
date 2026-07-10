"""Password hashing and JWT helpers, shared by the auth and users modules."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.exceptions import AuthenticationError

# PasswordHasher usa Argon2id por omissão (recomendado atualmente para
# hashing de passwords, resistente a ataques com GPU/ASIC).
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(subject: str) -> str:
    # O "sub" do JWT é sempre o id do utilizador (nunca o email ou o role),
    # para que o token continue válido mesmo que esses campos sejam alterados.
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    # Qualquer falha de assinatura, formato ou expiração é tratada da mesma
    # forma: erro de autenticação genérico, sem detalhes sobre a causa.
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        msg = "Invalid or expired authentication token."
        raise AuthenticationError(msg) from exc

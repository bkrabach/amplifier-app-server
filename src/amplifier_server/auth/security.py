"""Security utilities for password hashing and token generation."""

import hashlib
import secrets
from datetime import datetime, timedelta

import bcrypt
import jwt

# JWT config (loaded from server config)
JWT_SECRET: str | None = None  # Set at runtime
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 15
REFRESH_TOKEN_DAYS = 30


def init_security(secret: str) -> None:
    """Initialize security with JWT secret."""
    global JWT_SECRET
    JWT_SECRET = secret


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str, username: str, role: str) -> str:
    """Create JWT access token."""
    if JWT_SECRET is None:
        raise RuntimeError("JWT secret not initialized. Call init_security() first.")

    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRY_MINUTES),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate JWT. Raises on invalid/expired."""
    if JWT_SECRET is None:
        raise RuntimeError("JWT secret not initialized. Call init_security() first.")

    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def generate_refresh_token() -> str:
    """Generate random refresh token."""
    return secrets.token_urlsafe(48)


def generate_api_key(user_id: str) -> tuple[str, str, str]:
    """Generate API key.

    Returns: (full_key, key_hash, prefix)
    """
    random_part = secrets.token_urlsafe(36)  # 48 chars
    full_key = f"cortex_{user_id}_{random_part}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    prefix = full_key[:16]  # "cortex_user123_a"
    return full_key, key_hash, prefix


def hash_token(token: str) -> str:
    """Hash token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()

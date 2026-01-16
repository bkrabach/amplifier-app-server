"""Authentication and user models."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class UserRole(str, Enum):
    """User roles."""

    ADMIN = "admin"
    USER = "user"


class User(BaseModel):
    """User account."""

    id: str
    username: str
    email: str | None = None
    password_hash: str
    role: UserRole = UserRole.USER
    created_at: datetime
    last_login: datetime | None = None
    is_active: bool = True


class APIKey(BaseModel):
    """Device API key."""

    id: str
    user_id: str
    key_hash: str
    prefix: str  # First 8 chars for display
    name: str  # "Windows Desktop", "Android Phone"
    created_at: datetime
    last_used: datetime | None = None
    expires_at: datetime | None = None
    is_active: bool = True


class RefreshToken(BaseModel):
    """JWT refresh token."""

    id: str
    user_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked: bool = False


# Request/Response models


class RegisterRequest(BaseModel):
    """Request to register a new user."""

    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    """Request to login."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """Response from successful login."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """Request to refresh access token."""

    refresh_token: str


class CreateAPIKeyRequest(BaseModel):
    """Request to create a new API key."""

    name: str
    expires_days: int | None = None


class APIKeyResponse(BaseModel):
    """Response containing API key information."""

    id: str
    key: str | None = None  # Only returned on creation
    prefix: str
    name: str
    created_at: datetime
    expires_at: datetime | None
    is_active: bool

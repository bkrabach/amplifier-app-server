"""Authentication and authorization package."""

from amplifier_server.auth.middleware import (
    get_current_user_from_jwt,
    get_user_from_api_key,
    get_websocket_user,
    require_admin,
    require_auth,
)
from amplifier_server.auth.models import (
    APIKey,
    APIKeyResponse,
    CreateAPIKeyRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshToken,
    RegisterRequest,
    User,
    UserRole,
)
from amplifier_server.auth.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    generate_refresh_token,
    hash_password,
    hash_token,
    init_security,
    verify_password,
)
from amplifier_server.auth.user_store import UserStore

__all__ = [
    # Models
    "User",
    "UserRole",
    "APIKey",
    "RefreshToken",
    "RegisterRequest",
    "LoginRequest",
    "LoginResponse",
    "RefreshRequest",
    "CreateAPIKeyRequest",
    "APIKeyResponse",
    # Security
    "init_security",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "generate_refresh_token",
    "generate_api_key",
    "hash_token",
    # Store
    "UserStore",
    # Middleware
    "get_current_user_from_jwt",
    "get_user_from_api_key",
    "require_auth",
    "require_admin",
    "get_websocket_user",
]

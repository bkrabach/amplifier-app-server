"""Authentication middleware for FastAPI."""

import logging

from fastapi import Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from amplifier_server.auth.models import User
from amplifier_server.auth.security import decode_access_token
from amplifier_server.auth.user_store import UserStore

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Module-level storage for injected user store
_user_store: UserStore | None = None


def inject_user_store(user_store: UserStore) -> None:
    """Inject user store into this module."""
    global _user_store
    _user_store = user_store


def get_user_store() -> UserStore:
    """Dependency to get user store - injected by server."""
    if _user_store is None:
        raise RuntimeError("User store not injected")
    return _user_store


async def get_current_user_from_jwt(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    user_store: UserStore = Depends(get_user_store),
) -> User | None:
    """Extract user from JWT token.

    Returns None if no credentials or invalid token.
    Does not raise exceptions - used for optional auth.
    """
    if not credentials:
        return None

    try:
        payload = decode_access_token(credentials.credentials)
        user = await user_store.get_user(payload["sub"])
        if user and user.is_active:
            return user
    except Exception as e:
        logger.debug(f"JWT validation failed: {e}")
        pass

    return None


async def get_user_from_api_key(
    api_key: str | None = Header(None, alias="X-API-Key"),
    user_store: UserStore = Depends(get_user_store),
) -> User | None:
    """Extract user from API key.

    Returns None if no API key or invalid key.
    Does not raise exceptions - used for optional auth.
    """
    if not api_key:
        return None

    try:
        user = await user_store.get_user_by_api_key(api_key)
        if user and user.is_active:
            return user
    except Exception as e:
        logger.debug(f"API key validation failed: {e}")
        pass

    return None


async def require_auth(
    jwt_user: User | None = Depends(get_current_user_from_jwt),
    api_user: User | None = Depends(get_user_from_api_key),
) -> User:
    """Require authentication (JWT or API key).

    Raises HTTPException if no valid authentication provided.
    """
    user = jwt_user or api_user
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(user: User = Depends(require_auth)) -> User:
    """Require admin role.

    Raises HTTPException if user is not an admin.
    """
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def get_websocket_user(
    token: str = Query(...),
    user_store: UserStore = Depends(get_user_store),
) -> User:
    """Get user from WebSocket token (query param).

    Used for WebSocket connections where headers are limited.
    Raises HTTPException if token is invalid.
    """
    try:
        payload = decode_access_token(token)
        user = await user_store.get_user(payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Invalid user")
        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

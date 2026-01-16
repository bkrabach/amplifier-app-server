"""Admin API endpoints for user and API key management."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from amplifier_server.auth import (
    APIKeyResponse,
    CreateAPIKeyRequest,
    User,
    UserRole,
    generate_api_key,
    hash_password,
    require_admin,
)
from amplifier_server.auth.models import RegisterRequest
from amplifier_server.auth.user_store import UserStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

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


# User Management


@router.get("/users")
async def list_users(
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """List all users (admin only)."""
    users = await user_store.list_users()

    return {
        "count": len(users),
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role.value,
                "created_at": u.created_at.isoformat(),
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "is_active": u.is_active,
            }
            for u in users
        ],
    }


@router.post("/users")
async def create_user(
    request: RegisterRequest,
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """Create a new user (admin only)."""
    password_hash = hash_password(request.password)

    try:
        user = await user_store.create_user(
            username=request.username,
            password_hash=password_hash,
            email=request.email,
            role=UserRole.USER,
        )

        logger.info(f"Admin {admin.username} created user: {user.username}")

        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "created_at": user.created_at.isoformat(),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """Get user details (admin only)."""
    user = await user_store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "created_at": user.created_at.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "is_active": user.is_active,
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    email: str | None = None,
    is_active: bool | None = None,
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """Update user (admin only)."""
    user = await user_store.update_user(
        user_id=user_id,
        email=email,
        is_active=is_active,
    )

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(f"Admin {admin.username} updated user: {user.username}")

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
    }


@router.delete("/users/{user_id}")
async def disable_user(
    user_id: str,
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """Disable a user (soft delete, admin only)."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot disable yourself")

    user = await user_store.update_user(user_id=user_id, is_active=False)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Revoke all tokens
    await user_store.revoke_user_tokens(user_id)

    logger.info(f"Admin {admin.username} disabled user: {user.username}")

    return {"status": "disabled", "user_id": user_id, "username": user.username}


# API Key Management


@router.get("/users/{user_id}/api-keys")
async def list_api_keys(
    user_id: str,
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """List API keys for a user (admin only)."""
    keys = await user_store.list_api_keys(user_id)

    return {
        "count": len(keys),
        "keys": [
            {
                "id": k.id,
                "prefix": k.prefix,
                "name": k.name,
                "created_at": k.created_at.isoformat(),
                "last_used": k.last_used.isoformat() if k.last_used else None,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "is_active": k.is_active,
            }
            for k in keys
        ],
    }


@router.post("/users/{user_id}/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    user_id: str,
    request: CreateAPIKeyRequest,
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> APIKeyResponse:
    """Generate a new API key for a user (admin only).

    WARNING: The full API key is only returned once. Store it securely.
    """
    # Verify user exists
    user = await user_store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Generate API key
    full_key, key_hash, prefix = generate_api_key(user_id)

    # Calculate expiration
    expires_at = None
    if request.expires_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_days)

    # Store API key
    api_key = await user_store.create_api_key(
        user_id=user_id,
        key_hash=key_hash,
        prefix=prefix,
        name=request.name,
        expires_at=expires_at,
    )

    logger.info(f"Admin {admin.username} created API key '{request.name}' for user {user.username}")

    return APIKeyResponse(
        id=api_key.id,
        key=full_key,  # Only returned on creation!
        prefix=api_key.prefix,
        name=api_key.name,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
        is_active=api_key.is_active,
    )


@router.delete("/users/{user_id}/api-keys/{key_id}")
async def revoke_api_key(
    user_id: str,
    key_id: str,
    admin: User = Depends(require_admin),
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """Revoke an API key (admin only)."""
    await user_store.revoke_api_key(key_id)

    logger.info(f"Admin {admin.username} revoked API key {key_id}")

    return {"status": "revoked", "key_id": key_id}

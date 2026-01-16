"""Authentication API endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from amplifier_server.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    User,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from amplifier_server.auth.security import JWT_EXPIRY_MINUTES
from amplifier_server.auth.user_store import UserStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

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


async def is_bootstrap_mode(user_store: UserStore = Depends(get_user_store)) -> bool:
    """Check if we're in bootstrap mode (no users exist)."""
    count = await user_store.count_users()
    return count == 0


@router.options("/register")
@router.options("/login")
@router.options("/refresh")
@router.options("/logout")
async def auth_options():
    """Handle CORS preflight for auth endpoints."""
    return {}


@router.post("/register")
async def register(
    request: RegisterRequest,
    user_store: UserStore = Depends(get_user_store),
    admin: User | None = Depends(lambda: None),  # Will be overridden for auth check
) -> dict:
    """Register a new user.

    In bootstrap mode (no users exist), creates first admin user.
    After bootstrap, requires admin authentication.
    """
    # Check if bootstrap mode
    bootstrap = await is_bootstrap_mode(user_store)

    if not bootstrap and not admin:
        # Not bootstrap, need admin auth
        raise HTTPException(
            status_code=403,
            detail="Registration disabled. Admin access required to create users.",
        )

    # Hash password
    password_hash = hash_password(request.password)

    # First user becomes admin
    from amplifier_server.auth.models import UserRole

    role = UserRole.ADMIN if bootstrap else UserRole.USER

    try:
        user = await user_store.create_user(
            username=request.username,
            password_hash=password_hash,
            email=request.email,
            role=role,
        )

        logger.info(f"User registered: {user.username} (role={user.role}, bootstrap={bootstrap})")

        return {
            "user_id": user.id,
            "username": user.username,
            "role": user.role,
            "message": "First admin user created" if bootstrap else "User created",
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    user_store: UserStore = Depends(get_user_store),
) -> LoginResponse:
    """Login and receive JWT access token + refresh token."""
    # Get user
    user = await user_store.get_user_by_username(request.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Verify password
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Check if active
    if not user.is_active:
        raise HTTPException(status_code=401, detail="User account is disabled")

    # Update last login
    await user_store.update_last_login(user.id)

    # Create tokens
    access_token = create_access_token(user.id, user.username, user.role.value)
    refresh_token_value = generate_refresh_token()
    refresh_token_hash = hash_token(refresh_token_value)

    # Store refresh token
    await user_store.create_refresh_token(user.id, refresh_token_hash)

    logger.info(f"User logged in: {user.username}")

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token_value,
        token_type="Bearer",
        expires_in=JWT_EXPIRY_MINUTES * 60,
        username=user.username,
        role=user.role.value,
    )


@router.post("/refresh")
async def refresh(
    request: RefreshRequest,
    user_store: UserStore = Depends(get_user_store),
) -> LoginResponse:
    """Refresh access token using refresh token."""
    # Get refresh token
    refresh_token = await user_store.get_refresh_token(request.refresh_token)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Check if revoked
    if refresh_token.revoked:
        raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    # Check if expired
    if refresh_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh token has expired")

    # Get user
    user = await user_store.get_user(refresh_token.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Create new access token
    access_token = create_access_token(user.id, user.username, user.role.value)

    logger.debug(f"Token refreshed for user: {user.username}")

    return LoginResponse(
        access_token=access_token,
        refresh_token=request.refresh_token,  # Return same refresh token
        token_type="Bearer",
        expires_in=JWT_EXPIRY_MINUTES * 60,
    )


@router.post("/logout")
async def logout(
    request: RefreshRequest,
    user_store: UserStore = Depends(get_user_store),
) -> dict:
    """Logout by revoking refresh token."""
    try:
        await user_store.revoke_refresh_token(request.refresh_token)
        logger.info("User logged out")
        return {"status": "logged_out"}
    except Exception as e:
        logger.error(f"Logout error: {e}")
        # Don't fail on logout
        return {"status": "ok"}

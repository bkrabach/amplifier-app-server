"""Chat API for Cortex Core interaction."""

import logging
from contextlib import suppress

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from amplifier_server.auth.user_store import UserStore
from amplifier_server.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Injected managers
_session_manager: SessionManager | None = None
_user_store: UserStore | None = None


def inject_managers(session_manager: SessionManager, user_store: UserStore) -> None:
    """Inject session manager and user store."""
    global _session_manager, _user_store
    _session_manager = session_manager
    _user_store = user_store


@router.websocket("/cortex")
async def chat_cortex_core(
    websocket: WebSocket,
    token: str = Query(...),  # JWT in query param
):
    """WebSocket endpoint for chatting with Cortex Core. Requires JWT authentication.

    Connects to the long-running cortex-core session and enables
    conversational interaction.
    """
    # Validate JWT BEFORE accepting
    if not _user_store:
        await websocket.close(code=1011, reason="Server not initialized")
        return

    try:
        from amplifier_server.auth.security import decode_access_token

        payload = decode_access_token(token)
        user = await _user_store.get_user(payload["sub"])
        if not user or not user.is_active:
            await websocket.close(code=1008, reason="Invalid user")
            return
    except Exception as e:
        logger.error(f"JWT validation failed: {e}")
        await websocket.close(code=1008, reason="Invalid token")
        return

    await websocket.accept()

    if not _session_manager:
        await websocket.send_json({"error": "Session manager not available"})
        await websocket.close()
        return

    try:
        # Use user's cortex-core session (not global)
        core_id = f"cortex-core-{user.id}"

        logger.info(f"Chat connection established to Cortex Core for user {user.id}")

        # Ensure user's cortex core session exists
        try:
            await _session_manager.get_session(core_id)
        except Exception:
            # Create user's cortex-core session if it doesn't exist
            from pathlib import Path

            bundle_path = Path(__file__).parent.parent.parent.parent / "bundles" / "cortex-core.md"
            if bundle_path.exists():
                await _session_manager.create_session(
                    bundle=str(bundle_path),
                    session_id=core_id,
                )
                logger.info(f"Created cortex-core session for user {user.id}")

        # Chat loop
        while True:
            # Receive message from user
            data = await websocket.receive_json()
            message = data.get("message", "")

            if not message:
                continue

            logger.info(f"User {user.username} message: {message[:100]}")

            # Execute in Core session
            try:
                response = await _session_manager.execute(
                    session_id=core_id,
                    prompt=message,
                )

                # Send response back
                await websocket.send_json(
                    {
                        "response": response,
                        "session_id": core_id,
                    }
                )

            except Exception as e:
                logger.error(f"Core execution error: {e}")
                await websocket.send_json({"error": str(e)})

    except WebSocketDisconnect:
        logger.info(f"Chat connection closed for user {user.id}")
    except Exception as e:
        logger.error(f"Chat error: {e}")
        with suppress(Exception):
            await websocket.close()

"""WebSocket endpoints for real-time communication."""

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from amplifier_server.auth.user_store import UserStore
from amplifier_server.device_manager import DeviceManager
from amplifier_server.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# These will be injected by the server
_session_manager: SessionManager | None = None
_device_manager: DeviceManager | None = None
_user_store: UserStore | None = None


def inject_managers(
    session_manager: SessionManager,
    device_manager: DeviceManager,
    user_store: UserStore,
) -> None:
    """Inject managers into the WebSocket module."""
    global _session_manager, _device_manager, _user_store
    _session_manager = session_manager
    _device_manager = device_manager
    _user_store = user_store


@router.websocket("/ws/device/{device_id}")
async def device_websocket(
    websocket: WebSocket,
    device_id: str,
    api_key: str = Query(...),  # Required API key in query
    device_name: str = Query(default=None),
    platform: str = Query(default="unknown"),
):
    """WebSocket endpoint for device connections. Requires API key authentication.

    Devices (Windows clients, mobile apps, etc.) connect here to:
    - Receive push notifications
    - Send notifications for ingestion
    - Send status updates
    """
    # Validate API key BEFORE accepting connection
    if not _user_store:
        await websocket.close(code=1011, reason="Server not initialized")
        return

    try:
        user = await _user_store.get_user_by_api_key(api_key)
        if not user or not user.is_active:
            await websocket.close(code=1008, reason="Invalid API key")
            return
    except Exception as e:
        logger.error(f"API key validation failed: {e}")
        await websocket.close(code=1008, reason="Authentication failed")
        return

    if not _device_manager:
        await websocket.close(code=1011, reason="Server not initialized")
        return

    # Accept connection for authenticated user
    logger.info(f"Device {device_id} authenticated for user {user.id}")

    await _device_manager.connect(
        websocket=websocket,
        device_id=device_id,
        device_name=device_name,
        platform=platform,
        capabilities=["notifications"],
    )

    try:
        await _device_manager.listen(websocket, device_id)
    except WebSocketDisconnect:
        logger.info(f"Device {device_id} disconnected")
    finally:
        await _device_manager.disconnect(device_id)


@router.websocket("/ws/chat/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str,
):
    """WebSocket endpoint for interactive chat with a session.

    Provides real-time bidirectional communication with an Amplifier session.
    """
    if not _session_manager:
        await websocket.close(code=1011, reason="Server not initialized")
        return

    # Verify session exists
    try:
        await _session_manager.get_session(session_id)
    except Exception:
        await websocket.close(code=1008, reason=f"Session not found: {session_id}")
        return

    await websocket.accept()
    logger.info(f"Chat WebSocket connected to session {session_id}")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            message_type = data.get("type", "chat")

            if message_type == "chat":
                # Execute prompt and stream response
                prompt = data.get("payload", {}).get("prompt", "")

                if not prompt:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "payload": {"message": "Empty prompt"},
                        }
                    )
                    continue

                # Send acknowledgment
                await websocket.send_json(
                    {
                        "type": "ack",
                        "payload": {"status": "processing"},
                    }
                )

                try:
                    # Execute (non-streaming for now)
                    response = await _session_manager.execute(
                        session_id=session_id,
                        prompt=prompt,
                        stream=False,
                    )

                    # Send response
                    await websocket.send_json(
                        {
                            "type": "response",
                            "payload": {"content": response},
                        }
                    )

                except Exception as e:
                    logger.error(f"Execution error: {e}")
                    await websocket.send_json(
                        {
                            "type": "error",
                            "payload": {"message": str(e)},
                        }
                    )

            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "payload": {"message": f"Unknown message type: {message_type}"},
                    }
                )

    except WebSocketDisconnect:
        logger.info(f"Chat WebSocket disconnected from session {session_id}")
    except Exception as e:
        logger.error(f"Chat WebSocket error: {e}")


@router.websocket("/ws/events")
async def events_websocket(
    websocket: WebSocket,
    session_id: str = Query(default=None),
):
    """WebSocket endpoint for event streaming.

    Subscribe to events from one or all sessions.
    """
    await websocket.accept()
    logger.info(f"Events WebSocket connected (session_id={session_id})")

    # TODO: Implement event streaming via hooks
    # This would subscribe to session events and forward them

    try:
        while True:
            # Keep connection alive, forward events
            data = await websocket.receive_json()

            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Events WebSocket disconnected")

"""Log streaming API endpoints.

Provides access to recent server logs and real-time log streaming
via WebSocket for debugging and monitoring.
"""

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from amplifier_server.auth import User, require_auth
from amplifier_server.auth.user_store import UserStore
from amplifier_server.log_capture import LogEntry, get_log_buffer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["logs"])

# Module-level storage for injected dependencies
_user_store: UserStore | None = None


def inject_dependencies(user_store: UserStore | None = None) -> None:
    """Inject dependencies into this module."""
    global _user_store
    _user_store = user_store


@router.get("/logs")
async def get_logs(
    limit: int = Query(default=100, le=500, description="Max entries to return"),
    level: str | None = Query(default=None, description="Filter by level"),
    component: str | None = Query(default=None, description="Filter by component"),
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """
    Get recent log entries.

    Returns the most recent log entries from the server, with optional
    filtering by level and component. Useful for debugging without
    needing SSH access.

    Components include: notification_processor, device_manager, triage, etc.
    """
    log_buffer = get_log_buffer()
    entries = log_buffer.get_recent(limit=limit, level=level, component=component)

    return {
        "count": len(entries),
        "entries": [e.to_dict() for e in entries],
        "filters": {
            "level": level,
            "component": component,
        },
        "hint": "Use /logs/stream for real-time streaming via WebSocket",
    }


@router.websocket("/logs/stream")
async def stream_logs(
    websocket: WebSocket,
    level: str | None = Query(default=None),
    component: str | None = Query(default=None),
) -> None:
    """
    Stream logs in real-time via WebSocket.

    Connect and authenticate, then receive log entries as they occur.
    Optionally filter by level and/or component.

    Authentication: Send {"type": "auth", "api_key": "your-key"} first.

    Messages received:
    - {"type": "log", "entry": {...}} - A log entry
    - {"type": "error", "message": "..."} - Error message
    - {"type": "authenticated"} - Auth successful
    """
    await websocket.accept()

    if not _user_store:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Server not properly configured",
            }
        )
        await websocket.close(code=4000)
        return

    # Require authentication first
    try:
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
        if auth_msg.get("type") != "auth" or not auth_msg.get("api_key"):
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "First message must be auth: {type: 'auth', api_key: '...'}",
                }
            )
            await websocket.close(code=4001)
            return

        # Validate the API key using UserStore
        user = await _user_store.get_user_by_api_key(auth_msg["api_key"])
        if not user:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Invalid API key",
                }
            )
            await websocket.close(code=4003)
            return

        await websocket.send_json({"type": "authenticated", "user": user.username})
        logger.info(f"Log stream authenticated for user: {user.username}")

    except TimeoutError:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Authentication timeout",
            }
        )
        await websocket.close(code=4002)
        return

    # Set up log streaming
    log_buffer = get_log_buffer()
    queue: asyncio.Queue[LogEntry] = asyncio.Queue()

    # Filter function
    level_upper = level.upper() if level else None
    component_lower = component.lower() if component else None

    def should_include(entry: LogEntry) -> bool:
        if level_upper and entry.level != level_upper:
            return False
        if component_lower:
            entry_component = (entry.component or "").lower()
            if (
                component_lower not in entry_component
                and component_lower not in entry.logger_name.lower()
            ):
                return False
        return True

    def on_log(entry: LogEntry) -> None:
        if should_include(entry):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(entry)

    # Subscribe to log events
    unsubscribe = log_buffer.subscribe(on_log)

    try:
        # Send recent logs first (backfill)
        recent = log_buffer.get_recent(limit=50, level=level, component=component)
        for entry in recent:
            await websocket.send_json(
                {
                    "type": "log",
                    "backfill": True,
                    "entry": entry.to_dict(),
                }
            )

        # Stream new logs
        while True:
            try:
                # Check for incoming messages (ping/pong, close)
                with contextlib.suppress(TimeoutError):
                    msg = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=0.1,
                    )
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})

                # Send any queued log entries
                while not queue.empty():
                    entry = queue.get_nowait()
                    await websocket.send_json(
                        {
                            "type": "log",
                            "entry": entry.to_dict(),
                        }
                    )

                # Small sleep to prevent busy-waiting
                await asyncio.sleep(0.05)

            except WebSocketDisconnect:
                break

    finally:
        unsubscribe()
        logger.info(f"Log stream disconnected for user: {user.username}")

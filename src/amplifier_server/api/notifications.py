"""Notification API endpoints."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Depends

from amplifier_server.models import (
    IngestNotificationRequest,
    PushNotificationRequest,
    WebSocketMessage,
)
from amplifier_server.session_manager import SessionManager
from amplifier_server.device_manager import DeviceManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def get_session_manager() -> SessionManager:
    """Dependency to get session manager - injected by server."""
    raise NotImplementedError("Session manager not injected")


def get_device_manager() -> DeviceManager:
    """Dependency to get device manager - injected by server."""
    raise NotImplementedError("Device manager not injected")


@router.post("/ingest")
async def ingest_notification(
    request: IngestNotificationRequest,
    target_session: str | None = None,
    session_manager: SessionManager = Depends(get_session_manager),
) -> dict[str, Any]:
    """Ingest a notification from a client device.
    
    This endpoint receives notifications from Windows clients, mobile devices,
    or other sources and routes them to the appropriate session for processing.
    
    If target_session is specified, the notification is injected into that session.
    Otherwise, it's routed to the default "personal-hub" session if it exists.
    """
    # Format notification for injection
    notification_text = _format_notification_for_context(request)
    
    # Determine target session
    sessions = await session_manager.list_sessions()
    
    if target_session:
        session_id = target_session
    elif sessions:
        # Use first available session (could be smarter about this)
        session_id = sessions[0].session_id
    else:
        # No sessions available - log and return
        logger.warning(f"No sessions available for notification from {request.device_id}")
        return {
            "status": "queued",
            "message": "No active sessions - notification logged",
            "device_id": request.device_id,
        }
    
    try:
        # Inject into session as a user message
        await session_manager.inject_context(
            session_id=session_id,
            content=notification_text,
            role="user",
        )
        
        logger.info(
            f"Injected notification from {request.device_id}/{request.app_id} "
            f"into session {session_id}"
        )
        
        return {
            "status": "ingested",
            "session_id": session_id,
            "device_id": request.device_id,
            "app_id": request.app_id,
        }
        
    except Exception as e:
        logger.error(f"Failed to ingest notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/push")
async def push_notification(
    request: PushNotificationRequest,
    device_manager: DeviceManager = Depends(get_device_manager),
) -> dict[str, Any]:
    """Push a notification to connected device(s).
    
    This endpoint allows the AI session to send notifications back to
    the user's devices.
    """
    results = await device_manager.push_notification(request)
    
    sent_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    return {
        "status": "sent" if sent_count > 0 else "no_devices",
        "sent_count": sent_count,
        "total_devices": total_count,
        "results": results,
    }


def _format_notification_for_context(request: IngestNotificationRequest) -> str:
    """Format a notification for injection into session context."""
    parts = [
        f"[NOTIFICATION from {request.device_id}]",
        f"App: {request.app_id}",
        f"Time: {request.timestamp}",
    ]
    
    if request.sender:
        parts.append(f"From: {request.sender}")
    
    if request.conversation_hint:
        parts.append(f"Conversation: {request.conversation_hint}")
    
    parts.append(f"Title: {request.title}")
    
    if request.body:
        parts.append(f"Body: {request.body}")
    
    parts.append("[END NOTIFICATION]")
    
    return "\n".join(parts)

"""Notification API endpoints."""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Depends, Query

from amplifier_server.models import (
    IngestNotificationRequest,
    PushNotificationRequest,
    WebSocketMessage,
)
from amplifier_server.session_manager import SessionManager
from amplifier_server.device_manager import DeviceManager
from amplifier_server.notification_store import NotificationStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Module-level storage for injected managers
_session_manager: SessionManager | None = None
_device_manager: DeviceManager | None = None
_notification_store: NotificationStore | None = None


def inject_managers(
    session_manager: SessionManager,
    device_manager: DeviceManager,
    notification_store: NotificationStore | None = None,
) -> None:
    """Inject managers into this module."""
    global _session_manager, _device_manager, _notification_store
    _session_manager = session_manager
    _device_manager = device_manager
    _notification_store = notification_store


def get_session_manager() -> SessionManager:
    """Dependency to get session manager - injected by server."""
    if _session_manager is None:
        raise NotImplementedError("Session manager not injected")
    return _session_manager


def get_device_manager() -> DeviceManager:
    """Dependency to get device manager - injected by server."""
    if _device_manager is None:
        raise NotImplementedError("Device manager not injected")
    return _device_manager


def get_notification_store() -> NotificationStore:
    """Dependency to get notification store - injected by server."""
    if _notification_store is None:
        raise NotImplementedError("Notification store not injected")
    return _notification_store


@router.post("/ingest")
async def ingest_notification(
    request: IngestNotificationRequest,
    target_session: str | None = None,
    session_manager: SessionManager = Depends(get_session_manager),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> dict[str, Any]:
    """Ingest a notification from a client device.
    
    This endpoint receives notifications from Windows clients, mobile devices,
    or other sources. Notifications are stored and optionally routed to a session.
    """
    # Store the notification
    notification_id = await notification_store.store(request)
    
    logger.info(
        f"Stored notification {notification_id} from {request.device_id}/{request.app_id}: "
        f"{request.title[:50]}..."
    )
    
    return {
        "status": "stored",
        "notification_id": notification_id,
        "device_id": request.device_id,
        "app_id": request.app_id,
    }


@router.get("/recent")
async def get_recent_notifications(
    limit: int = Query(default=50, le=500),
    device_id: str | None = None,
    app_id: str | None = None,
    hours: int = Query(default=24, le=168),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> dict[str, Any]:
    """Get recent notifications with optional filters."""
    since = datetime.utcnow() - timedelta(hours=hours)
    
    notifications = await notification_store.get_recent(
        limit=limit,
        device_id=device_id,
        app_id=app_id,
        since=since,
    )
    
    return {
        "count": len(notifications),
        "since": since.isoformat(),
        "notifications": notifications,
    }


@router.get("/stats")
async def get_notification_stats(
    hours: int = Query(default=24, le=168),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> dict[str, Any]:
    """Get notification statistics."""
    since = datetime.utcnow() - timedelta(hours=hours)
    return await notification_store.get_summary_stats(since=since)


@router.get("/digest")
async def get_notification_digest(
    hours: int = Query(default=1, le=24),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> dict[str, Any]:
    """Generate a digest of recent notifications."""
    since = datetime.utcnow() - timedelta(hours=hours)
    digest = await notification_store.generate_digest(since=since)
    
    return {
        "since": since.isoformat(),
        "digest": digest,
    }


@router.get("/{notification_id}")
async def get_notification(
    notification_id: int,
    notification_store: NotificationStore = Depends(get_notification_store),
) -> dict[str, Any]:
    """Get a specific notification by ID."""
    notification = await notification_store.get_by_id(notification_id)
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return notification


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

"""Notification API endpoints."""

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from amplifier_server.auth import User, require_auth
from amplifier_server.device_manager import DeviceManager
from amplifier_server.models import (
    IngestNotificationRequest,
    PushNotificationRequest,
)
from amplifier_server.notification_processor import NotificationProcessor
from amplifier_server.notification_store import NotificationStore
from amplifier_server.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Module-level storage for injected managers
_session_manager: SessionManager | None = None
_device_manager: DeviceManager | None = None
_notification_store: NotificationStore | None = None
_notification_processor: NotificationProcessor | None = None


def inject_managers(
    session_manager: SessionManager,
    device_manager: DeviceManager,
    notification_store: NotificationStore | None = None,
    notification_processor: NotificationProcessor | None = None,
) -> None:
    """Inject managers into this module."""
    global _session_manager, _device_manager, _notification_store, _notification_processor
    _session_manager = session_manager
    _device_manager = device_manager
    _notification_store = notification_store
    _notification_processor = notification_processor


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


def get_notification_processor() -> NotificationProcessor | None:
    """Dependency to get notification processor - may be None."""
    return _notification_processor


@router.post("/ingest")
async def ingest_notification(
    request: IngestNotificationRequest,
    user: User = Depends(require_auth),
    target_session: str | None = None,
    session_manager: SessionManager = Depends(get_session_manager),
    notification_store: NotificationStore = Depends(get_notification_store),
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Ingest a notification from a client device.

    This endpoint receives notifications from Windows clients, mobile devices,
    or other sources. Notifications are stored and queued for AI processing.
    """
    # Debug: Log raw notification data
    logger.info(
        f"[RAW NOTIFICATION] device={request.device_id} app={request.app_id}\n"
        f"  title: {repr(request.title)}\n"
        f"  body: {repr(request.body)}\n"
        f"  sender: {repr(request.sender)}\n"
        f"  conversation_hint: {repr(request.conversation_hint)}\n"
        f"  raw: {request.raw}"
    )

    # Store the notification
    notification_id = await notification_store.store(request)

    logger.info(
        f"Stored notification {notification_id} from {request.device_id}/{request.app_id}: "
        f"{request.title[:50] if request.title else '(empty)'}..."
    )

    # Enqueue for processing
    if processor:
        await processor.enqueue(notification_id)

    return {
        "status": "stored",
        "notification_id": notification_id,
        "device_id": request.device_id,
        "app_id": request.app_id,
    }


@router.get("/recent")
async def get_recent_notifications(
    user: User = Depends(require_auth),
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
    user: User = Depends(require_auth),
    hours: int = Query(default=24, le=168),
    notification_store: NotificationStore = Depends(get_notification_store),
) -> dict[str, Any]:
    """Get notification statistics."""
    since = datetime.utcnow() - timedelta(hours=hours)
    return await notification_store.get_summary_stats(since=since)


@router.get("/digest")
async def get_notification_digest(
    user: User = Depends(require_auth),
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
    user: User = Depends(require_auth),
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
    user: User = Depends(require_auth),
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


# --- Policy Management Endpoints ---


@router.get("/config")
async def get_processor_config(
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Get current notification processing configuration."""
    if not processor:
        return {"error": "Processor not available"}

    config = processor.config
    return {
        "vip_senders": config.vip_senders,
        "urgent_keywords": config.urgent_keywords,
        "action_keywords": config.action_keywords,
        "priority_apps": config.priority_apps,
        "low_priority_apps": config.low_priority_apps,
        "push_threshold": config.push_threshold,
        "user_aliases": config.user_aliases,
    }


@router.post("/vip/add")
async def add_vip_sender(
    sender: str,
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Add a VIP sender (always high priority)."""
    if not processor:
        return {"error": "Processor not available"}

    processor.add_vip(sender)
    return {"status": "added", "sender": sender, "vip_list": processor.config.vip_senders}


@router.post("/vip/remove")
async def remove_vip_sender(
    sender: str,
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Remove a VIP sender."""
    if not processor:
        return {"error": "Processor not available"}

    processor.remove_vip(sender)
    return {"status": "removed", "sender": sender, "vip_list": processor.config.vip_senders}


@router.post("/keyword/add")
async def add_keyword(
    keyword: str,
    category: str = "urgent",
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Add a keyword to watch for (urgent or action)."""
    if not processor:
        return {"error": "Processor not available"}

    processor.add_keyword(keyword, category)

    keywords = (
        processor.config.urgent_keywords
        if category == "urgent"
        else processor.config.action_keywords
    )
    return {"status": "added", "keyword": keyword, "category": category, "keywords": keywords}


# --- LLM Scoring Control ---


@router.post("/llm/enable")
async def enable_llm_scoring(
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Enable LLM-based scoring (requires Amplifier to be available)."""
    if not processor:
        return {"error": "Processor not available"}

    if not processor.llm_scorer:
        return {
            "error": "LLM scorer not initialized",
            "hint": "Amplifier may not be available or failed to initialize",
        }

    processor.enable_llm_scoring(True)
    return {"status": "enabled", "mode": "llm"}


@router.post("/llm/disable")
async def disable_llm_scoring(
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Disable LLM-based scoring (use heuristics only)."""
    if not processor:
        return {"error": "Processor not available"}

    processor.enable_llm_scoring(False)
    return {"status": "disabled", "mode": "heuristics"}


@router.get("/llm/status")
async def get_llm_status(
    processor: NotificationProcessor | None = Depends(get_notification_processor),
) -> dict[str, Any]:
    """Get current LLM scoring status."""
    if not processor:
        return {"error": "Processor not available"}

    return {
        "llm_available": processor.llm_scorer is not None,
        "llm_enabled": processor.use_llm,
        "mode": "llm" if processor.use_llm else "heuristics",
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

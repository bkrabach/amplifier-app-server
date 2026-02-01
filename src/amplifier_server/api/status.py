"""Server status API endpoints."""

import logging
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from amplifier_server.auth import User, require_auth
from amplifier_server.device_manager import DeviceManager
from amplifier_server.notification_processor import NotificationProcessor
from amplifier_server.notification_store import NotificationStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["status"])

# Track server start time for uptime
_server_start_time = time.time()

# Module-level storage for injected managers
_notification_store: NotificationStore | None = None
_notification_processor: NotificationProcessor | None = None
_device_manager: DeviceManager | None = None


def inject_managers(
    notification_store: NotificationStore | None = None,
    notification_processor: NotificationProcessor | None = None,
    device_manager: DeviceManager | None = None,
) -> None:
    """Inject managers into this module."""
    global _notification_store, _notification_processor, _device_manager, _server_start_time
    _notification_store = notification_store
    _notification_processor = notification_processor
    _device_manager = device_manager
    # Reset start time when managers are injected (server startup)
    _server_start_time = time.time()


class StatusResponse(BaseModel):
    """Server status response."""

    status: str
    version: str
    uptime_seconds: int
    llm_enabled: bool
    connected_devices: int
    notifications_today: int


@router.get("/status", response_model=StatusResponse)
async def get_status(user: User = Depends(require_auth)) -> StatusResponse:
    """
    Get server status and health information.

    Returns system status including uptime, connected devices,
    and notification processing statistics.
    """
    connected = 0
    today_count = 0

    if _device_manager:
        connected = len(_device_manager.list_devices(connected_only=True))

    if _notification_store:
        stats = await _notification_store.get_summary_stats()
        today_count = stats.get("today", 0)

    llm_enabled = False
    if _notification_processor:
        llm_enabled = _notification_processor.use_llm

    return StatusResponse(
        status="healthy",
        version="0.1.0",
        uptime_seconds=int(time.time() - _server_start_time),
        llm_enabled=llm_enabled,
        connected_devices=connected,
        notifications_today=today_count,
    )

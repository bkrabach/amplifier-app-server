"""Device management API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from amplifier_server.auth import User, require_auth
from amplifier_server.device_manager import DeviceManager
from amplifier_server.models import DeviceInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])

# Module-level storage for injected managers
_device_manager: DeviceManager | None = None


def inject_managers(device_manager: DeviceManager | None = None) -> None:
    """Inject managers into this module."""
    global _device_manager
    _device_manager = device_manager


@router.get("", response_model=list[DeviceInfo])
async def list_devices(
    connected_only: bool = True,
    user: User = Depends(require_auth),
) -> list[DeviceInfo]:
    """List connected devices."""
    if not _device_manager:
        raise HTTPException(status_code=503, detail="Device manager not available")
    return _device_manager.list_devices(connected_only=connected_only)


@router.get("/{device_id}", response_model=DeviceInfo | None)
async def get_device(
    device_id: str,
    user: User = Depends(require_auth),
) -> DeviceInfo | None:
    """Get information about a device."""
    if not _device_manager:
        raise HTTPException(status_code=503, detail="Device manager not available")
    return _device_manager.get_device(device_id)


@router.post("/{device_id}/ping")
async def ping_device(
    device_id: str,
    user: User = Depends(require_auth),
) -> dict:
    """
    Send a test ping to verify device connectivity.

    The device will receive a WebSocket message with type='ping'.
    Use this to verify the WebSocket connection is working before
    testing notifications.
    """
    if not _device_manager:
        raise HTTPException(status_code=503, detail="Device manager not available")

    if not _device_manager.is_connected(device_id):
        return {
            "success": False,
            "error": f"Device '{device_id}' is not connected",
            "hint": "Check /connections to see connected device_ids",
        }

    from amplifier_server.models import WebSocketMessage

    message = WebSocketMessage(
        type="ping",
        payload={"test": True, "message": "Connectivity test from /devices/{id}/ping"},
    )

    success = await _device_manager.send_to_device(device_id, message)

    return {
        "success": success,
        "device_id": device_id,
        "message_sent": message.model_dump() if success else None,
        "note": "Device should respond with type='pong' if working correctly",
    }

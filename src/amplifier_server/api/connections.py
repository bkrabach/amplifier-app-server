"""WebSocket connection status API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from amplifier_server.auth import User, require_auth
from amplifier_server.device_manager import DeviceManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["connections"])

# Module-level storage for injected managers
_device_manager: DeviceManager | None = None


def inject_managers(device_manager: DeviceManager | None = None) -> None:
    """Inject managers into this module."""
    global _device_manager
    _device_manager = device_manager


@router.get("/connections")
async def get_connections(user: User = Depends(require_auth)) -> dict[str, Any]:
    """
    Get all WebSocket connections and their status.
    
    Use this to verify device connectivity and debug connection issues.
    Shows all devices (connected and recently disconnected) with their IDs.
    """
    if not _device_manager:
        raise HTTPException(status_code=503, detail="Device manager not available")

    # Get all devices (connected and recently disconnected)
    all_devices = _device_manager.list_devices(connected_only=False)
    connected_devices = _device_manager.list_devices(connected_only=True)

    connected_ids = {d.device_id for d in connected_devices}

    connections = []
    for device in all_devices:
        is_connected = device.device_id in connected_ids
        connections.append({
            "device_id": device.device_id,
            "device_name": device.device_name,
            "platform": device.platform,
            "connected": is_connected,
            "connected_at": (
                device.connected_at.isoformat() if device.connected_at else None
            ),
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        })

    return {
        "total_devices": len(all_devices),
        "connected_count": len(connected_devices),
        "connections": connections,
        "troubleshooting": {
            "no_devices": "Connect via WebSocket to /ws/device/{your-device-id}",
            "device_not_receiving": (
                "Ensure notification device_id matches a connected device_id"
            ),
            "wrong_device_id": (
                "The device_id in requests must match your WebSocket connection"
            ),
        },
    }

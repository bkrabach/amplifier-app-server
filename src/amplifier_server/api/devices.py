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

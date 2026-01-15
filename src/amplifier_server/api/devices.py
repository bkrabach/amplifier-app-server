"""Device management API endpoints."""

import logging

from fastapi import APIRouter, Depends

from amplifier_server.device_manager import DeviceManager
from amplifier_server.models import DeviceInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devices", tags=["devices"])


def get_device_manager() -> DeviceManager:
    """Dependency to get device manager - injected by server."""
    raise NotImplementedError("Device manager not injected")


@router.get("", response_model=list[DeviceInfo])
async def list_devices(
    connected_only: bool = True,
    manager: DeviceManager = Depends(get_device_manager),
) -> list[DeviceInfo]:
    """List connected devices."""
    return manager.list_devices(connected_only=connected_only)


@router.get("/{device_id}", response_model=DeviceInfo | None)
async def get_device(
    device_id: str,
    manager: DeviceManager = Depends(get_device_manager),
) -> DeviceInfo | None:
    """Get information about a device."""
    return manager.get_device(device_id)

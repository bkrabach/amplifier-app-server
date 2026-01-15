"""Device manager for tracking connected client devices."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from amplifier_server.models import DeviceInfo, PushNotificationRequest, WebSocketMessage

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages connected client devices and push notifications.

    Tracks WebSocket connections from devices (Windows clients, web browsers, etc.)
    and routes notifications to them.
    """

    def __init__(self):
        # Active connections: device_id -> WebSocket
        self._connections: dict[str, WebSocket] = {}
        self._device_info: dict[str, DeviceInfo] = {}

        # Callbacks for incoming messages
        self._message_handlers: list[Callable] = []

    async def connect(
        self,
        websocket: WebSocket,
        device_id: str,
        device_name: str | None = None,
        platform: str = "unknown",
        capabilities: list[str] | None = None,
    ) -> None:
        """Register a new device connection.

        Args:
            websocket: The WebSocket connection
            device_id: Unique device identifier
            device_name: Human-readable device name
            platform: Platform type (windows, web, mobile)
            capabilities: List of supported capabilities
        """
        await websocket.accept()

        self._connections[device_id] = websocket
        self._device_info[device_id] = DeviceInfo(
            device_id=device_id,
            device_name=device_name,
            platform=platform,
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            capabilities=capabilities or [],
        )

        logger.info(f"Device connected: {device_id} ({platform})")

    async def disconnect(self, device_id: str) -> None:
        """Remove a device connection."""
        self._connections.pop(device_id, None)
        if device_id in self._device_info:
            self._device_info[device_id].last_seen = datetime.now()

        logger.info(f"Device disconnected: {device_id}")

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """Get info about a device."""
        return self._device_info.get(device_id)

    def list_devices(self, connected_only: bool = True) -> list[DeviceInfo]:
        """List devices."""
        if connected_only:
            return [
                info
                for device_id, info in self._device_info.items()
                if device_id in self._connections
            ]
        return list(self._device_info.values())

    def is_connected(self, device_id: str) -> bool:
        """Check if a device is connected."""
        return device_id in self._connections

    async def send_to_device(
        self,
        device_id: str,
        message: WebSocketMessage,
    ) -> bool:
        """Send a message to a specific device.

        Args:
            device_id: Target device
            message: Message to send

        Returns:
            True if sent, False if device not connected
        """
        websocket = self._connections.get(device_id)
        if not websocket:
            logger.warning(f"Device not connected: {device_id}")
            return False

        try:
            await websocket.send_json(message.model_dump())
            if device_id in self._device_info:
                self._device_info[device_id].last_seen = datetime.now()
            return True
        except Exception as e:
            logger.error(f"Failed to send to device {device_id}: {e}")
            await self.disconnect(device_id)
            return False

    async def broadcast(
        self,
        message: WebSocketMessage,
        exclude: list[str] | None = None,
    ) -> dict[str, bool]:
        """Broadcast a message to all connected devices.

        Args:
            message: Message to broadcast
            exclude: Device IDs to exclude

        Returns:
            Dict of device_id -> success
        """
        exclude = exclude or []
        results = {}

        for device_id in list(self._connections.keys()):
            if device_id not in exclude:
                results[device_id] = await self.send_to_device(device_id, message)

        return results

    async def push_notification(
        self,
        notification: PushNotificationRequest,
    ) -> dict[str, bool]:
        """Push a notification to device(s).

        Args:
            notification: Notification to push

        Returns:
            Dict of device_id -> success
        """
        message = WebSocketMessage(
            type="notification",
            payload={
                "title": notification.title,
                "body": notification.body,
                "urgency": notification.urgency,
                "rationale": notification.rationale,
                "app_source": notification.app_source,
                "actions": notification.actions,
            },
        )

        if notification.device_id:
            # Send to specific device
            success = await self.send_to_device(notification.device_id, message)
            return {notification.device_id: success}
        else:
            # Broadcast to all
            return await self.broadcast(message)

    def on_message(self, handler: Callable) -> Callable:
        """Register a handler for incoming messages.

        Usage:
            @device_manager.on_message
            async def handle(device_id: str, message: dict):
                ...
        """
        self._message_handlers.append(handler)
        return handler

    async def handle_message(
        self,
        device_id: str,
        message: dict[str, Any],
    ) -> None:
        """Handle an incoming message from a device."""
        if device_id in self._device_info:
            self._device_info[device_id].last_seen = datetime.now()

        # Call all registered handlers
        for handler in self._message_handlers:
            try:
                await handler(device_id, message)
            except Exception as e:
                logger.error(f"Message handler error: {e}")

    async def listen(self, websocket: WebSocket, device_id: str) -> None:
        """Listen for messages from a device.

        Runs until the connection is closed.
        """
        try:
            while True:
                data = await websocket.receive_json()
                await self.handle_message(device_id, data)
        except Exception as e:
            logger.debug(f"Device {device_id} connection ended: {e}")
        finally:
            await self.disconnect(device_id)

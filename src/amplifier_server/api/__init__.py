"""API routers for Amplifier Server."""

from amplifier_server.api.chat import router as chat_router
from amplifier_server.api.devices import router as devices_router
from amplifier_server.api.notifications import router as notifications_router
from amplifier_server.api.sessions import router as sessions_router
from amplifier_server.api.websocket import router as websocket_router

__all__ = [
    "chat_router",
    "devices_router",
    "notifications_router",
    "sessions_router",
    "websocket_router",
]

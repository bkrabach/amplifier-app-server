"""Main FastAPI server for Amplifier Server."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from amplifier_server.session_manager import SessionManager
from amplifier_server.device_manager import DeviceManager
from amplifier_server.api import (
    sessions_router,
    devices_router,
    notifications_router,
    websocket_router,
)
from amplifier_server.api import sessions as sessions_api
from amplifier_server.api import devices as devices_api
from amplifier_server.api import notifications as notifications_api
from amplifier_server.api import websocket as websocket_api

logger = logging.getLogger(__name__)


class AmplifierServer:
    """Main Amplifier Server application.
    
    Hosts multiple Amplifier sessions with HTTP/WebSocket API access.
    """
    
    def __init__(
        self,
        data_dir: Path | str = "~/.amplifier-server",
        host: str = "0.0.0.0",
        port: int = 8420,
        cors_origins: list[str] | None = None,
    ):
        """Initialize the server.
        
        Args:
            data_dir: Directory for server data and session state
            host: Host to bind to
            port: Port to listen on
            cors_origins: Allowed CORS origins (None = allow all for development)
        """
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.host = host
        self.port = port
        self.cors_origins = cors_origins or ["*"]
        
        # Core managers
        self.session_manager = SessionManager(self.data_dir / "sessions")
        self.device_manager = DeviceManager()
        
        # FastAPI app
        self.app = self._create_app()
        
        # Register device message handlers
        self._setup_device_handlers()
    
    def _create_app(self) -> FastAPI:
        """Create and configure the FastAPI application."""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """Manage server lifecycle."""
            logger.info(f"Amplifier Server starting on {self.host}:{self.port}")
            logger.info(f"Data directory: {self.data_dir}")
            yield
            logger.info("Amplifier Server shutting down")
            await self.session_manager.shutdown()
        
        app = FastAPI(
            title="Amplifier Server",
            description="Always-on AI agent runtime with HTTP/WebSocket API",
            version="0.1.0",
            lifespan=lifespan,
        )
        
        # CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Inject dependencies
        self._inject_dependencies()
        
        # Register routers
        app.include_router(sessions_router)
        app.include_router(devices_router)
        app.include_router(notifications_router)
        app.include_router(websocket_router)
        
        # Root endpoint
        @app.get("/")
        async def root():
            return {
                "service": "Amplifier Server",
                "version": "0.1.0",
                "status": "running",
                "endpoints": {
                    "sessions": "/sessions",
                    "devices": "/devices",
                    "notifications": "/notifications",
                    "websocket_device": "/ws/device/{device_id}",
                    "websocket_chat": "/ws/chat/{session_id}",
                    "websocket_events": "/ws/events",
                    "docs": "/docs",
                },
            }
        
        # Health check
        @app.get("/health")
        async def health():
            sessions = await self.session_manager.list_sessions()
            devices = self.device_manager.list_devices()
            
            return {
                "status": "healthy",
                "sessions": len(sessions),
                "connected_devices": len(devices),
            }
        
        return app
    
    def _inject_dependencies(self) -> None:
        """Inject managers into API modules."""
        # Override dependency functions
        sessions_api.get_session_manager = lambda: self.session_manager
        devices_api.get_device_manager = lambda: self.device_manager
        notifications_api.get_session_manager = lambda: self.session_manager
        notifications_api.get_device_manager = lambda: self.device_manager
        
        # Inject into WebSocket module
        websocket_api.inject_managers(self.session_manager, self.device_manager)
    
    def _setup_device_handlers(self) -> None:
        """Set up handlers for device messages."""
        
        @self.device_manager.on_message
        async def handle_notification(device_id: str, message: dict[str, Any]):
            """Handle notification messages from devices."""
            if message.get("type") != "notification":
                return
            
            payload = message.get("payload", {})
            
            # Format and inject into active session
            notification_text = (
                f"[NOTIFICATION from {device_id}]\n"
                f"App: {payload.get('app_id', 'unknown')}\n"
                f"Title: {payload.get('title', '')}\n"
                f"Body: {payload.get('body', '')}\n"
                f"[END NOTIFICATION]"
            )
            
            # Inject into first available session
            sessions = await self.session_manager.list_sessions()
            if sessions:
                await self.session_manager.inject_context(
                    session_id=sessions[0].session_id,
                    content=notification_text,
                    role="user",
                )
                logger.info(f"Injected notification from {device_id}")
    
    def run(self) -> None:
        """Run the server (blocking)."""
        import uvicorn
        
        uvicorn.run(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
    
    async def run_async(self) -> None:
        """Run the server asynchronously."""
        import uvicorn
        
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()


def create_server(
    data_dir: str | Path = "~/.amplifier-server",
    host: str = "0.0.0.0",
    port: int = 8420,
    **kwargs,
) -> AmplifierServer:
    """Create an Amplifier Server instance.
    
    Args:
        data_dir: Directory for server data
        host: Host to bind to
        port: Port to listen on
        **kwargs: Additional options
        
    Returns:
        Configured AmplifierServer instance
    """
    return AmplifierServer(
        data_dir=data_dir,
        host=host,
        port=port,
        **kwargs,
    )

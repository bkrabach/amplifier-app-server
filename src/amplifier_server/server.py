"""Main FastAPI server for Amplifier Server."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from amplifier_server.api import chat as chat_api
from amplifier_server.api import (
    chat_router,
    devices_router,
    notifications_router,
    sessions_router,
    websocket_router,
)
from amplifier_server.api import devices as devices_api
from amplifier_server.api import notifications as notifications_api
from amplifier_server.api import sessions as sessions_api
from amplifier_server.api import websocket as websocket_api
from amplifier_server.device_manager import DeviceManager
from amplifier_server.llm_scorer import LLMScorer
from amplifier_server.notification_processor import NotificationProcessor, ScoringConfig
from amplifier_server.notification_store import NotificationStore
from amplifier_server.session_manager import SessionManager

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
        self.notification_store = NotificationStore(self.data_dir / "notifications.db")

        # Scoring configuration
        self.scoring_config = ScoringConfig(
            # Add your name/aliases for mention detection
            user_aliases=["Brian", "bkrabach"],
            # Add VIP senders (will be configurable via API)
            vip_senders=[],
        )

        # Notification processor with default config
        self.notification_processor = NotificationProcessor(
            notification_store=self.notification_store,
            device_manager=self.device_manager,
            config=self.scoring_config,
        )

        # LLM scorer (initialized lazily on first use)
        self.llm_scorer: LLMScorer | None = None

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

            # Initialize notification store
            await self.notification_store.initialize()

            # Start notification processor
            await self.notification_processor.start()

            # Initialize LLM scorer if Amplifier is available
            await self._init_llm_scorer()

            # Initialize Cortex Core orchestrator
            await self._init_cortex_core()

            yield

            logger.info("Amplifier Server shutting down")
            await self.notification_processor.stop()
            if self.llm_scorer:
                await self.llm_scorer.cleanup()
            await self.notification_store.close()
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
        app.include_router(chat_router)
        app.include_router(sessions_router)
        app.include_router(devices_router)
        app.include_router(notifications_router)
        app.include_router(websocket_router)

        # API root endpoint
        @app.get("/api")
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

        # Mount static files (must be last to not override API routes)
        static_dir = Path(__file__).parent.parent.parent / "static"
        if static_dir.exists():
            app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
            logger.info(f"Serving static files from {static_dir}")

        return app

    def _inject_dependencies(self) -> None:
        """Inject managers into API modules."""
        # Override dependency functions
        sessions_api.get_session_manager = lambda: self.session_manager
        devices_api.get_device_manager = lambda: self.device_manager

        # Use inject_managers for notifications (proper pattern)
        notifications_api.inject_managers(
            self.session_manager,
            self.device_manager,
            self.notification_store,
            self.notification_processor,
        )

        # Inject into WebSocket module
        websocket_api.inject_managers(self.session_manager, self.device_manager)

        # Inject into Chat module
        chat_api.inject_managers(self.session_manager)

    async def _init_llm_scorer(self) -> None:
        """Initialize the LLM scorer.

        Raises:
            RuntimeError: If LLM scorer fails to initialize (critical failure)
        """
        try:
            self.llm_scorer = LLMScorer(
                session_manager=self.session_manager,
                rules_path=self.data_dir / "config" / "attention-rules.md",
            )

            # Initialize with foundation bundle + Anthropic provider
            await self.llm_scorer.initialize()

            # Wire up to processor and enable by default
            self.notification_processor.set_llm_scorer(self.llm_scorer)
            self.notification_processor.enable_llm_scoring(True)

            logger.info("LLM scorer initialized and enabled")

        except Exception as e:
            logger.error(f"CRITICAL: LLM scorer failed to initialize: {e}")
            logger.error("Server cannot start without LLM scoring capability")
            raise RuntimeError(f"LLM scorer initialization failed: {e}") from e

    async def _init_cortex_core(self) -> None:
        """Initialize the Cortex Core orchestrator session."""
        try:
            # Load cortex-core bundle
            bundle_path = Path(__file__).parent.parent.parent / "bundles" / "cortex-core.md"

            # Create long-running Core session
            core_id = await self.session_manager.create_session(
                bundle=str(bundle_path),
                session_id="cortex-core",
            )

            logger.info(f"Cortex Core initialized: {core_id}")

        except Exception as e:
            logger.error(f"Failed to initialize Cortex Core: {e}")
            # Non-fatal - server can still run for notifications

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

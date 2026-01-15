"""Session manager for hosting multiple concurrent Amplifier sessions."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from amplifier_server.models import SessionInfo, SessionStatus

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class SessionManager:
    """Manages multiple concurrent Amplifier sessions.

    Handles session lifecycle, persistence, and execution routing.
    """

    def __init__(self, data_dir: Path | str):
        """Initialize the session manager.

        Args:
            data_dir: Directory for session state and logs
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Active sessions (in-memory)
        self._sessions: dict[str, Any] = {}  # session_id -> AmplifierSession
        self._session_info: dict[str, SessionInfo] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}

        # Bundle cache
        self._bundle_cache: dict[str, Any] = {}  # uri -> Bundle
        self._prepared_cache: dict[str, Any] = {}  # cache_key -> PreparedBundle

        # Check if Amplifier is available
        self._amplifier_available = self._check_amplifier_available()

    def _check_amplifier_available(self) -> bool:
        """Check if amplifier-foundation is available."""
        try:
            from amplifier_foundation import Bundle  # noqa: F401

            return True
        except ImportError:
            logger.warning("amplifier-foundation not available, using mock sessions")
            return False

    async def create_session(
        self,
        bundle: str,
        session_id: str | None = None,
        config: dict[str, Any] | None = None,
        provider_bundle: str | None = None,
    ) -> str:
        """Create and initialize a new session.

        Args:
            bundle: Bundle name or URI (git+https://..., file path, etc.)
            session_id: Optional custom session ID
            config: Session configuration overrides
            provider_bundle: Optional provider bundle to compose

        Returns:
            The session ID
        """
        # Generate session ID if not provided
        if session_id is None:
            session_id = f"session_{int(time.time() * 1000)}"

        if session_id in self._sessions:
            raise ValueError(f"Session already exists: {session_id}")

        logger.info(f"Creating session {session_id} with bundle: {bundle}")

        # Create session info
        info = SessionInfo(
            session_id=session_id,
            bundle=bundle,
            status=SessionStatus.INITIALIZING,
            created_at=datetime.now(),
        )
        self._session_info[session_id] = info
        self._session_locks[session_id] = asyncio.Lock()

        try:
            # Create session using Amplifier or mock
            session = await self._create_amplifier_session(
                bundle_uri=bundle,
                session_id=session_id,
                config=config or {},
                provider_bundle=provider_bundle,
            )

            self._sessions[session_id] = session
            info.status = SessionStatus.READY

            logger.info(f"Session {session_id} ready")
            return session_id

        except Exception as e:
            info.status = SessionStatus.ERROR
            info.metadata["error"] = str(e)
            logger.error(f"Failed to create session {session_id}: {e}")
            raise

    async def create_minimal_session(self, session_id: str) -> str:
        """Create a minimal session optimized for fast JSON responses.

        This creates a lightweight session with only:
        - Provider (Haiku for speed/cost)
        - Basic orchestrator
        - No tools, no hooks, minimal system prompt

        Ideal for simple scoring/classification tasks.
        """
        if session_id in self._sessions:
            raise ValueError(f"Session already exists: {session_id}")

        logger.info(f"Creating minimal session: {session_id}")

        # Create session info
        info = SessionInfo(
            session_id=session_id,
            bundle="minimal-scorer",
            status=SessionStatus.INITIALIZING,
            created_at=datetime.now(),
        )
        self._session_info[session_id] = info
        self._session_locks[session_id] = asyncio.Lock()

        try:
            session = await self._create_minimal_amplifier_session(session_id)
            self._sessions[session_id] = session
            info.status = SessionStatus.READY
            logger.info(f"Minimal session {session_id} ready")
            return session_id
        except Exception as e:
            info.status = SessionStatus.ERROR
            info.metadata["error"] = str(e)
            logger.error(f"Failed to create minimal session {session_id}: {e}")
            raise

    async def _load_bundle(self, bundle_uri: str) -> Any:
        """Load a bundle with caching."""
        if bundle_uri not in self._bundle_cache:
            from amplifier_foundation import load_bundle

            bundle = await load_bundle(bundle_uri)
            self._bundle_cache[bundle_uri] = bundle
        return self._bundle_cache[bundle_uri]

    async def _prepare_bundle(self, bundle: Any) -> Any:
        """Prepare a bundle for execution with caching."""
        cache_key = f"{bundle.name}:{bundle.version}"
        if cache_key not in self._prepared_cache:
            prepared = await bundle.prepare(install_deps=True)
            self._prepared_cache[cache_key] = prepared
        return self._prepared_cache[cache_key]

    async def _create_amplifier_session(
        self,
        bundle_uri: str,
        session_id: str,
        config: dict[str, Any],
        provider_bundle: str | None = None,
    ) -> Any:
        """Create an Amplifier session from a bundle.

        This integrates with amplifier-foundation to create real sessions.
        """
        if not self._amplifier_available:
            logger.info(f"Using mock session for {session_id}")
            return MockSession(session_id, bundle_uri)

        try:
            from amplifier_foundation import Bundle

            # Load base bundle
            bundle = await self._load_bundle(bundle_uri)

            # Build provider config if provider_bundle specified
            # Provider modules are configured via the providers list with source URLs
            providers_config = config.get("providers", [])
            if provider_bundle and not providers_config:
                # Use Claude Haiku for fast, cheap scoring (not Sonnet with extended thinking)
                # Must specify source so the module can be downloaded/installed
                providers_config = [
                    {
                        "module": "provider-anthropic",
                        "source": "git+https://github.com/microsoft/amplifier-module-provider-anthropic@main",
                        "config": {
                            "model": "claude-haiku-3-5-20241022",  # Fast, cheap
                            "max_tokens": 300,  # Short JSON responses only
                        },
                    }
                ]

            # Compose with config overrides
            override_bundle = Bundle(
                name="config-override",
                version="1.0.0",
                session=config.get("session", {}),
                providers=providers_config,
                tools=config.get("tools", []),
                hooks=config.get("hooks", []),
            )
            bundle = bundle.compose(override_bundle)

            # Prepare bundle (downloads modules)
            prepared = await self._prepare_bundle(bundle)

            # Create session
            session = await prepared.create_session(
                session_id=session_id,
                parent_id=None,
            )

            return session

        except Exception as e:
            logger.error(f"Failed to create Amplifier session: {e}")
            logger.info(f"Falling back to mock session for {session_id}")
            return MockSession(session_id, bundle_uri)

    async def _create_minimal_amplifier_session(self, session_id: str) -> Any:
        """Create an optimized Amplifier session for scoring.

        Uses foundation bundle but with Haiku for fast/cheap scoring.
        """
        if not self._amplifier_available:
            return MockSession(session_id, "minimal-scorer")

        try:
            from amplifier_foundation import Bundle

            # Use foundation bundle as base (has orchestrator, context, etc.)
            bundle = await self._load_bundle(
                "git+https://github.com/microsoft/amplifier-foundation@main"
            )

            # Get config directory path for file access
            config_dir = str(self.data_dir / "config")

            # Override with Haiku provider, minimal system prompt, and file access
            override = Bundle(
                name="scorer-override",
                version="1.0.0",
                session={
                    "system_prompt": (
                        "You are a notification classifier with autonomous config management. "
                        f"Rules file: {config_dir}/attention-rules.md\n\n"
                        "IMPORTANT: Check the current time. If it's after 12:00 PM and the "
                        "rules file still has 'Before 12:00 PM' instructions, UPDATE the "
                        "file to switch to 'After 12:00 PM' mode before scoring.\n\n"
                        "Then score the notification and respond ONLY with JSON."
                    ),
                },
                providers=[
                    {
                        "module": "provider-anthropic",
                        "source": "git+https://github.com/microsoft/amplifier-module-provider-anthropic@main",
                        "config": {
                            "model": "claude-haiku-3-5-20241022",
                            "max_tokens": 300,
                        },
                    }
                ],
                tools=[
                    {
                        "module": "tool-filesystem",
                        "config": {
                            "allowed_write_paths": [config_dir],
                        },
                    }
                ],
            )
            bundle = bundle.compose(override)

            # Prepare and create session
            prepared = await self._prepare_bundle(bundle)
            session = await prepared.create_session(
                session_id=session_id,
                parent_id=None,
            )

            return session

        except Exception as e:
            logger.error(f"Failed to create minimal session: {e}")
            raise

    async def get_session(self, session_id: str) -> Any:
        """Get a session by ID.

        Args:
            session_id: The session ID

        Returns:
            The AmplifierSession

        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(session_id)
        return self._sessions[session_id]

    async def get_session_info(self, session_id: str) -> SessionInfo:
        """Get info about a session."""
        if session_id not in self._session_info:
            raise SessionNotFoundError(session_id)
        return self._session_info[session_id]

    async def list_sessions(self) -> list[SessionInfo]:
        """List all sessions."""
        return list(self._session_info.values())

    async def execute(
        self,
        session_id: str,
        prompt: str,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        """Execute a prompt in a session.

        Args:
            session_id: The session ID
            prompt: User message to process
            stream: Whether to stream the response

        Returns:
            The response string, or an async iterator if streaming
        """
        session = await self.get_session(session_id)
        info = self._session_info[session_id]

        async with self._session_locks[session_id]:
            info.status = SessionStatus.EXECUTING
            info.last_activity = datetime.now()

            try:
                if stream:
                    # Return async generator for streaming
                    return self._stream_execute(session, info, prompt)
                else:
                    # Direct execution
                    result = await session.execute(prompt)
                    info.message_count += 1
                    info.status = SessionStatus.READY
                    return result

            except Exception as e:
                info.status = SessionStatus.ERROR
                info.metadata["last_error"] = str(e)
                raise

    async def _stream_execute(
        self,
        session: Any,
        info: SessionInfo,
        prompt: str,
    ) -> AsyncIterator[str]:
        """Stream execution results."""
        try:
            async for chunk in session.execute_stream(prompt):
                yield chunk
            info.message_count += 1
            info.status = SessionStatus.READY
        except Exception as e:
            info.status = SessionStatus.ERROR
            info.metadata["last_error"] = str(e)
            raise

    async def inject_context(
        self,
        session_id: str,
        content: str,
        role: str = "user",
    ) -> None:
        """Inject context into a session without executing.

        Useful for feeding notifications, events, etc.

        Args:
            session_id: The session ID
            content: Content to inject
            role: Message role (user, system, assistant)
        """
        session = await self.get_session(session_id)
        info = self._session_info[session_id]

        async with self._session_locks[session_id]:
            # Try to get context from coordinator
            try:
                context = session.coordinator.get("context")
                if context:
                    await context.add_message({"role": role, "content": content})
            except AttributeError:
                # MockSession or different API
                if hasattr(session, "inject_context"):
                    await session.inject_context(role, content)

            info.last_activity = datetime.now()

    async def clear_context(self, session_id: str) -> None:
        """Clear all conversation context from a session.

        Resets the session to a clean state, keeping only the system prompt.
        Useful for stateless operations like scoring where each request
        should be independent.

        Args:
            session_id: The session ID
        """
        session = await self.get_session(session_id)

        async with self._session_locks[session_id]:
            try:
                # Try to get context from coordinator and clear it
                context = session.coordinator.get("context")
                if context:
                    # Clear messages but preserve system prompt
                    if hasattr(context, "clear"):
                        await context.clear()
                    elif hasattr(context, "messages"):
                        # Direct access to messages list
                        context.messages.clear()
                    logger.debug(f"Cleared context for session {session_id}")
            except AttributeError:
                # MockSession or different API
                if hasattr(session, "clear_context"):
                    await session.clear_context()
                elif hasattr(session, "messages"):
                    session.messages.clear()
                elif hasattr(session, "_context"):
                    session._context.clear()

    async def stop_session(self, session_id: str) -> None:
        """Stop and cleanup a session."""
        if session_id not in self._sessions:
            raise SessionNotFoundError(session_id)

        logger.info(f"Stopping session {session_id}")

        session = self._sessions.pop(session_id)
        info = self._session_info[session_id]

        try:
            await session.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up session {session_id}: {e}")

        info.status = SessionStatus.STOPPED

    async def shutdown(self) -> None:
        """Shutdown all sessions gracefully."""
        logger.info(f"Shutting down {len(self._sessions)} sessions")

        for session_id in list(self._sessions.keys()):
            try:
                await self.stop_session(session_id)
            except Exception as e:
                logger.error(f"Error stopping session {session_id}: {e}")


class MockSession:
    """Mock session for testing without amplifier-foundation."""

    def __init__(self, session_id: str, bundle: str):
        self.session_id = session_id
        self.bundle = bundle
        self.messages: list[dict[str, str]] = []
        self._context: list[dict[str, str]] = []

    async def execute(self, prompt: str) -> str:
        self.messages.append({"role": "user", "content": prompt})
        response = f"[MockSession:{self.bundle}] Received: {prompt[:100]}..."
        self.messages.append({"role": "assistant", "content": response})
        return response

    async def execute_stream(self, prompt: str) -> AsyncIterator[str]:
        response = await self.execute(prompt)
        for word in response.split():
            yield word + " "
            await asyncio.sleep(0.05)

    async def inject_context(self, role: str, content: str) -> None:
        self._context.append({"role": role, "content": content})

    async def cleanup(self) -> None:
        pass

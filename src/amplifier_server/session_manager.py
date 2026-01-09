"""Session manager for hosting multiple concurrent Amplifier sessions."""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

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
        self._bundle_cache: dict[str, Any] = {}
    
    async def create_session(
        self,
        bundle: str,
        session_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Create and initialize a new session.
        
        Args:
            bundle: Bundle name or path
            session_id: Optional custom session ID
            config: Session configuration overrides
            
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
            # Load bundle and create session
            # Note: This is a placeholder - actual implementation depends on
            # how amplifier-foundation exposes bundle loading
            session = await self._create_amplifier_session(
                bundle=bundle,
                session_id=session_id,
                config=config or {},
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
    
    async def _create_amplifier_session(
        self,
        bundle: str,
        session_id: str,
        config: dict[str, Any],
    ) -> Any:
        """Create an Amplifier session from a bundle.
        
        This is where we integrate with amplifier-core/foundation.
        """
        # Import here to avoid circular deps and allow graceful degradation
        try:
            from amplifier_foundation import load_bundle, PreparedBundle
        except ImportError:
            logger.warning("amplifier-foundation not available, using mock session")
            return MockSession(session_id, bundle)
        
        # Load bundle (with caching)
        if bundle not in self._bundle_cache:
            prepared = await load_bundle(bundle)
            self._bundle_cache[bundle] = prepared
        else:
            prepared = self._bundle_cache[bundle]
        
        # Create session
        session_dir = self.data_dir / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        session = await prepared.create_session(
            session_id=session_id,
            session_dir=session_dir,
            config_overrides=config,
        )
        
        await session.initialize()
        return session
    
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
            # Add to context without triggering execution
            await session.context.add_message(role=role, content=content)
            info.last_activity = datetime.now()
    
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
    
    async def cleanup(self) -> None:
        pass
    
    class context:
        @staticmethod
        async def add_message(role: str, content: str) -> None:
            pass

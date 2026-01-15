"""Session management API endpoints."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from amplifier_server.models import (
    CreateSessionRequest,
    CreateSessionResponse,
    ExecuteRequest,
    ExecuteResponse,
    SessionInfo,
    SessionStatus,
)
from amplifier_server.session_manager import SessionManager, SessionNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def get_session_manager() -> SessionManager:
    """Dependency to get session manager - injected by server."""
    # This will be overridden by the server
    raise NotImplementedError("Session manager not injected")


@router.post("", response_model=CreateSessionResponse)
async def create_session(
    request: CreateSessionRequest,
    manager: SessionManager = Depends(get_session_manager),
) -> CreateSessionResponse:
    """Create a new Amplifier session."""
    try:
        session_id = await manager.create_session(
            bundle=request.bundle,
            session_id=request.session_id,
            config=request.config,
        )

        return CreateSessionResponse(
            session_id=session_id,
            status=SessionStatus.READY,
            message=f"Session created with bundle: {request.bundle}",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")


@router.get("", response_model=list[SessionInfo])
async def list_sessions(
    manager: SessionManager = Depends(get_session_manager),
) -> list[SessionInfo]:
    """List all sessions."""
    return await manager.list_sessions()


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    manager: SessionManager = Depends(get_session_manager),
) -> SessionInfo:
    """Get information about a session."""
    try:
        return await manager.get_session_info(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.post("/{session_id}/execute", response_model=ExecuteResponse)
async def execute(
    session_id: str,
    request: ExecuteRequest,
    manager: SessionManager = Depends(get_session_manager),
) -> ExecuteResponse:
    """Execute a prompt in a session."""
    try:
        start_time = time.time()

        response = await manager.execute(
            session_id=session_id,
            prompt=request.prompt,
            stream=False,  # Streaming handled via WebSocket
        )

        duration_ms = int((time.time() - start_time) * 1000)

        return ExecuteResponse(
            session_id=session_id,
            response=response,
            tool_calls=[],  # TODO: Extract from response
            duration_ms=duration_ms,
        )

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except Exception as e:
        logger.error(f"Execution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/inject")
async def inject_context(
    session_id: str,
    content: str,
    role: str = "user",
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, str]:
    """Inject context into a session without executing.

    Useful for feeding notifications, events, etc. into the session
    without triggering an immediate response.
    """
    try:
        await manager.inject_context(
            session_id=session_id,
            content=content,
            role=role,
        )
        return {"status": "injected"}

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except Exception as e:
        logger.error(f"Inject error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def stop_session(
    session_id: str,
    manager: SessionManager = Depends(get_session_manager),
) -> dict[str, str]:
    """Stop and cleanup a session."""
    try:
        await manager.stop_session(session_id)
        return {"status": "stopped", "session_id": session_id}

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    except Exception as e:
        logger.error(f"Stop session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

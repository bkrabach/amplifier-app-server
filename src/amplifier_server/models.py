"""Pydantic models for API requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Session lifecycle states."""
    
    INITIALIZING = "initializing"
    READY = "ready"
    EXECUTING = "executing"
    ERROR = "error"
    STOPPED = "stopped"


class SessionInfo(BaseModel):
    """Information about a session."""
    
    session_id: str
    bundle: str
    status: SessionStatus
    created_at: datetime
    last_activity: datetime | None = None
    message_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""
    
    bundle: str = Field(
        description="Bundle name or path (e.g., 'foundation', 'git+https://...')"
    )
    session_id: str | None = Field(
        default=None,
        description="Optional custom session ID"
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Session configuration overrides"
    )


class CreateSessionResponse(BaseModel):
    """Response from session creation."""
    
    session_id: str
    status: SessionStatus
    message: str


class ExecuteRequest(BaseModel):
    """Request to execute a prompt in a session."""
    
    prompt: str = Field(description="User message to process")
    stream: bool = Field(
        default=False,
        description="Whether to stream the response"
    )


class ExecuteResponse(BaseModel):
    """Response from execution."""
    
    session_id: str
    response: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int


class IngestNotificationRequest(BaseModel):
    """Request to ingest a notification from a client device."""
    
    device_id: str = Field(description="Identifier for the source device")
    app_id: str = Field(description="Source application ID")
    app_name: str | None = Field(default=None, description="Human-readable app name")
    title: str
    body: str | None = None
    timestamp: str = Field(description="ISO-8601 timestamp")
    sender: str | None = None
    conversation_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] | None = Field(default=None, description="Raw notification data")


class PushNotificationRequest(BaseModel):
    """Request to push a notification to a client device."""
    
    device_id: str | None = Field(
        default=None,
        description="Target device (None = all connected devices)"
    )
    title: str
    body: str
    urgency: str = "normal"
    rationale: str | None = None
    app_source: str | None = None
    actions: list[dict[str, str]] = Field(default_factory=list)


class WebSocketMessage(BaseModel):
    """WebSocket message envelope."""
    
    type: str = Field(description="Message type: chat, event, notification, ping")
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class DeviceInfo(BaseModel):
    """Information about a connected device."""
    
    device_id: str
    device_name: str | None = None
    platform: str = "unknown"
    connected_at: datetime
    last_seen: datetime
    capabilities: list[str] = Field(default_factory=list)

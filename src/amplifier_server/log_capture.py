"""Log capture infrastructure for API and WebSocket streaming.

Provides a ring buffer that captures recent log entries and allows
streaming to WebSocket clients.
"""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Default buffer size (number of log entries to keep)
DEFAULT_BUFFER_SIZE = 1000


@dataclass
class LogEntry:
    """A captured log entry."""

    timestamp: str
    level: str
    logger_name: str
    message: str
    component: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger_name,
            "component": self.component or self._extract_component(),
            "message": self.message,
        }

    def _extract_component(self) -> str:
        """Extract component name from logger name."""
        # e.g., "amplifier_server.notification_processor" -> "notification_processor"
        if "." in self.logger_name:
            return self.logger_name.split(".")[-1]
        return self.logger_name


@dataclass
class LogBuffer:
    """Ring buffer for storing recent log entries."""

    max_size: int = DEFAULT_BUFFER_SIZE
    _entries: deque[LogEntry] = field(default_factory=deque)
    _subscribers: list[Callable[[LogEntry], None]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def add(self, entry: LogEntry) -> None:
        """Add a log entry to the buffer."""
        self._entries.append(entry)
        while len(self._entries) > self.max_size:
            self._entries.popleft()

        # Notify subscribers (non-blocking)
        for subscriber in self._subscribers:
            with contextlib.suppress(Exception):
                subscriber(entry)

    def get_recent(
        self,
        limit: int = 100,
        level: str | None = None,
        component: str | None = None,
    ) -> list[LogEntry]:
        """Get recent log entries with optional filtering."""
        entries = list(self._entries)

        # Apply filters
        if level:
            level_upper = level.upper()
            entries = [e for e in entries if e.level == level_upper]

        if component:
            component_lower = component.lower()
            entries = [
                e
                for e in entries
                if component_lower in (e.component or "").lower()
                or component_lower in e.logger_name.lower()
            ]

        # Return most recent entries (up to limit)
        return entries[-limit:]

    def subscribe(self, callback: Callable[[LogEntry], None]) -> Callable[[], None]:
        """Subscribe to new log entries. Returns unsubscribe function."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def clear(self) -> None:
        """Clear all entries from the buffer."""
        self._entries.clear()


class BufferingHandler(logging.Handler):
    """Logging handler that writes to a LogBuffer."""

    def __init__(self, buffer: LogBuffer, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the buffer."""
        try:
            entry = LogEntry(
                timestamp=datetime.now(UTC).isoformat(),
                level=record.levelname,
                logger_name=record.name,
                message=self.format(record),
                component=self._extract_component(record.name),
            )
            self.buffer.add(entry)
        except Exception:
            self.handleError(record)

    def _extract_component(self, logger_name: str) -> str | None:
        """Extract component name from logger name."""
        if "amplifier_server" in logger_name:
            parts = logger_name.split(".")
            if len(parts) > 1:
                return parts[-1]
        return None


# Global log buffer instance
_log_buffer: LogBuffer | None = None


def get_log_buffer() -> LogBuffer:
    """Get the global log buffer, creating it if necessary."""
    global _log_buffer
    if _log_buffer is None:
        _log_buffer = LogBuffer()
    return _log_buffer


def setup_log_capture(
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    level: int = logging.INFO,
) -> LogBuffer:
    """Set up log capture for the application.

    Installs a handler on the root logger that captures all log messages
    to a ring buffer for later retrieval via API.

    Args:
        buffer_size: Maximum number of log entries to keep
        level: Minimum log level to capture

    Returns:
        The LogBuffer instance
    """
    global _log_buffer
    _log_buffer = LogBuffer(max_size=buffer_size)

    # Create and configure the handler
    handler = BufferingHandler(_log_buffer, level=level)
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Add to root logger to capture everything
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    # Also add to amplifier_server logger specifically
    server_logger = logging.getLogger("amplifier_server")
    server_logger.addHandler(handler)

    return _log_buffer

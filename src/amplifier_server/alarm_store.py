"""Alarm storage and management for Cortex scheduler."""

import asyncio
import contextlib
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AlarmStore:
    """Manages scheduled alarms for Cortex wake-ups.

    Stores alarms that trigger at specific times to wake up Cortex Core
    for proactive actions. Supports alarms from various sources (cortex,
    notification watcher, calendar integration, user).
    """

    def __init__(self, db_path: Path, user_id: str | None = None):
        """Initialize alarm store.

        Args:
            db_path: Path to database file (shares DB with notifications)
            user_id: Optional user ID for per-user isolation
        """
        self.base_path = db_path
        self.user_id = user_id

        # If user_id provided, use per-user path
        if user_id:
            self.db_path = db_path.parent / "users" / user_id / "notifications.db"
        else:
            self.db_path = db_path

        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the alarm store.

        Note: This assumes the alarms table has already been created by
        NotificationStore._run_migrations(). This store shares the same
        database as notifications.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row

        logger.info(f"Alarm store initialized at {self.db_path}")

    async def create_alarm(
        self,
        trigger_at: datetime | str,
        reason: str,
        source: str = "cortex",
        context: dict[str, Any] | None = None,
    ) -> int:
        """Create a new alarm.

        Args:
            trigger_at: When the alarm should trigger (datetime or ISO string)
            reason: Human-readable reason for the alarm
            source: Origin of the alarm ('cortex', 'notification', 'calendar', 'user')
            context: Optional context data as dict (stored as JSON)

        Returns:
            The ID of the created alarm
        """
        if not self._connection:
            raise RuntimeError("Alarm store not initialized")

        # Convert datetime to ISO string if needed
        trigger_at_str = trigger_at.isoformat() if isinstance(trigger_at, datetime) else trigger_at

        now = datetime.utcnow().isoformat()
        context_json = json.dumps(context) if context else None

        async with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO alarms 
                (trigger_at, reason, source, status, context, created_at, user_id)
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (trigger_at_str, reason, source, context_json, now, self.user_id),
            )
            self._connection.commit()
            result = cursor.lastrowid
            if result is None:
                raise RuntimeError("Failed to get alarm ID")
            logger.debug(f"Created alarm {result}: {reason} at {trigger_at_str}")
            return result

    async def get_pending_alarms(self, before: datetime | None = None) -> list[dict[str, Any]]:
        """Get pending alarms that should trigger before given time.

        Args:
            before: Get alarms with trigger_at before this time.
                   Defaults to current time (all due alarms).

        Returns:
            List of alarm dicts with parsed context
        """
        if not self._connection:
            raise RuntimeError("Alarm store not initialized")

        if before is None:
            before = datetime.utcnow()

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM alarms 
                WHERE status = 'pending' AND trigger_at <= ?
                ORDER BY trigger_at ASC
                """,
                (before.isoformat(),),
            )
            rows = cursor.fetchall()
            return self._parse_alarm_rows(rows)

    async def get_next_alarm(self) -> dict[str, Any] | None:
        """Get the next pending alarm (soonest trigger_at).

        Returns:
            Alarm dict or None if no pending alarms
        """
        if not self._connection:
            raise RuntimeError("Alarm store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM alarms 
                WHERE status = 'pending'
                ORDER BY trigger_at ASC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._parse_alarm_row(dict(row))

    async def mark_triggered(self, alarm_id: int) -> None:
        """Mark an alarm as triggered.

        Args:
            alarm_id: ID of the alarm to mark
        """
        if not self._connection:
            raise RuntimeError("Alarm store not initialized")

        now = datetime.utcnow().isoformat()

        async with self._lock:
            self._connection.execute(
                """
                UPDATE alarms 
                SET status = 'triggered', triggered_at = ?
                WHERE id = ?
                """,
                (now, alarm_id),
            )
            self._connection.commit()
            logger.debug(f"Marked alarm {alarm_id} as triggered")

    async def cancel_alarm(self, alarm_id: int) -> None:
        """Cancel a pending alarm.

        Args:
            alarm_id: ID of the alarm to cancel
        """
        if not self._connection:
            raise RuntimeError("Alarm store not initialized")

        async with self._lock:
            self._connection.execute(
                """
                UPDATE alarms 
                SET status = 'cancelled'
                WHERE id = ? AND status = 'pending'
                """,
                (alarm_id,),
            )
            self._connection.commit()
            logger.debug(f"Cancelled alarm {alarm_id}")

    async def get_alarm_by_id(self, alarm_id: int) -> dict[str, Any] | None:
        """Get a specific alarm by ID.

        Args:
            alarm_id: ID of the alarm

        Returns:
            Alarm dict or None if not found
        """
        if not self._connection:
            raise RuntimeError("Alarm store not initialized")

        async with self._lock:
            cursor = self._connection.execute("SELECT * FROM alarms WHERE id = ?", (alarm_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._parse_alarm_row(dict(row))

    async def get_alarms_by_source(
        self, source: str, status: str = "pending"
    ) -> list[dict[str, Any]]:
        """Get alarms filtered by source and status.

        Args:
            source: Alarm source to filter by
            status: Alarm status to filter by (default: 'pending')

        Returns:
            List of alarm dicts
        """
        if not self._connection:
            raise RuntimeError("Alarm store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM alarms 
                WHERE source = ? AND status = ?
                ORDER BY trigger_at ASC
                """,
                (source, status),
            )
            rows = cursor.fetchall()
            return self._parse_alarm_rows(rows)

    def _parse_alarm_rows(self, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        """Parse multiple alarm rows, converting context JSON."""
        return [self._parse_alarm_row(dict(row)) for row in rows]

    def _parse_alarm_row(self, alarm: dict[str, Any]) -> dict[str, Any]:
        """Parse a single alarm row, converting context JSON."""
        if alarm.get("context"):
            with contextlib.suppress(json.JSONDecodeError):
                alarm["context"] = json.loads(alarm["context"])
        return alarm

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None


def create_user_alarm_store(base_dir: Path, user_id: str) -> AlarmStore:
    """Create an alarm store for a specific user.

    Args:
        base_dir: Base server data directory
        user_id: User ID

    Returns:
        AlarmStore instance for the user
    """
    user_dir = base_dir / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return AlarmStore(user_dir / "notifications.db", user_id=user_id)

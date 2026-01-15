"""Notification storage and retrieval."""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from amplifier_server.models import IngestNotificationRequest

logger = logging.getLogger(__name__)


class NotificationStore:
    """SQLite-based notification storage.

    Stores incoming notifications for later retrieval, analysis, and digest generation.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the database."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row

        # Create tables
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                app_id TEXT NOT NULL,
                app_name TEXT,
                title TEXT NOT NULL,
                body TEXT,
                sender TEXT,
                conversation_hint TEXT,
                timestamp TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                processed BOOLEAN DEFAULT FALSE,
                relevance_score REAL,
                decision TEXT,
                rationale TEXT,
                raw_data TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_notifications_device ON notifications(device_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_app ON notifications(app_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_timestamp ON notifications(timestamp);
            CREATE INDEX IF NOT EXISTS idx_notifications_processed ON notifications(processed);
        """)
        self._connection.commit()
        logger.info(f"Notification store initialized at {self.db_path}")

    async def store(self, request: IngestNotificationRequest) -> int:
        """Store a notification and return its ID."""
        async with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO notifications 
                (device_id, app_id, app_name, title, body, sender, 
                 conversation_hint, timestamp, ingested_at, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request.device_id,
                    request.app_id,
                    request.app_name,
                    request.title,
                    request.body,
                    request.sender,
                    request.conversation_hint,
                    request.timestamp,
                    datetime.utcnow().isoformat(),
                    json.dumps(request.raw) if request.raw else None,
                ),
            )
            self._connection.commit()
            return cursor.lastrowid

    async def get_recent(
        self,
        limit: int = 100,
        device_id: str | None = None,
        app_id: str | None = None,
        since: datetime | None = None,
        unprocessed_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Get recent notifications with optional filters."""
        query = "SELECT * FROM notifications WHERE 1=1"
        params = []

        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)

        if app_id:
            query += " AND app_id = ?"
            params.append(app_id)

        if since:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())

        if unprocessed_only:
            query += " AND processed = FALSE"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with self._lock:
            cursor = self._connection.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_by_id(self, notification_id: int) -> dict[str, Any] | None:
        """Get a specific notification by ID."""
        async with self._lock:
            cursor = self._connection.execute(
                "SELECT * FROM notifications WHERE id = ?", (notification_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    async def mark_processed(
        self,
        notification_id: int,
        relevance_score: float,
        decision: str,
        rationale: str,
    ) -> None:
        """Mark a notification as processed with AI results."""
        async with self._lock:
            self._connection.execute(
                """
                UPDATE notifications 
                SET processed = TRUE, relevance_score = ?, decision = ?, rationale = ?
                WHERE id = ?
                """,
                (relevance_score, decision, rationale, notification_id),
            )
            self._connection.commit()

    async def get_summary_stats(
        self,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Get summary statistics for notifications."""
        if since is None:
            since = datetime.utcnow() - timedelta(hours=24)

        async with self._lock:
            # Total count
            cursor = self._connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE timestamp >= ?", (since.isoformat(),)
            )
            total = cursor.fetchone()[0]

            # By app
            cursor = self._connection.execute(
                """
                SELECT app_id, app_name, COUNT(*) as count 
                FROM notifications 
                WHERE timestamp >= ?
                GROUP BY app_id 
                ORDER BY count DESC
                """,
                (since.isoformat(),),
            )
            by_app = [dict(row) for row in cursor.fetchall()]

            # By device
            cursor = self._connection.execute(
                """
                SELECT device_id, COUNT(*) as count 
                FROM notifications 
                WHERE timestamp >= ?
                GROUP BY device_id 
                ORDER BY count DESC
                """,
                (since.isoformat(),),
            )
            by_device = [dict(row) for row in cursor.fetchall()]

            # Processed vs unprocessed
            cursor = self._connection.execute(
                """
                SELECT processed, COUNT(*) as count 
                FROM notifications 
                WHERE timestamp >= ?
                GROUP BY processed
                """,
                (since.isoformat(),),
            )
            processing_stats = {
                "processed": 0,
                "unprocessed": 0,
            }
            for row in cursor.fetchall():
                if row["processed"]:
                    processing_stats["processed"] = row["count"]
                else:
                    processing_stats["unprocessed"] = row["count"]

            return {
                "since": since.isoformat(),
                "total": total,
                "by_app": by_app,
                "by_device": by_device,
                "processing": processing_stats,
            }

    async def generate_digest(
        self,
        since: datetime | None = None,
        include_low_relevance: bool = False,
    ) -> str:
        """Generate a text digest of notifications."""
        if since is None:
            since = datetime.utcnow() - timedelta(hours=1)

        notifications = await self.get_recent(limit=500, since=since)

        if not notifications:
            return f"No notifications since {since.strftime('%H:%M')}."

        # Group by app
        by_app: dict[str, list] = {}
        for n in notifications:
            app = n.get("app_name") or n.get("app_id", "Unknown")
            if app not in by_app:
                by_app[app] = []
            by_app[app].append(n)

        # Build digest
        lines = [f"📋 Notification Digest (since {since.strftime('%H:%M')})"]
        lines.append(f"Total: {len(notifications)} notifications from {len(by_app)} apps\n")

        for app, notifs in sorted(by_app.items(), key=lambda x: -len(x[1])):
            lines.append(f"**{app}** ({len(notifs)} notifications)")

            # Show first few
            for n in notifs[:3]:
                title = n.get("title", "")
                sender = n.get("sender", "")
                preview = f"  - {sender}: {title}" if sender else f"  - {title}"
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(preview)

            if len(notifs) > 3:
                lines.append(f"  ... and {len(notifs) - 3} more")
            lines.append("")

        return "\n".join(lines)

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

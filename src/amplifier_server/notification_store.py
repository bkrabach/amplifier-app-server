"""Notification storage and retrieval."""

import asyncio
import contextlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from amplifier_server.models import IngestNotificationRequest

logger = logging.getLogger(__name__)

# Schema version for migrations
CURRENT_SCHEMA_VERSION = 2


class NotificationStore:
    """SQLite-based notification storage.

    Stores incoming notifications for later retrieval, analysis, and digest generation.
    Supports per-user data isolation with separate databases.
    """

    def __init__(self, db_path: Path, user_id: str | None = None):
        """Initialize notification store.

        Args:
            db_path: Path to database file (or base path for per-user mode)
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
                raw_data TEXT,
                user_id TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_notifications_device ON notifications(device_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_app ON notifications(app_id);
            CREATE INDEX IF NOT EXISTS idx_notifications_timestamp ON notifications(timestamp);
            CREATE INDEX IF NOT EXISTS idx_notifications_processed ON notifications(processed);
            CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
        """)
        self._connection.commit()

        # Run migrations for triage support
        await self._run_migrations()

        logger.info(f"Notification store initialized at {self.db_path}")

    async def _run_migrations(self) -> None:
        """Run database migrations for triage support."""
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        async with self._lock:
            # Create schema_version table if it doesn't exist
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
            """)
            self._connection.commit()

            # Get current version
            cursor = self._connection.execute("SELECT MAX(version) FROM schema_version")
            row = cursor.fetchone()
            current_version = row[0] if row[0] is not None else 0

            if current_version < 1:
                await self._migrate_v1()
                self._connection.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (1, datetime.utcnow().isoformat()),
                )
                self._connection.commit()
                logger.info("Applied migration v1: triage support")

            if current_version < 2:
                await self._migrate_v2()
                self._connection.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (2, datetime.utcnow().isoformat()),
                )
                self._connection.commit()
                logger.info("Applied migration v2: notification enrichment fields")

    async def _migrate_v1(self) -> None:
        """Migration v1: Add triage support columns and tables."""
        if not self._connection:
            return

        # Add triage columns to notifications table (if not exist)
        # SQLite doesn't have IF NOT EXISTS for ALTER TABLE, so we check first
        cursor = self._connection.execute("PRAGMA table_info(notifications)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        new_columns = [
            ("triage_status", "TEXT"),  # pending, handled, dismissed, expired, NULL
            ("expires_at", "TEXT"),  # ISO timestamp when item should expire
            ("surfaced_at", "TEXT"),  # when it was surfaced to triage queue
            ("suggested_response", "TEXT"),  # JSON with AI-generated suggestions
            ("quick_reaction", "TEXT"),  # emoji reaction from user
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                self._connection.execute(
                    f"ALTER TABLE notifications ADD COLUMN {col_name} {col_type}"
                )

        # Create index for triage queries
        self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_notifications_triage 
            ON notifications(triage_status, expires_at)
        """)

        # Create alarms table
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_at TEXT NOT NULL,
                reason TEXT,
                source TEXT DEFAULT 'cortex',
                status TEXT DEFAULT 'pending',
                context TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                user_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_alarms_trigger ON alarms(trigger_at);
            CREATE INDEX IF NOT EXISTS idx_alarms_status ON alarms(status);
        """)

        # Create user_feedback table
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                feedback_type TEXT,
                feedback_text TEXT,
                original_score REAL,
                original_decision TEXT,
                time_in_queue_seconds INTEGER,
                created_at TEXT NOT NULL,
                user_id TEXT,
                FOREIGN KEY (notification_id) REFERENCES notifications(id)
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_notification 
            ON user_feedback(notification_id);
        """)

        self._connection.commit()

    async def _migrate_v2(self) -> None:
        """Migration v2: Add notification enrichment fields.

        Adds columns for:
        - App display name and package ID for better app identification
        - Conversation context (type and name) for messaging apps
        - AI reasoning (thinking and tags) for transparency
        """
        if not self._connection:
            return

        # Check existing columns
        cursor = self._connection.execute("PRAGMA table_info(notifications)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        new_columns = [
            ("app_display_name", "TEXT"),  # OS display name for the app
            ("app_package_id", "TEXT"),  # Package/bundle identifier
            ("conversation_type", "TEXT"),  # 'direct', 'group', 'channel'
            ("conversation_name", "TEXT"),  # Group/channel name
            ("ai_thinking", "TEXT"),  # Full LLM reasoning/chain-of-thought
            ("ai_tags", "TEXT"),  # JSON array of decision factor tags
        ]

        for col_name, col_type in new_columns:
            if col_name not in existing_columns:
                self._connection.execute(
                    f"ALTER TABLE notifications ADD COLUMN {col_name} {col_type}"
                )

        self._connection.commit()

    async def store(self, request: IngestNotificationRequest) -> int:
        """Store a notification and return its ID."""
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO notifications 
                (device_id, app_id, app_name, title, body, sender, 
                 conversation_hint, timestamp, ingested_at, raw_data, user_id,
                 app_display_name, app_package_id, conversation_type, conversation_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    self.user_id,
                    request.app_display_name,
                    request.app_package_id,
                    request.conversation_type,
                    request.conversation_name,
                ),
            )
            self._connection.commit()
            result = cursor.lastrowid
            if result is None:
                raise RuntimeError("Failed to get notification ID")
            return result

    async def get_recent(
        self,
        limit: int = 100,
        device_id: str | None = None,
        app_id: str | None = None,
        since: datetime | None = None,
        unprocessed_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Get recent notifications with optional filters."""
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

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

    async def get_conversation_history(
        self,
        notification: dict[str, Any],
        limit: int = 10,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Get recent notifications from the same conversation thread.

        Matches by conversation_hint (group/channel name) + app_id,
        or by sender + app_id for direct messages.
        Returns most recent first, excluding the notification itself.

        Args:
            notification: The current notification to find history for
            limit: Max number of history items to return
            hours: How far back to look (default 24h)

        Returns:
            List of recent notifications in the same conversation, newest first
        """
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        from datetime import timedelta

        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        notification_id = notification.get("id")
        app_id = notification.get("app_id") or notification.get("app_name")
        conversation_hint = notification.get("conversation_hint")
        sender = notification.get("sender")

        if not app_id:
            return []

        # Build query - match by conversation or sender within same app
        if conversation_hint:
            # Group/channel - match by conversation name
            query = """
                SELECT * FROM notifications
                WHERE app_id = ? AND conversation_hint = ?
                AND timestamp >= ?
                AND (id != ? OR ? IS NULL)
                ORDER BY timestamp DESC LIMIT ?
            """
            params = [app_id, conversation_hint, since, notification_id, notification_id, limit]
        elif sender:
            # Direct message - match by sender within same app
            query = """
                SELECT * FROM notifications
                WHERE app_id = ? AND sender = ?
                AND timestamp >= ?
                AND (id != ? OR ? IS NULL)
                ORDER BY timestamp DESC LIMIT ?
            """
            params = [app_id, sender, since, notification_id, notification_id, limit]
        else:
            return []

        async with self._lock:
            cursor = self._connection.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_by_id(self, notification_id: int) -> dict[str, Any] | None:
        """Get a specific notification by ID."""
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

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
        ai_thinking: str | None = None,
        ai_tags: list[str] | None = None,
    ) -> None:
        """Mark a notification as processed with AI results.

        Args:
            notification_id: ID of the notification to update
            relevance_score: Score from 0.0 to 1.0
            decision: Decision string ('push', 'summarize', 'suppress')
            rationale: Human-readable explanation
            ai_thinking: Full LLM reasoning/chain-of-thought (optional)
            ai_tags: List of decision factor tags (optional)
        """
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        # Serialize ai_tags to JSON if provided
        ai_tags_json = json.dumps(ai_tags) if ai_tags else None

        async with self._lock:
            self._connection.execute(
                """
                UPDATE notifications 
                SET processed = TRUE, relevance_score = ?, decision = ?, rationale = ?,
                    ai_thinking = ?, ai_tags = ?
                WHERE id = ?
                """,
                (relevance_score, decision, rationale, ai_thinking, ai_tags_json, notification_id),
            )
            self._connection.commit()

    async def get_summary_stats(
        self,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Get summary statistics for notifications."""
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

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

    # =========================================================================
    # Triage Methods
    # =========================================================================

    async def create_triage_item(
        self,
        notification_id: int,
        expires_at: str | None = None,
        suggested_response: dict | None = None,
        initial_status: str = "pending",
    ) -> None:
        """Mark a notification as a triage item.

        Args:
            notification_id: ID of the notification to mark for triage
            expires_at: ISO timestamp when item should expire (optional)
            suggested_response: AI-generated suggestions as dict (optional)
            initial_status: Initial triage status (default: 'pending').
                           Use 'surfaced' for push notifications that user already saw.
        """
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        now = datetime.utcnow().isoformat()
        suggested_json = json.dumps(suggested_response) if suggested_response else None

        async with self._lock:
            self._connection.execute(
                """
                UPDATE notifications 
                SET triage_status = ?, 
                    surfaced_at = ?,
                    expires_at = ?,
                    suggested_response = ?
                WHERE id = ?
                """,
                (initial_status, now, expires_at, suggested_json, notification_id),
            )
            self._connection.commit()

    async def get_triage_items(
        self, status: str = "pending", limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get triage items with specified status.

        Args:
            status: Triage status to filter by (default: 'pending')
            limit: Maximum number of items to return

        Returns:
            List of notification dicts with triage data
        """
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM notifications 
                WHERE triage_status = ?
                ORDER BY 
                    CASE WHEN expires_at IS NOT NULL THEN 0 ELSE 1 END,
                    expires_at ASC,
                    surfaced_at DESC
                LIMIT ?
                """,
                (status, limit),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                # Parse suggested_response JSON if present
                if item.get("suggested_response"):
                    with contextlib.suppress(json.JSONDecodeError):
                        item["suggested_response"] = json.loads(item["suggested_response"])
                results.append(item)
            return results

    async def update_triage_status(
        self,
        notification_id: int,
        status: str,
        quick_reaction: str | None = None,
    ) -> None:
        """Update the triage status of a notification.

        Args:
            notification_id: ID of the notification to update
            status: New triage status ('handled', 'dismissed', 'expired')
            quick_reaction: Optional emoji reaction from user
        """
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        async with self._lock:
            self._connection.execute(
                """
                UPDATE notifications 
                SET triage_status = ?, quick_reaction = ?
                WHERE id = ?
                """,
                (status, quick_reaction, notification_id),
            )
            self._connection.commit()

    async def update_expiration(self, notification_id: int, expires_at: str) -> None:
        """Update the expiration time for a triage item.

        Args:
            notification_id: ID of the notification to update
            expires_at: ISO timestamp for new expiration time
        """
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        async with self._lock:
            self._connection.execute(
                "UPDATE notifications SET expires_at = ? WHERE id = ?",
                (expires_at, notification_id),
            )
            self._connection.commit()

    async def expire_old_triage_items(self, before: datetime | None = None) -> int:
        """Expire triage items that have passed their expiration time.

        Args:
            before: Expire items with expires_at before this time.
                   Defaults to current time.

        Returns:
            Number of items expired
        """
        if not self._connection:
            raise RuntimeError("Notification store not initialized")

        if before is None:
            before = datetime.utcnow()

        async with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE notifications 
                SET triage_status = 'expired'
                WHERE triage_status = 'pending'
                  AND expires_at IS NOT NULL
                  AND expires_at < ?
                """,
                (before.isoformat(),),
            )
            self._connection.commit()
            return cursor.rowcount

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None


def get_user_data_dir(base_dir: Path, user_id: str) -> Path:
    """Get the data directory for a specific user.

    Args:
        base_dir: Base server data directory
        user_id: User ID

    Returns:
        Path to user's data directory
    """
    user_dir = base_dir / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def create_user_notification_store(base_dir: Path, user_id: str) -> NotificationStore:
    """Create a notification store for a specific user.

    Args:
        base_dir: Base server data directory
        user_id: User ID

    Returns:
        NotificationStore instance for the user
    """
    user_dir = get_user_data_dir(base_dir, user_id)
    return NotificationStore(user_dir / "notifications.db", user_id=user_id)

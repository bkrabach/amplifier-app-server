"""User feedback storage for learning system."""

import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FeedbackStore:
    """Stores user feedback on notification decisions for learning.

    Captures feedback when users triage notifications, allowing the system
    to learn from decisions like 'dealt_with', 'dismissed', 'already_handled'.
    Supports optional detailed feedback like 'good_call', 'bad_call', etc.
    """

    def __init__(self, db_path: Path, user_id: str | None = None):
        """Initialize feedback store.

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
        """Initialize the feedback store.

        Note: This assumes the user_feedback table has already been created by
        NotificationStore._run_migrations(). This store shares the same
        database as notifications.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row

        logger.info(f"Feedback store initialized at {self.db_path}")

    async def record_feedback(
        self,
        notification_id: int,
        action: str,
        feedback_type: str | None = None,
        feedback_text: str | None = None,
        original_score: float | None = None,
        original_decision: str | None = None,
        time_in_queue_seconds: int | None = None,
    ) -> int:
        """Record user feedback on a notification decision.

        Args:
            notification_id: ID of the notification being acted on
            action: User action ('dealt_with', 'dismissed', 'already_handled')
            feedback_type: Optional feedback type ('good_call', 'bad_call',
                          'wrong_timing', None)
            feedback_text: Optional free-text explanation
            original_score: Original relevance score from processor
            original_decision: Original decision ('push', 'summarize', 'suppress')
            time_in_queue_seconds: How long the item was in triage queue

        Returns:
            The ID of the created feedback record
        """
        if not self._connection:
            raise RuntimeError("Feedback store not initialized")

        now = datetime.utcnow().isoformat()

        async with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO user_feedback 
                (notification_id, action, feedback_type, feedback_text,
                 original_score, original_decision, time_in_queue_seconds,
                 created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification_id,
                    action,
                    feedback_type,
                    feedback_text,
                    original_score,
                    original_decision,
                    time_in_queue_seconds,
                    now,
                    self.user_id,
                ),
            )
            self._connection.commit()
            result = cursor.lastrowid
            if result is None:
                raise RuntimeError("Failed to get feedback ID")
            logger.debug(f"Recorded feedback {result}: {action} on notification {notification_id}")
            return result

    async def get_feedback_for_notification(self, notification_id: int) -> dict[str, Any] | None:
        """Get feedback for a specific notification.

        Args:
            notification_id: ID of the notification

        Returns:
            Feedback dict or None if no feedback recorded
        """
        if not self._connection:
            raise RuntimeError("Feedback store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM user_feedback 
                WHERE notification_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (notification_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    async def get_recent_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent feedback entries for analysis.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of feedback dicts, most recent first
        """
        if not self._connection:
            raise RuntimeError("Feedback store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM user_feedback 
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_feedback_stats(self) -> dict[str, Any]:
        """Get aggregate feedback statistics for learning insights.

        Returns:
            Dict with statistics:
            - total: Total feedback count
            - by_action: Counts by action type
            - by_feedback_type: Counts by feedback type
            - avg_time_in_queue: Average time in queue (seconds)
            - feedback_rate: Percentage of actions with explicit feedback
        """
        if not self._connection:
            raise RuntimeError("Feedback store not initialized")

        async with self._lock:
            stats: dict[str, Any] = {}

            # Total count
            cursor = self._connection.execute("SELECT COUNT(*) FROM user_feedback")
            stats["total"] = cursor.fetchone()[0]

            # By action
            cursor = self._connection.execute(
                """
                SELECT action, COUNT(*) as count 
                FROM user_feedback 
                GROUP BY action
                """
            )
            stats["by_action"] = {row["action"]: row["count"] for row in cursor.fetchall()}

            # By feedback type (only counts explicit feedback)
            cursor = self._connection.execute(
                """
                SELECT feedback_type, COUNT(*) as count 
                FROM user_feedback 
                WHERE feedback_type IS NOT NULL
                GROUP BY feedback_type
                """
            )
            stats["by_feedback_type"] = {
                row["feedback_type"]: row["count"] for row in cursor.fetchall()
            }

            # Average time in queue
            cursor = self._connection.execute(
                """
                SELECT AVG(time_in_queue_seconds) as avg_time
                FROM user_feedback 
                WHERE time_in_queue_seconds IS NOT NULL
                """
            )
            row = cursor.fetchone()
            stats["avg_time_in_queue_seconds"] = (
                round(row["avg_time"], 1) if row["avg_time"] else None
            )

            # Feedback rate (percentage with explicit feedback_type)
            cursor = self._connection.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN feedback_type IS NOT NULL THEN 1 ELSE 0 END) as with_feedback
                FROM user_feedback
                """
            )
            row = cursor.fetchone()
            if row["total"] > 0:
                stats["feedback_rate"] = round((row["with_feedback"] / row["total"]) * 100, 1)
            else:
                stats["feedback_rate"] = 0.0

            return stats

    async def get_feedback_by_original_decision(
        self, original_decision: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get feedback entries for a specific original decision.

        Useful for analyzing how well the system's decisions match user actions.

        Args:
            original_decision: The original decision ('push', 'summarize', 'suppress')
            limit: Maximum number of entries to return

        Returns:
            List of feedback dicts
        """
        if not self._connection:
            raise RuntimeError("Feedback store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM user_feedback 
                WHERE original_decision = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (original_decision, limit),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_misclassified_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get feedback where user indicated the decision was wrong.

        Returns feedback with 'bad_call' or 'wrong_timing' feedback_type,
        which indicates the system's decision didn't match user expectations.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of feedback dicts indicating misclassification
        """
        if not self._connection:
            raise RuntimeError("Feedback store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT * FROM user_feedback 
                WHERE feedback_type IN ('bad_call', 'wrong_timing')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None


def create_user_feedback_store(base_dir: Path, user_id: str) -> FeedbackStore:
    """Create a feedback store for a specific user.

    Args:
        base_dir: Base server data directory
        user_id: User ID

    Returns:
        FeedbackStore instance for the user
    """
    user_dir = base_dir / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return FeedbackStore(user_dir / "notifications.db", user_id=user_id)

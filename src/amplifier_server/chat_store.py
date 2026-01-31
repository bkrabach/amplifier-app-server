"""Chat message storage and retrieval."""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChatStore:
    """SQLite-based chat message storage.

    Stores chat messages for history retrieval across reconnections.
    Supports per-user data isolation.
    """

    def __init__(self, db_path: Path, user_id: str | None = None):
        """Initialize chat store.

        Args:
            db_path: Path to database file (or base path for per-user mode)
            user_id: Optional user ID for per-user isolation
        """
        self.base_path = db_path
        self.user_id = user_id

        # If user_id provided, use per-user path
        if user_id:
            self.db_path = db_path.parent / "users" / user_id / "chat.db"
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
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_messages(created_at);
        """)
        self._connection.commit()

        logger.info(f"Chat store initialized at {self.db_path}")

    async def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Add a chat message.

        Args:
            user_id: User ID
            session_id: Session ID (e.g., cortex-core-{user_id})
            role: Message role (user, assistant)
            content: Message content
            metadata: Optional metadata dict

        Returns:
            Message ID
        """
        if not self._connection:
            raise RuntimeError("Chat store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO chat_messages (user_id, session_id, role, content, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    session_id,
                    role,
                    content,
                    datetime.utcnow().isoformat(),
                    json.dumps(metadata) if metadata else None,
                ),
            )
            self._connection.commit()
            return cursor.lastrowid or 0

    async def get_recent_messages(
        self,
        user_id: str,
        session_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent messages for a user's session.

        Args:
            user_id: User ID
            session_id: Session ID
            limit: Max messages to retrieve (default 50)

        Returns:
            List of messages (oldest first)
        """
        if not self._connection:
            raise RuntimeError("Chat store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                """
                SELECT id, role, content, created_at, metadata
                FROM chat_messages
                WHERE user_id = ? AND session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, session_id, limit),
            )
            rows = cursor.fetchall()

        # Reverse to get oldest first
        messages = []
        for row in reversed(rows):
            msg = {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            if row["metadata"]:
                msg["metadata"] = json.loads(row["metadata"])
            messages.append(msg)

        return messages

    async def clear_session(self, user_id: str, session_id: str) -> int:
        """Clear all messages for a session.

        Returns:
            Number of messages deleted
        """
        if not self._connection:
            raise RuntimeError("Chat store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM chat_messages WHERE user_id = ? AND session_id = ?",
                (user_id, session_id),
            )
            self._connection.commit()
            return cursor.rowcount

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

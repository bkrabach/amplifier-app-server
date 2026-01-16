"""SQLite-based user, API key, and refresh token storage."""

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from amplifier_server.auth.models import APIKey, RefreshToken, User, UserRole
from amplifier_server.auth.security import hash_token

logger = logging.getLogger(__name__)


class UserStore:
    """SQLite-based storage for users, API keys, and refresh tokens."""

    def __init__(self, db_path: Path):
        """Initialize the user store.

        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = db_path
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row

        # Create tables
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                last_login TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                key_hash TEXT UNIQUE NOT NULL,
                prefix TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used TEXT,
                expires_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
            CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
            
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);
        """)
        self._connection.commit()
        logger.info(f"User store initialized at {self.db_path}")

    # User operations

    async def create_user(
        self,
        username: str,
        password_hash: str,
        email: str | None = None,
        role: UserRole = UserRole.USER,
    ) -> User:
        """Create a new user."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        user_id = str(uuid.uuid4())
        created_at = datetime.utcnow()

        async with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO users (id, username, email, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username, email, password_hash, role.value, created_at.isoformat()),
                )
                self._connection.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError(f"User already exists: {username}") from e

        return User(
            id=user_id,
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            created_at=created_at,
            is_active=True,
        )

    async def get_user(self, user_id: str) -> User | None:
        """Get user by ID."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            cursor = self._connection.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    async def get_user_by_username(self, username: str) -> User | None:
        """Get user by username."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            cursor = self._connection.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    async def get_user_by_api_key(self, api_key: str) -> User | None:
        """Get user associated with an API key."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        key_hash = hash_token(api_key)

        async with self._lock:
            # Get API key
            cursor = self._connection.execute(
                "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
                (key_hash,),
            )
            api_key_row = cursor.fetchone()
            if not api_key_row:
                return None

            # Check expiration
            if api_key_row["expires_at"]:
                expires_at = datetime.fromisoformat(api_key_row["expires_at"])
                if expires_at < datetime.utcnow():
                    return None

            # Update last_used
            self._connection.execute(
                "UPDATE api_keys SET last_used = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), api_key_row["id"]),
            )
            self._connection.commit()

            # Get user
            cursor = self._connection.execute(
                "SELECT * FROM users WHERE id = ? AND is_active = 1",
                (api_key_row["user_id"],),
            )
            user_row = cursor.fetchone()
            if not user_row:
                return None

            return self._row_to_user(user_row)

    async def list_users(self) -> list[User]:
        """List all users."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            cursor = self._connection.execute("SELECT * FROM users ORDER BY created_at DESC")
            return [self._row_to_user(row) for row in cursor.fetchall()]

    async def count_users(self) -> int:
        """Count total users."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            cursor = self._connection.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]

    async def update_last_login(self, user_id: str) -> None:
        """Update user's last login time."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            self._connection.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), user_id),
            )
            self._connection.commit()

    async def update_user(
        self,
        user_id: str,
        email: str | None = None,
        password_hash: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> User | None:
        """Update user fields."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        updates = []
        params = []

        if email is not None:
            updates.append("email = ?")
            params.append(email)
        if password_hash is not None:
            updates.append("password_hash = ?")
            params.append(password_hash)
        if role is not None:
            updates.append("role = ?")
            params.append(role.value)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)

        if not updates:
            return await self.get_user(user_id)

        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"

        async with self._lock:
            self._connection.execute(query, params)
            self._connection.commit()

        return await self.get_user(user_id)

    # API Key operations

    async def create_api_key(
        self,
        user_id: str,
        key_hash: str,
        prefix: str,
        name: str,
        expires_at: datetime | None = None,
    ) -> APIKey:
        """Create a new API key."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        key_id = str(uuid.uuid4())
        created_at = datetime.utcnow()

        async with self._lock:
            self._connection.execute(
                """
                INSERT INTO api_keys (id, user_id, key_hash, prefix, name, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key_id,
                    user_id,
                    key_hash,
                    prefix,
                    name,
                    created_at.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                ),
            )
            self._connection.commit()

        return APIKey(
            id=key_id,
            user_id=user_id,
            key_hash=key_hash,
            prefix=prefix,
            name=name,
            created_at=created_at,
            expires_at=expires_at,
            is_active=True,
        )

    async def list_api_keys(self, user_id: str) -> list[APIKey]:
        """List all API keys for a user."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            cursor = self._connection.execute(
                "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
            return [self._row_to_api_key(row) for row in cursor.fetchall()]

    async def revoke_api_key(self, key_id: str) -> None:
        """Revoke an API key."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            self._connection.execute(
                "UPDATE api_keys SET is_active = 0 WHERE id = ?",
                (key_id,),
            )
            self._connection.commit()

    # Refresh Token operations

    async def create_refresh_token(
        self,
        user_id: str,
        token_hash: str,
        expires_at: datetime | None = None,
    ) -> RefreshToken:
        """Create a new refresh token."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        token_id = str(uuid.uuid4())
        created_at = datetime.utcnow()

        if expires_at is None:
            expires_at = created_at + timedelta(days=30)

        async with self._lock:
            self._connection.execute(
                """
                INSERT INTO refresh_tokens (id, user_id, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token_id, user_id, token_hash, created_at.isoformat(), expires_at.isoformat()),
            )
            self._connection.commit()

        return RefreshToken(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            created_at=created_at,
            expires_at=expires_at,
            revoked=False,
        )

    async def get_refresh_token(self, token: str) -> RefreshToken | None:
        """Get refresh token by token value."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        token_hash = hash_token(token)

        async with self._lock:
            cursor = self._connection.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?",
                (token_hash,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_refresh_token(row)

    async def revoke_refresh_token(self, token: str) -> None:
        """Revoke a refresh token."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        token_hash = hash_token(token)

        async with self._lock:
            self._connection.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?",
                (token_hash,),
            )
            self._connection.commit()

    async def revoke_user_tokens(self, user_id: str) -> None:
        """Revoke all refresh tokens for a user."""
        if not self._connection:
            raise RuntimeError("User store not initialized")

        async with self._lock:
            self._connection.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?",
                (user_id,),
            )
            self._connection.commit()

    # Helper methods

    def _row_to_user(self, row: sqlite3.Row) -> User:
        """Convert database row to User model."""
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            role=UserRole(row["role"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_login=datetime.fromisoformat(row["last_login"]) if row["last_login"] else None,
            is_active=bool(row["is_active"]),
        )

    def _row_to_api_key(self, row: sqlite3.Row) -> APIKey:
        """Convert database row to APIKey model."""
        return APIKey(
            id=row["id"],
            user_id=row["user_id"],
            key_hash=row["key_hash"],
            prefix=row["prefix"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_used=datetime.fromisoformat(row["last_used"]) if row["last_used"] else None,
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            is_active=bool(row["is_active"]),
        )

    def _row_to_refresh_token(self, row: sqlite3.Row) -> RefreshToken:
        """Convert database row to RefreshToken model."""
        return RefreshToken(
            id=row["id"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            revoked=bool(row["revoked"]),
        )

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

"""Database models and operations for the orchestrator.

Uses aiosqlite for async SQLite operations — same approach as the registry service.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import aiosqlite
import structlog

log = structlog.get_logger()

# ISO format helper
_now = lambda: datetime.now(timezone.utc).isoformat()


class OrchestratorDB:
    """Async SQLite database for users, agent instances, and magic links."""

    def __init__(self, db_path: str = "orchestrator.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Initialize database and create tables."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                subdomain TEXT UNIQUE,
                created_at TEXT NOT NULL,
                last_login TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_instances (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                container_id TEXT,
                port INTEGER,
                api_token TEXT,
                agent_url TEXT,
                status TEXT DEFAULT 'starting',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS magic_links (
                token TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_agent_user ON agent_instances(user_id);
            CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_links(email);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        """)
        await self._db.commit()
        log.info("orchestrator_db_initialized", path=self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ── Users ─────────────────────────────────────────────────

    async def create_user(self, email: str, subdomain: str | None = None) -> dict:
        """Create a new user with optional subdomain. Returns user dict."""
        user_id = str(uuid.uuid4())
        now = _now()
        await self._db.execute(
            "INSERT INTO users (id, email, subdomain, created_at, last_login) VALUES (?, ?, ?, ?, ?)",
            (user_id, email.lower().strip(), subdomain, now, now),
        )
        await self._db.commit()
        return {
            "id": user_id,
            "email": email.lower().strip(),
            "subdomain": subdomain,
            "created_at": now,
            "last_login": now,
        }

    async def get_user_by_email(self, email: str) -> dict | None:
        """Find user by email."""
        cursor = await self._db.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_user_by_id(self, user_id: str) -> dict | None:
        """Find user by ID."""
        cursor = await self._db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_last_login(self, user_id: str) -> None:
        """Update user's last login timestamp."""
        await self._db.execute(
            "UPDATE users SET last_login = ? WHERE id = ?", (_now(), user_id)
        )
        await self._db.commit()

    async def count_users(self) -> int:
        cursor = await self._db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0]

    async def get_all_subdomains(self) -> set[str]:
        """Get all taken subdomains for uniqueness checking."""
        cursor = await self._db.execute(
            "SELECT subdomain FROM users WHERE subdomain IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return {row[0] for row in rows}

    async def get_user_by_subdomain(self, subdomain: str) -> dict | None:
        """Find user by subdomain."""
        cursor = await self._db.execute(
            "SELECT * FROM users WHERE subdomain = ?", (subdomain,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── Agent Instances ───────────────────────────────────────

    async def create_agent_instance(
        self,
        user_id: str,
        container_id: str | None = None,
        port: int | None = None,
        api_token: str | None = None,
        agent_url: str | None = None,
        status: str = "starting",
    ) -> dict:
        """Create a new agent instance record."""
        instance_id = str(uuid.uuid4())
        now = _now()
        await self._db.execute(
            """INSERT INTO agent_instances
               (id, user_id, container_id, port, api_token, agent_url, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (instance_id, user_id, container_id, port, api_token, agent_url, status, now, now),
        )
        await self._db.commit()
        return {
            "id": instance_id,
            "user_id": user_id,
            "container_id": container_id,
            "port": port,
            "api_token": api_token,
            "agent_url": agent_url,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }

    async def get_agent_by_user(self, user_id: str) -> dict | None:
        """Get agent instance for a user (one agent per user)."""
        cursor = await self._db.execute(
            "SELECT * FROM agent_instances WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_agent_by_id(self, instance_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT * FROM agent_instances WHERE id = ?", (instance_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_agent_status(self, instance_id: str, status: str, **kwargs) -> None:
        """Update agent instance status and optional fields."""
        sets = ["status = ?", "updated_at = ?"]
        values = [status, _now()]
        for key, val in kwargs.items():
            if key in ("container_id", "port", "api_token", "agent_url"):
                sets.append(f"{key} = ?")
                values.append(val)
        values.append(instance_id)
        await self._db.execute(
            f"UPDATE agent_instances SET {', '.join(sets)} WHERE id = ?", values
        )
        await self._db.commit()

    async def delete_agent_instance(self, instance_id: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM agent_instances WHERE id = ?", (instance_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def list_all_agents(self) -> list[dict]:
        """List all agent instances (admin)."""
        cursor = await self._db.execute(
            """SELECT ai.*, u.email FROM agent_instances ai
               JOIN users u ON ai.user_id = u.id
               ORDER BY ai.created_at DESC"""
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count_agents(self) -> int:
        cursor = await self._db.execute("SELECT COUNT(*) FROM agent_instances")
        row = await cursor.fetchone()
        return row[0]

    # ── Magic Links ───────────────────────────────────────────

    async def create_magic_link(self, token: str, email: str, expires_at: str) -> None:
        """Store a magic link token."""
        await self._db.execute(
            "INSERT INTO magic_links (token, email, expires_at, used) VALUES (?, ?, ?, 0)",
            (token, email.lower().strip(), expires_at),
        )
        await self._db.commit()

    async def use_magic_link(self, token: str) -> dict | None:
        """Consume a magic link. Returns {email, expires_at} or None if invalid/used."""
        cursor = await self._db.execute(
            "SELECT * FROM magic_links WHERE token = ? AND used = 0", (token,)
        )
        row = await cursor.fetchone()
        if not row:
            return None

        # Mark as used
        await self._db.execute(
            "UPDATE magic_links SET used = 1 WHERE token = ?", (token,)
        )
        await self._db.commit()
        return dict(row)

    async def cleanup_expired_links(self) -> int:
        """Remove expired magic links."""
        now = _now()
        cursor = await self._db.execute(
            "DELETE FROM magic_links WHERE expires_at < ? OR used = 1", (now,)
        )
        await self._db.commit()
        return cursor.rowcount

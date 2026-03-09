"""Registry SQLite storage — lightweight persistence for registered agents."""

from __future__ import annotations

import json
import aiosqlite
import structlog
from pathlib import Path
from datetime import datetime, timezone

log = structlog.get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS registered_agents (
    did TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    name TEXT,
    description TEXT,
    skills_json TEXT,
    status TEXT DEFAULT 'online',
    failures INTEGER DEFAULT 0,
    last_seen TEXT,
    registered_at TEXT
);
"""


class RegistryDB:
    """Async SQLite store for registered agents."""

    def __init__(self, db_path: str | Path = "/data/registry.db"):
        self.db_path = str(db_path)

    async def init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()
        log.info("registry_db_ready", path=self.db_path)

    async def upsert_agent(
        self,
        did: str,
        url: str,
        name: str = "",
        description: str = "",
        skills: list[dict] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        skills_json = json.dumps(skills or [])
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO registered_agents (did, url, name, description, skills_json, status, failures, last_seen, registered_at)
                VALUES (?, ?, ?, ?, ?, 'online', 0, ?, ?)
                ON CONFLICT(did) DO UPDATE SET
                    url = excluded.url,
                    name = excluded.name,
                    description = excluded.description,
                    skills_json = excluded.skills_json,
                    status = 'online',
                    failures = 0,
                    last_seen = excluded.last_seen
                """,
                (did, url, name, description, skills_json, now, now),
            )
            await db.commit()
        log.info("agent_upserted", did=did[:30], url=url)

    async def get_all_agents(self, status: str | None = None) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cursor = await db.execute(
                    "SELECT * FROM registered_agents WHERE status = ? ORDER BY last_seen DESC",
                    (status,),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM registered_agents ORDER BY last_seen DESC"
                )
            rows = await cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    async def search_agents(self, query: str) -> list[dict]:
        q = f"%{query}%"
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM registered_agents
                WHERE status = 'online'
                  AND (name LIKE ? OR description LIKE ? OR skills_json LIKE ?)
                ORDER BY last_seen DESC
                """,
                (q, q, q),
            )
            rows = await cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    async def get_agent_by_did(self, did: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM registered_agents WHERE did = ?", (did,)
            )
            row = await cursor.fetchone()
            return self._row_to_dict(row) if row else None

    async def delete_agent(self, did: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM registered_agents WHERE did = ?", (did,)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def increment_failure(self, did: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE registered_agents SET failures = failures + 1 WHERE did = ?",
                (did,),
            )
            cursor = await db.execute(
                "SELECT failures FROM registered_agents WHERE did = ?", (did,)
            )
            row = await cursor.fetchone()
            await db.commit()
            return row[0] if row else 0

    async def mark_offline(self, did: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE registered_agents SET status = 'offline' WHERE did = ?",
                (did,),
            )
            await db.commit()

    async def prune_dead(self, max_offline_hours: int = 24) -> int:
        """Remove agents that have been offline for too long."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM registered_agents
                WHERE status = 'offline'
                  AND last_seen < datetime('now', ? || ' hours')
                """,
                (f"-{max_offline_hours}",),
            )
            await db.commit()
            return cursor.rowcount

    async def count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM registered_agents")
            row = await cursor.fetchone()
            return row[0] if row else 0

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        if "skills_json" in d:
            try:
                d["skills"] = json.loads(d["skills_json"])
            except (json.JSONDecodeError, TypeError):
                d["skills"] = []
            del d["skills_json"]
        return d

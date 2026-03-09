"""Async SQLite storage — persistent state for agents, negotiations, matches, events."""

from __future__ import annotations

import json
import aiosqlite
import structlog
from pathlib import Path

log = structlog.get_logger()

SCHEMA_VERSION = 3


class StorageError(Exception):
    """Raised when a storage operation fails."""
    pass


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS agents (
    url TEXT PRIMARY KEY,
    did TEXT,
    name TEXT,
    card_json TEXT,
    public_key TEXT,
    last_seen TEXT,
    status TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS negotiations (
    id TEXT PRIMARY KEY,
    our_url TEXT,
    their_url TEXT,
    our_name TEXT,
    their_name TEXT,
    state TEXT,
    match_score REAL,
    match_reasons_json TEXT,
    messages_json TEXT,
    current_round INTEGER DEFAULT 0,
    max_rounds INTEGER DEFAULT 5,
    collaboration_summary TEXT DEFAULT '',
    owner_decision TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    our_url TEXT,
    their_url TEXT,
    their_name TEXT,
    score REAL,
    is_mutual INTEGER DEFAULT 0,
    skill_matches_json TEXT,
    their_skills_text TEXT,
    their_description TEXT,
    discovered_at TEXT,
    PRIMARY KEY (our_url, their_url)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,
    data_json TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    coordinator_url TEXT,
    coordinator_name TEXT,
    state TEXT DEFAULT 'draft',
    roles_json TEXT DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    negotiation_id TEXT NOT NULL,
    sender_url TEXT NOT NULL,
    sender_name TEXT NOT NULL,
    message TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'agent',
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_neg ON chat_messages(negotiation_id, timestamp);
"""


class Storage:
    """Async SQLite storage with schema migration support."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA_SQL)
        await self._db.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        await self._db.commit()
        log.info("storage_initialized", path=str(self.db_path))

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def health_check(self) -> dict:
        """Check if the database is accessible and responding."""
        if not self._db:
            return {"healthy": False, "error": "Database not initialized"}
        try:
            async with self._db.execute("SELECT 1") as cur:
                await cur.fetchone()
            async with self._db.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ) as cur:
                row = await cur.fetchone()
                version = row["value"] if row else "unknown"
            return {
                "healthy": True,
                "path": str(self.db_path),
                "schema_version": version,
            }
        except Exception as e:
            log.error("storage_health_check_failed", error=str(e))
            return {"healthy": False, "error": str(e)}

    # --- Agents ---

    async def save_agent(
        self, url: str, name: str | None = None, did: str | None = None,
        card_json: str | None = None, public_key: str | None = None,
        last_seen: str | None = None, status: str = "unknown",
    ) -> None:
        try:
            await self._db.execute(
                """INSERT INTO agents (url, did, name, card_json, public_key, last_seen, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                     did=COALESCE(excluded.did, did),
                     name=COALESCE(excluded.name, name),
                     card_json=COALESCE(excluded.card_json, card_json),
                     public_key=COALESCE(excluded.public_key, public_key),
                     last_seen=COALESCE(excluded.last_seen, last_seen),
                     status=excluded.status""",
                (url, did, name, card_json, public_key, last_seen, status),
            )
            await self._db.commit()
        except Exception as e:
            log.error("storage_save_agent_failed", url=url, error=str(e))
            raise StorageError(f"Failed to save agent {url}: {e}") from e

    async def get_agent(self, url: str) -> dict | None:
        try:
            async with self._db.execute("SELECT * FROM agents WHERE url = ?", (url,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None
        except Exception as e:
            log.error("storage_get_agent_failed", url=url, error=str(e))
            return None

    async def get_all_agents(self) -> list[dict]:
        try:
            async with self._db.execute("SELECT * FROM agents") as cur:
                return [dict(row) async for row in cur]
        except Exception as e:
            log.error("storage_get_all_agents_failed", error=str(e))
            return []

    async def get_agent_urls(self) -> list[str]:
        try:
            async with self._db.execute("SELECT url FROM agents") as cur:
                return [row["url"] async for row in cur]
        except Exception as e:
            log.error("storage_get_agent_urls_failed", error=str(e))
            return []

    # --- Negotiations ---

    async def save_negotiation(self, neg_dict: dict) -> None:
        try:
            await self._db.execute(
                """INSERT INTO negotiations
                   (id, our_url, their_url, our_name, their_name, state, match_score,
                    match_reasons_json, messages_json, current_round, max_rounds,
                    collaboration_summary, owner_decision, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     state=excluded.state,
                     messages_json=excluded.messages_json,
                     current_round=excluded.current_round,
                     collaboration_summary=excluded.collaboration_summary,
                     owner_decision=excluded.owner_decision,
                     updated_at=excluded.updated_at""",
                (
                    neg_dict["id"],
                    neg_dict.get("our_url", ""),
                    neg_dict.get("their_url", ""),
                    neg_dict.get("our_name", ""),
                    neg_dict.get("their_name", ""),
                    neg_dict["state"],
                    neg_dict.get("match_score", 0.0),
                    json.dumps(neg_dict.get("match_reasons", [])),
                    json.dumps(neg_dict.get("messages", [])),
                    neg_dict.get("current_round", 0),
                    neg_dict.get("max_rounds", 5),
                    neg_dict.get("collaboration_summary", ""),
                    neg_dict.get("owner_decision"),
                    neg_dict.get("created_at", ""),
                    neg_dict.get("updated_at", ""),
                ),
            )
            await self._db.commit()
        except Exception as e:
            log.error("storage_save_negotiation_failed", id=neg_dict.get("id"), error=str(e))
            raise StorageError(f"Failed to save negotiation: {e}") from e

    async def get_negotiation(self, neg_id: str) -> dict | None:
        try:
            async with self._db.execute(
                "SELECT * FROM negotiations WHERE id = ?", (neg_id,)
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["match_reasons"] = json.loads(d.pop("match_reasons_json", "[]"))
                d["messages"] = json.loads(d.pop("messages_json", "[]"))
                return d
        except Exception as e:
            log.error("storage_get_negotiation_failed", id=neg_id, error=str(e))
            return None

    async def get_all_negotiations(self) -> list[dict]:
        try:
            async with self._db.execute(
                "SELECT * FROM negotiations ORDER BY updated_at DESC"
            ) as cur:
                results = []
                async for row in cur:
                    d = dict(row)
                    d["match_reasons"] = json.loads(d.pop("match_reasons_json", "[]"))
                    d["messages"] = json.loads(d.pop("messages_json", "[]"))
                    results.append(d)
                return results
        except Exception as e:
            log.error("storage_get_all_negotiations_failed", error=str(e))
            return []

    # --- Matches ---

    async def save_match(
        self, our_url: str, their_url: str, their_name: str, score: float,
        is_mutual: bool, skill_matches_json: str = "[]",
        their_skills_text: str = "", their_description: str = "",
        discovered_at: str = "",
    ) -> None:
        try:
            await self._db.execute(
                """INSERT INTO matches
                   (our_url, their_url, their_name, score, is_mutual, skill_matches_json,
                    their_skills_text, their_description, discovered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(our_url, their_url) DO UPDATE SET
                     their_name=excluded.their_name,
                     score=excluded.score,
                     is_mutual=excluded.is_mutual,
                     skill_matches_json=excluded.skill_matches_json,
                     their_skills_text=excluded.their_skills_text,
                     their_description=excluded.their_description,
                     discovered_at=excluded.discovered_at""",
                (our_url, their_url, their_name, score, int(is_mutual),
                 skill_matches_json, their_skills_text, their_description, discovered_at),
            )
            await self._db.commit()
        except Exception as e:
            log.error("storage_save_match_failed", our_url=our_url, their_url=their_url, error=str(e))
            raise StorageError(f"Failed to save match: {e}") from e

    async def get_all_matches(self) -> list[dict]:
        try:
            async with self._db.execute(
                "SELECT * FROM matches ORDER BY score DESC"
            ) as cur:
                results = []
                async for row in cur:
                    d = dict(row)
                    d["is_mutual"] = bool(d["is_mutual"])
                    d["skill_matches"] = json.loads(d.pop("skill_matches_json", "[]"))
                    results.append(d)
                return results
        except Exception as e:
            log.error("storage_get_all_matches_failed", error=str(e))
            return []

    # --- Projects ---

    async def save_project(self, project_dict: dict) -> None:
        try:
            await self._db.execute(
                """INSERT INTO projects
                   (id, name, description, coordinator_url, coordinator_name,
                    state, roles_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name,
                     description=excluded.description,
                     state=excluded.state,
                     roles_json=excluded.roles_json,
                     updated_at=excluded.updated_at""",
                (
                    project_dict["id"],
                    project_dict.get("name", ""),
                    project_dict.get("description", ""),
                    project_dict.get("coordinator_url", ""),
                    project_dict.get("coordinator_name", ""),
                    project_dict.get("state", "draft"),
                    json.dumps(project_dict.get("roles", [])),
                    project_dict.get("created_at", ""),
                    project_dict.get("updated_at", ""),
                ),
            )
            await self._db.commit()
        except Exception as e:
            log.error("storage_save_project_failed", id=project_dict.get("id"), error=str(e))
            raise StorageError(f"Failed to save project: {e}") from e

    async def get_project(self, project_id: str) -> dict | None:
        try:
            async with self._db.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["roles"] = json.loads(d.pop("roles_json", "[]"))
                return d
        except Exception as e:
            log.error("storage_get_project_failed", id=project_id, error=str(e))
            return None

    async def get_all_projects(self) -> list[dict]:
        try:
            async with self._db.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ) as cur:
                results = []
                async for row in cur:
                    d = dict(row)
                    d["roles"] = json.loads(d.pop("roles_json", "[]"))
                    results.append(d)
                return results
        except Exception as e:
            log.error("storage_get_all_projects_failed", error=str(e))
            return []

    async def delete_project(self, project_id: str) -> bool:
        try:
            cur = await self._db.execute(
                "DELETE FROM projects WHERE id = ?", (project_id,)
            )
            await self._db.commit()
            return cur.rowcount > 0
        except Exception as e:
            log.error("storage_delete_project_failed", id=project_id, error=str(e))
            raise StorageError(f"Failed to delete project: {e}") from e

    # --- Negotiation History (Phase 6.7) ---

    async def get_negotiation_history_by_peer(self, peer_url: str) -> dict:
        """Return success/failure counts for negotiations with a specific peer.

        Returns dict with keys: successful, failed, total.
        """
        try:
            async with self._db.execute(
                """SELECT state, COUNT(*) as cnt FROM negotiations
                   WHERE their_url = ? GROUP BY state""",
                (peer_url,),
            ) as cur:
                successful = 0
                failed = 0
                async for row in cur:
                    state = row["state"]
                    count = row["cnt"]
                    if state in ("confirmed", "accepted"):
                        successful += count
                    elif state in ("rejected", "declined", "timeout"):
                        failed += count
                return {
                    "successful": successful,
                    "failed": failed,
                    "total": successful + failed,
                }
        except Exception as e:
            log.error("storage_get_negotiation_history_failed", peer=peer_url, error=str(e))
            return {"successful": 0, "failed": 0, "total": 0}

    async def get_active_negotiation_count(self, peer_url: str) -> int:
        """Count active (non-terminal) negotiations with a specific peer."""
        try:
            async with self._db.execute(
                """SELECT COUNT(*) as cnt FROM negotiations
                   WHERE their_url = ? AND state NOT IN
                   ('confirmed', 'rejected', 'declined', 'timeout')""",
                (peer_url,),
            ) as cur:
                row = await cur.fetchone()
                return row["cnt"] if row else 0
        except Exception as e:
            log.error("storage_get_active_neg_count_failed", peer=peer_url, error=str(e))
            return 0

    # --- Events ---

    async def save_event(self, event_type: str, data: dict, timestamp: str) -> int:
        try:
            cur = await self._db.execute(
                "INSERT INTO events (type, data_json, timestamp) VALUES (?, ?, ?)",
                (event_type, json.dumps(data), timestamp),
            )
            await self._db.commit()
            return cur.lastrowid
        except Exception as e:
            log.error("storage_save_event_failed", type=event_type, error=str(e))
            raise StorageError(f"Failed to save event: {e}") from e

    async def get_recent_events(self, count: int = 50, event_type: str | None = None) -> list[dict]:
        try:
            if event_type:
                sql = "SELECT * FROM events WHERE type = ? ORDER BY id DESC LIMIT ?"
                params = (event_type, count)
            else:
                sql = "SELECT * FROM events ORDER BY id DESC LIMIT ?"
                params = (count,)

            async with self._db.execute(sql, params) as cur:
                results = []
                async for row in cur:
                    d = dict(row)
                    d["data"] = json.loads(d.pop("data_json", "{}"))
                    results.append(d)
                results.reverse()  # Chronological order
                return results
        except Exception as e:
            log.error("storage_get_recent_events_failed", error=str(e))
            return []

    # --- Chat Messages (Phase 9) ---

    async def save_chat_message(self, msg: dict) -> None:
        """Persist a single chat message. Idempotent (INSERT OR IGNORE)."""
        try:
            await self._db.execute(
                """INSERT OR IGNORE INTO chat_messages
                   (id, negotiation_id, sender_url, sender_name, message, message_type, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg["id"],
                    msg["negotiation_id"],
                    msg["sender_url"],
                    msg["sender_name"],
                    msg["message"],
                    msg.get("message_type", "agent"),
                    msg["timestamp"],
                ),
            )
            await self._db.commit()
        except Exception as e:
            log.error("storage_save_chat_message_failed", id=msg.get("id"), error=str(e))
            raise StorageError(f"Failed to save chat message: {e}") from e

    async def get_chat_messages(self, negotiation_id: str, limit: int = 100) -> list[dict]:
        """Get chat messages for a negotiation, ordered chronologically."""
        try:
            async with self._db.execute(
                "SELECT * FROM chat_messages WHERE negotiation_id = ? ORDER BY timestamp ASC LIMIT ?",
                (negotiation_id, limit),
            ) as cur:
                return [dict(row) async for row in cur]
        except Exception as e:
            log.error("storage_get_chat_messages_failed", negotiation_id=negotiation_id, error=str(e))
            return []

    async def get_chat_message_count(self, negotiation_id: str) -> int:
        """Count chat messages for a negotiation."""
        try:
            async with self._db.execute(
                "SELECT COUNT(*) as cnt FROM chat_messages WHERE negotiation_id = ?",
                (negotiation_id,),
            ) as cur:
                row = await cur.fetchone()
                return row["cnt"] if row else 0
        except Exception as e:
            log.error("storage_get_chat_count_failed", negotiation_id=negotiation_id, error=str(e))
            return 0

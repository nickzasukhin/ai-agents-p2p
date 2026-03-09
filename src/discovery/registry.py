"""Static Registry — stores and retrieves known agent URLs.

Phase 1-2: Simple JSON file-based registry.
Phase 5: Will be replaced by Gossip/Kademlia DHT.
"""

import json
import structlog
from dataclasses import dataclass, field
from pathlib import Path

log = structlog.get_logger()


@dataclass
class AgentRecord:
    """A known agent in the registry."""
    url: str
    name: str | None = None
    last_seen: str | None = None
    status: str = "unknown"  # unknown, online, offline


class StaticRegistry:
    """File-backed registry of known agent URLs.

    Stores a simple JSON list of agent URLs that this node should
    try to discover. In later phases, this will be replaced by
    dynamic peer discovery (gossip, DHT).
    """

    def __init__(self, registry_path: str | Path | None = None):
        self.registry_path = Path(registry_path) if registry_path else None
        self._agents: dict[str, AgentRecord] = {}  # url -> AgentRecord

    def load(self) -> None:
        """Load registry from JSON file."""
        if not self.registry_path or not self.registry_path.exists():
            log.info("registry_no_file", path=str(self.registry_path))
            return

        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            agents = data if isinstance(data, list) else data.get("agents", [])

            for entry in agents:
                if isinstance(entry, str):
                    url = entry
                    self._agents[url] = AgentRecord(url=url)
                elif isinstance(entry, dict):
                    url = entry["url"]
                    self._agents[url] = AgentRecord(
                        url=url,
                        name=entry.get("name"),
                        last_seen=entry.get("last_seen"),
                        status=entry.get("status", "unknown"),
                    )

            log.info("registry_loaded", count=len(self._agents), path=str(self.registry_path))
        except Exception as e:
            log.error("registry_load_error", error=str(e))

    def save(self) -> None:
        """Save registry to JSON file."""
        if not self.registry_path:
            return

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "url": rec.url,
                "name": rec.name,
                "last_seen": rec.last_seen,
                "status": rec.status,
            }
            for rec in self._agents.values()
        ]
        self.registry_path.write_text(
            json.dumps({"agents": data}, indent=2),
            encoding="utf-8",
        )
        log.info("registry_saved", count=len(data))

    def add(self, url: str, name: str | None = None) -> None:
        """Add an agent URL to the registry."""
        if url not in self._agents:
            self._agents[url] = AgentRecord(url=url, name=name)
            log.info("registry_agent_added", url=url, name=name)

    def remove(self, url: str) -> None:
        """Remove an agent URL from the registry."""
        self._agents.pop(url, None)

    def update_status(self, url: str, status: str, name: str | None = None) -> None:
        """Update the status of a known agent."""
        if url in self._agents:
            self._agents[url].status = status
            if name:
                self._agents[url].name = name
            from datetime import datetime, timezone
            self._agents[url].last_seen = datetime.now(timezone.utc).isoformat()

    def get_all_urls(self) -> list[str]:
        """Return all known agent URLs."""
        return list(self._agents.keys())

    def get_online_urls(self) -> list[str]:
        """Return only online agent URLs."""
        return [url for url, rec in self._agents.items() if rec.status == "online"]

    def get_all_records(self) -> list[AgentRecord]:
        """Return all agent records."""
        return list(self._agents.values())

    def get_agent_status(self, url: str) -> str:
        """Return the status of an agent, or 'unknown' if not in registry."""
        rec = self._agents.get(url)
        return rec.status if rec else "unknown"

    def get_last_seen(self, url: str) -> str | None:
        """Return the last_seen timestamp for an agent, or None."""
        rec = self._agents.get(url)
        return rec.last_seen if rec else None

    def __len__(self) -> int:
        return len(self._agents)

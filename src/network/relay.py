"""HTTP relay for fully NAT'd agents.

A publicly reachable agent can act as a relay node. NAT'd agents register
with the relay and poll for messages.

Architecture:
  - Relay node exposes POST /relay/register, POST /relay/forward/{did},
    GET /relay/messages/{did}
  - NAT'd agent registers its DID and polls for incoming messages
  - Messages are stored in-memory with TTL and max queue size
  - This is the last-resort connectivity option when direct connections
    and tunnels are both unavailable
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()

DEFAULT_MESSAGE_TTL = 300  # 5 minutes
MAX_PENDING_MESSAGES = 50


@dataclass
class RelayMessage:
    """A message waiting for pickup by a NAT'd agent."""

    sender_url: str
    body: dict
    created_at: float = field(default_factory=time.time)


class RelayStore:
    """In-memory store for relay messages.

    Manages agent registration and message queuing/dequeuing
    with TTL expiration and queue size limits.
    """

    def __init__(
        self,
        ttl: float = DEFAULT_MESSAGE_TTL,
        max_messages: int = MAX_PENDING_MESSAGES,
    ):
        self.ttl = ttl
        self.max_messages = max_messages
        # agent_did -> list of pending messages
        self._messages: dict[str, list[RelayMessage]] = {}
        # agent_did -> registration info
        self._registered: dict[str, dict] = {}

    def register(self, agent_did: str, agent_info: dict) -> None:
        """Register a NAT'd agent with this relay."""
        self._registered[agent_did] = {
            **agent_info,
            "registered_at": time.time(),
        }
        if agent_did not in self._messages:
            self._messages[agent_did] = []
        log.info("relay_registered", did=agent_did[:30])

    def unregister(self, agent_did: str) -> bool:
        """Unregister an agent from this relay."""
        if agent_did in self._registered:
            del self._registered[agent_did]
            self._messages.pop(agent_did, None)
            log.info("relay_unregistered", did=agent_did[:30])
            return True
        return False

    def is_registered(self, agent_did: str) -> bool:
        """Check if an agent is registered."""
        return agent_did in self._registered

    def get_registration(self, agent_did: str) -> dict | None:
        """Get registration info for an agent."""
        return self._registered.get(agent_did)

    def list_registered(self) -> list[dict]:
        """List all registered agents."""
        return [
            {"did": did, **info}
            for did, info in self._registered.items()
        ]

    def enqueue(self, agent_did: str, sender_url: str, body: dict) -> bool:
        """Enqueue a message for a registered agent.

        Returns False if agent not registered or queue is full.
        """
        if agent_did not in self._registered:
            return False

        msgs = self._messages.setdefault(agent_did, [])

        # Evict expired messages
        now = time.time()
        msgs[:] = [m for m in msgs if now - m.created_at < self.ttl]

        if len(msgs) >= self.max_messages:
            log.warning("relay_queue_full", did=agent_did[:30])
            return False

        msgs.append(RelayMessage(sender_url=sender_url, body=body))
        return True

    def dequeue(self, agent_did: str) -> list[dict]:
        """Dequeue all pending messages for an agent.

        Returns list of message dicts and clears the queue.
        """
        msgs = self._messages.get(agent_did, [])
        now = time.time()
        valid = [
            {"sender_url": m.sender_url, "body": m.body}
            for m in msgs
            if now - m.created_at < self.ttl
        ]
        self._messages[agent_did] = []
        return valid

    def get_stats(self) -> dict:
        """Return relay statistics."""
        return {
            "registered_agents": len(self._registered),
            "pending_messages": sum(len(v) for v in self._messages.values()),
        }

"""Negotiation Manager — orchestrates multiple concurrent negotiations."""

from __future__ import annotations

import structlog
from src.negotiation.states import Negotiation, NegotiationState, NegotiationMessage
from src.negotiation.engine import NegotiationEngine
from src.matching.engine import AgentMatch
from src.notification.events import EventBus, EventType

log = structlog.get_logger()


class NegotiationManager:
    """Manages all active negotiations for a single agent node.

    Tracks negotiations by ID, handles incoming A2A negotiation messages,
    initiates new negotiations from matches, and emits events for AG-UI.
    """

    def __init__(
        self,
        engine: NegotiationEngine,
        event_bus: EventBus,
        storage=None,
        auto_negotiate: bool = True,
        max_concurrent: int = 10,
    ):
        self.engine = engine
        self.event_bus = event_bus
        self.storage = storage  # Optional Storage instance for persistence
        self.auto_negotiate = auto_negotiate
        self.max_concurrent = max_concurrent
        self._negotiations: dict[str, Negotiation] = {}  # id -> Negotiation
        self._by_peer: dict[str, str] = {}  # peer_url -> negotiation_id

    async def load_from_storage(self) -> int:
        """Load negotiations from SQLite on startup. Returns count loaded."""
        if not self.storage:
            return 0
        rows = await self.storage.get_all_negotiations()
        for row in rows:
            neg = Negotiation(
                id=row["id"],
                our_url=row.get("our_url", ""),
                their_url=row.get("their_url", ""),
                our_name=row.get("our_name", ""),
                their_name=row.get("their_name", ""),
                state=NegotiationState(row["state"]),
                match_score=row.get("match_score", 0.0),
                match_reasons=row.get("match_reasons", []),
                current_round=row.get("current_round", 0),
                max_rounds=row.get("max_rounds", 5),
                collaboration_summary=row.get("collaboration_summary", ""),
                owner_decision=row.get("owner_decision"),
                created_at=row.get("created_at", ""),
                updated_at=row.get("updated_at", ""),
            )
            # Restore messages
            for m in row.get("messages", []):
                neg.messages.append(NegotiationMessage(
                    sender=m["sender"],
                    content=m["content"],
                    round=m["round"],
                    timestamp=m.get("timestamp", ""),
                    message_type=m.get("type", "proposal"),
                ))
            self._negotiations[neg.id] = neg
            if neg.their_url:
                self._by_peer[neg.their_url] = neg.id
        log.info("negotiations_loaded_from_storage", count=len(rows))
        return len(rows)

    async def _persist(self, neg: Negotiation) -> None:
        """Persist negotiation to SQLite if storage is available."""
        if not self.storage:
            return
        d = neg.to_dict()
        d["our_url"] = neg.our_url
        d["their_url"] = neg.their_url
        d["match_reasons"] = neg.match_reasons
        await self.storage.save_negotiation(d)

    async def start_negotiation(self, match: AgentMatch) -> Negotiation:
        """Start a new negotiation from a match result."""
        # Check if already negotiating with this peer
        if match.agent_url in self._by_peer:
            existing_id = self._by_peer[match.agent_url]
            existing = self._negotiations.get(existing_id)
            if existing and not existing.is_terminal:
                log.info("negotiation_already_active", peer=match.agent_url, id=existing_id)
                return existing

        # Check concurrency limit
        active_count = sum(1 for n in self._negotiations.values() if not n.is_terminal)
        if active_count >= self.max_concurrent:
            log.warning("max_negotiations_reached", max=self.max_concurrent)
            raise RuntimeError(f"Maximum concurrent negotiations ({self.max_concurrent}) reached")

        # Create negotiation
        neg = Negotiation(
            our_url=self.engine.our_url,
            their_url=match.agent_url,
            our_name=self.engine.our_name,
            their_name=match.agent_name,
            match_score=match.overall_score,
            match_reasons=[
                f"{sm.our_text} ↔ {sm.their_text}" for sm in match.skill_matches[:5]
            ],
        )

        self._negotiations[neg.id] = neg
        self._by_peer[match.agent_url] = neg.id

        # Emit match found event
        self.event_bus.emit(EventType.MATCH_FOUND, {
            "negotiation_id": neg.id,
            "their_name": neg.their_name,
            "their_url": neg.their_url,
            "match_score": neg.match_score,
        })

        # Generate and record opening proposal
        proposal = self.engine.initiate_negotiation(neg)

        self.event_bus.emit(EventType.NEGOTIATION_STARTED, {
            "negotiation_id": neg.id,
            "their_name": neg.their_name,
            "proposal": proposal,
        })

        await self._persist(neg)

        log.info(
            "negotiation_started",
            id=neg.id,
            peer=match.agent_name,
            score=match.overall_score,
        )

        return neg

    async def handle_incoming_message(
        self,
        sender_url: str,
        sender_name: str,
        message: str,
        negotiation_id: str | None = None,
    ) -> dict:
        """Handle an incoming negotiation message from another agent.

        Returns response dict to send back via A2A.
        """
        # Find or create negotiation
        neg = None

        if negotiation_id and negotiation_id in self._negotiations:
            neg = self._negotiations[negotiation_id]
        elif sender_url in self._by_peer:
            neg = self._negotiations.get(self._by_peer[sender_url])

        if neg is None:
            # New negotiation initiated by the other agent
            neg = Negotiation(
                our_url=self.engine.our_url,
                their_url=sender_url,
                our_name=self.engine.our_name,
                their_name=sender_name,
                match_score=0.5,  # Unknown match score from their side
            )
            neg.state = NegotiationState.PROPOSED  # They already proposed
            self._negotiations[neg.id] = neg
            self._by_peer[sender_url] = neg.id

            self.event_bus.emit(EventType.NEGOTIATION_RECEIVED, {
                "negotiation_id": neg.id,
                "their_name": sender_name,
                "their_url": sender_url,
                "proposal": message,
            })

        if neg.is_terminal:
            return {
                "negotiation_id": neg.id,
                "action": "ended",
                "response_text": f"This negotiation has already ended (state: {neg.state.value}).",
                "state": neg.state.value,
            }

        # Process the message
        result = self.engine.process_incoming(neg, message, sender_url)
        result["negotiation_id"] = neg.id

        # Emit appropriate event
        if result["action"] == "accepted":
            self.event_bus.emit(EventType.NEGOTIATION_ACCEPTED, {
                "negotiation_id": neg.id,
                "their_name": neg.their_name,
                "summary": result.get("summary", ""),
            })
        elif result["action"] == "counter":
            self.event_bus.emit(EventType.NEGOTIATION_UPDATE, {
                "negotiation_id": neg.id,
                "their_name": neg.their_name,
                "round": neg.current_round,
                "action": "counter",
            })
        elif result["action"] == "rejected":
            self.event_bus.emit(EventType.NEGOTIATION_REJECTED, {
                "negotiation_id": neg.id,
                "their_name": neg.their_name,
                "reasoning": result.get("reasoning", ""),
            })
        elif result["action"] == "timeout":
            self.event_bus.emit(EventType.NEGOTIATION_TIMEOUT, {
                "negotiation_id": neg.id,
                "their_name": neg.their_name,
            })

        await self._persist(neg)

        log.info(
            "negotiation_incoming_handled",
            id=neg.id,
            from_=sender_name,
            action=result["action"],
            round=neg.current_round,
        )

        return result

    async def owner_decision(self, negotiation_id: str, decision: str) -> dict:
        """Process owner's decision on a negotiation.

        Args:
            negotiation_id: ID of the negotiation
            decision: "approve" or "reject"
        """
        neg = self._negotiations.get(negotiation_id)
        if not neg:
            return {"error": f"Negotiation {negotiation_id} not found"}

        if neg.state != NegotiationState.OWNER_REVIEW:
            return {"error": f"Negotiation is in state {neg.state.value}, not owner_review"}

        neg.owner_decision = decision

        if decision == "approve":
            neg.transition(NegotiationState.CONFIRMED)
            self.event_bus.emit(EventType.MATCH_CONFIRMED, {
                "negotiation_id": neg.id,
                "their_name": neg.their_name,
                "summary": neg.collaboration_summary,
            })
            await self._persist(neg)
            log.info("negotiation_confirmed", id=neg.id, peer=neg.their_name)
            return {
                "status": "confirmed",
                "negotiation_id": neg.id,
                "summary": neg.collaboration_summary,
            }
        else:
            neg.transition(NegotiationState.DECLINED)
            self.event_bus.emit(EventType.MATCH_DECLINED, {
                "negotiation_id": neg.id,
                "their_name": neg.their_name,
            })
            await self._persist(neg)
            log.info("negotiation_declined", id=neg.id, peer=neg.their_name)
            return {
                "status": "declined",
                "negotiation_id": neg.id,
            }

    def get_negotiation(self, negotiation_id: str) -> Negotiation | None:
        return self._negotiations.get(negotiation_id)

    def get_all_negotiations(self) -> list[Negotiation]:
        return list(self._negotiations.values())

    def get_active_negotiations(self) -> list[Negotiation]:
        return [n for n in self._negotiations.values() if not n.is_terminal]

    def get_pending_approvals(self) -> list[Negotiation]:
        return [
            n for n in self._negotiations.values()
            if n.state == NegotiationState.OWNER_REVIEW
        ]

    def get_negotiation_for_peer(self, peer_url: str) -> Negotiation | None:
        nid = self._by_peer.get(peer_url)
        return self._negotiations.get(nid) if nid else None

    def get_status(self) -> dict:
        all_negs = self.get_all_negotiations()
        return {
            "total": len(all_negs),
            "active": sum(1 for n in all_negs if not n.is_terminal),
            "pending_approval": sum(1 for n in all_negs if n.state == NegotiationState.OWNER_REVIEW),
            "confirmed": sum(1 for n in all_negs if n.state == NegotiationState.CONFIRMED),
            "rejected": sum(1 for n in all_negs if n.state in {NegotiationState.REJECTED, NegotiationState.DECLINED}),
        }

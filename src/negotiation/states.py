"""Negotiation State Machine — defines states, transitions, and negotiation data."""

from __future__ import annotations

import uuid
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class NegotiationState(str, Enum):
    """States of a negotiation between two agents."""
    INIT = "init"                  # Match found, negotiation not yet started
    PROPOSED = "proposed"          # One agent sent initial proposal
    COUNTER = "counter"            # Other agent sent counter-proposal
    EVALUATING = "evaluating"      # LLM is evaluating the proposal
    ACCEPTED = "accepted"          # Both agents agreed
    REJECTED = "rejected"          # One agent rejected
    TIMEOUT = "timeout"            # Max rounds exceeded
    OWNER_REVIEW = "owner_review"  # Waiting for owner approval
    CONFIRMED = "confirmed"        # Owner approved the collaboration
    DECLINED = "declined"          # Owner declined the collaboration


# Valid state transitions
TRANSITIONS: dict[NegotiationState, set[NegotiationState]] = {
    NegotiationState.INIT: {NegotiationState.PROPOSED},
    NegotiationState.PROPOSED: {NegotiationState.COUNTER, NegotiationState.EVALUATING},
    NegotiationState.COUNTER: {NegotiationState.PROPOSED, NegotiationState.EVALUATING},
    NegotiationState.EVALUATING: {
        NegotiationState.ACCEPTED,
        NegotiationState.REJECTED,
        NegotiationState.COUNTER,
        NegotiationState.TIMEOUT,
    },
    NegotiationState.ACCEPTED: {NegotiationState.OWNER_REVIEW},
    NegotiationState.OWNER_REVIEW: {NegotiationState.CONFIRMED, NegotiationState.DECLINED},
    NegotiationState.REJECTED: set(),   # Terminal
    NegotiationState.TIMEOUT: set(),    # Terminal
    NegotiationState.CONFIRMED: set(),  # Terminal
    NegotiationState.DECLINED: set(),   # Terminal
}

TERMINAL_STATES = {
    NegotiationState.REJECTED,
    NegotiationState.TIMEOUT,
    NegotiationState.CONFIRMED,
    NegotiationState.DECLINED,
}


@dataclass
class NegotiationMessage:
    """A single message exchanged during negotiation."""
    sender: str          # Agent URL or name
    content: str         # Message text
    round: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    message_type: str = "proposal"  # proposal, counter, accept, reject, info


@dataclass
class Negotiation:
    """Full state of a negotiation between two agents."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    our_url: str = ""
    their_url: str = ""
    our_name: str = ""
    their_name: str = ""
    state: NegotiationState = NegotiationState.INIT
    match_score: float = 0.0
    match_reasons: list[str] = field(default_factory=list)
    messages: list[NegotiationMessage] = field(default_factory=list)
    current_round: int = 0
    max_rounds: int = 5
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    collaboration_summary: str = ""  # Final agreed collaboration description
    owner_decision: str | None = None  # "approve" or "reject"

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_our_turn(self) -> bool:
        """Check if it's our turn to respond."""
        if not self.messages:
            return True  # We initiate
        return self.messages[-1].sender != self.our_url

    def can_transition_to(self, new_state: NegotiationState) -> bool:
        return new_state in TRANSITIONS.get(self.state, set())

    def transition(self, new_state: NegotiationState) -> None:
        if not self.can_transition_to(new_state):
            raise ValueError(
                f"Invalid transition: {self.state.value} → {new_state.value}. "
                f"Allowed: {[s.value for s in TRANSITIONS.get(self.state, set())]}"
            )
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_message(self, sender: str, content: str, message_type: str = "proposal") -> None:
        self.current_round += 1
        self.messages.append(NegotiationMessage(
            sender=sender,
            content=content,
            round=self.current_round,
            message_type=message_type,
        ))
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "our_name": self.our_name,
            "their_name": self.their_name,
            "their_url": self.their_url,
            "state": self.state.value,
            "match_score": round(self.match_score, 4),
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "is_terminal": self.is_terminal,
            "collaboration_summary": self.collaboration_summary,
            "owner_decision": self.owner_decision,
            "messages": [
                {
                    "sender": m.sender,
                    "content": m.content,
                    "round": m.round,
                    "type": m.message_type,
                    "timestamp": m.timestamp,
                }
                for m in self.messages
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

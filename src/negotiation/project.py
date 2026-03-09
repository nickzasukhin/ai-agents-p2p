"""Project Data Model — multi-agent collaboration overlay on 1:1 negotiations."""

from __future__ import annotations

import uuid
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


class ProjectState(str, Enum):
    """States of a multi-agent collaboration project."""
    DRAFT = "draft"              # Just created, roles defined but no recruiting yet
    RECRUITING = "recruiting"    # Actively looking for agents to fill roles
    PARTIAL = "partial"          # Some roles filled (confirmed), others still open
    ACTIVE = "active"            # All roles filled, project is running
    COMPLETED = "completed"      # Project finished successfully
    STALLED = "stalled"          # One or more agents declined/rejected — need replacement


# Valid state transitions
PROJECT_TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.DRAFT: {ProjectState.RECRUITING},
    ProjectState.RECRUITING: {ProjectState.PARTIAL, ProjectState.ACTIVE, ProjectState.STALLED},
    ProjectState.PARTIAL: {ProjectState.ACTIVE, ProjectState.STALLED},
    ProjectState.STALLED: {ProjectState.RECRUITING},  # Find replacement
    ProjectState.ACTIVE: {ProjectState.COMPLETED},
    ProjectState.COMPLETED: set(),  # Terminal
}

PROJECT_TERMINAL_STATES = {ProjectState.COMPLETED}


@dataclass
class ProjectRole:
    """A role within a project, linked to a 1:1 negotiation."""
    role_name: str           # "UI Designer", "Backend Dev"
    description: str         # What this role does in the project
    agent_url: str = ""      # Filled when agent assigned
    agent_name: str = ""     # Filled when agent assigned
    negotiation_id: str = "" # Link to existing 1:1 negotiation
    status: str = "open"     # open, negotiating, confirmed, rejected

    def to_dict(self) -> dict:
        return {
            "role_name": self.role_name,
            "description": self.description,
            "agent_url": self.agent_url,
            "agent_name": self.agent_name,
            "negotiation_id": self.negotiation_id,
            "status": self.status,
        }

    @staticmethod
    def from_dict(d: dict) -> ProjectRole:
        return ProjectRole(
            role_name=d.get("role_name", ""),
            description=d.get("description", ""),
            agent_url=d.get("agent_url", ""),
            agent_name=d.get("agent_name", ""),
            negotiation_id=d.get("negotiation_id", ""),
            status=d.get("status", "open"),
        )


@dataclass
class Project:
    """A multi-agent collaboration project — overlay on existing 1:1 negotiations."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    coordinator_url: str = ""
    coordinator_name: str = ""
    state: ProjectState = ProjectState.DRAFT
    roles: list[ProjectRole] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_terminal(self) -> bool:
        return self.state in PROJECT_TERMINAL_STATES

    @property
    def filled_roles(self) -> list[ProjectRole]:
        """Roles with confirmed agents."""
        return [r for r in self.roles if r.status == "confirmed"]

    @property
    def open_roles(self) -> list[ProjectRole]:
        """Roles still looking for agents."""
        return [r for r in self.roles if r.status == "open"]

    @property
    def progress(self) -> float:
        """Fraction of roles filled (0.0 to 1.0)."""
        if not self.roles:
            return 0.0
        return len(self.filled_roles) / len(self.roles)

    def can_transition_to(self, new_state: ProjectState) -> bool:
        return new_state in PROJECT_TRANSITIONS.get(self.state, set())

    def transition(self, new_state: ProjectState) -> None:
        if not self.can_transition_to(new_state):
            raise ValueError(
                f"Invalid project transition: {self.state.value} -> {new_state.value}. "
                f"Allowed: {[s.value for s in PROJECT_TRANSITIONS.get(self.state, set())]}"
            )
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "coordinator_url": self.coordinator_url,
            "coordinator_name": self.coordinator_name,
            "state": self.state.value,
            "roles": [r.to_dict() for r in self.roles],
            "progress": round(self.progress, 2),
            "filled_roles": len(self.filled_roles),
            "total_roles": len(self.roles),
            "open_roles": len(self.open_roles),
            "is_terminal": self.is_terminal,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(d: dict) -> Project:
        """Reconstruct a Project from a dict (e.g., from storage)."""
        return Project(
            id=d.get("id", str(uuid.uuid4())[:8]),
            name=d.get("name", ""),
            description=d.get("description", ""),
            coordinator_url=d.get("coordinator_url", ""),
            coordinator_name=d.get("coordinator_name", ""),
            state=ProjectState(d.get("state", "draft")),
            roles=[ProjectRole.from_dict(r) for r in d.get("roles", [])],
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )

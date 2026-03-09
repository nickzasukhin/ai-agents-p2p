"""Tests for Project data model — state machine, transitions, serialization."""

import pytest
from src.negotiation.project import (
    Project, ProjectRole, ProjectState,
    PROJECT_TRANSITIONS, PROJECT_TERMINAL_STATES,
)


# ── ProjectState Enum ─────────────────────────────────────────

class TestProjectState:
    def test_all_states_defined(self):
        states = {s.value for s in ProjectState}
        assert states == {"draft", "recruiting", "partial", "active", "completed", "stalled"}

    def test_state_is_str(self):
        assert isinstance(ProjectState.DRAFT, str)
        assert ProjectState.DRAFT == "draft"


# ── PROJECT_TRANSITIONS ──────────────────────────────────────

class TestProjectTransitions:
    def test_draft_can_transition_to_recruiting(self):
        assert ProjectState.RECRUITING in PROJECT_TRANSITIONS[ProjectState.DRAFT]

    def test_recruiting_transitions(self):
        allowed = PROJECT_TRANSITIONS[ProjectState.RECRUITING]
        assert ProjectState.PARTIAL in allowed
        assert ProjectState.ACTIVE in allowed
        assert ProjectState.STALLED in allowed

    def test_partial_transitions(self):
        allowed = PROJECT_TRANSITIONS[ProjectState.PARTIAL]
        assert ProjectState.ACTIVE in allowed
        assert ProjectState.STALLED in allowed

    def test_stalled_can_go_back_to_recruiting(self):
        assert ProjectState.RECRUITING in PROJECT_TRANSITIONS[ProjectState.STALLED]

    def test_active_can_complete(self):
        assert ProjectState.COMPLETED in PROJECT_TRANSITIONS[ProjectState.ACTIVE]

    def test_completed_is_terminal(self):
        assert PROJECT_TRANSITIONS[ProjectState.COMPLETED] == set()
        assert ProjectState.COMPLETED in PROJECT_TERMINAL_STATES

    def test_all_states_have_transitions(self):
        for state in ProjectState:
            assert state in PROJECT_TRANSITIONS


# ── ProjectRole ──────────────────────────────────────────────

class TestProjectRole:
    def test_default_values(self):
        role = ProjectRole(role_name="Designer", description="UI work")
        assert role.role_name == "Designer"
        assert role.status == "open"
        assert role.agent_url == ""
        assert role.negotiation_id == ""

    def test_to_dict(self):
        role = ProjectRole(
            role_name="Backend Dev",
            description="API development",
            agent_url="http://localhost:9001",
            agent_name="Alice",
            negotiation_id="abc123",
            status="confirmed",
        )
        d = role.to_dict()
        assert d["role_name"] == "Backend Dev"
        assert d["agent_name"] == "Alice"
        assert d["status"] == "confirmed"

    def test_from_dict(self):
        d = {
            "role_name": "ML Engineer",
            "description": "Build models",
            "agent_url": "http://localhost:9002",
            "status": "negotiating",
        }
        role = ProjectRole.from_dict(d)
        assert role.role_name == "ML Engineer"
        assert role.status == "negotiating"
        assert role.agent_url == "http://localhost:9002"

    def test_from_dict_defaults(self):
        role = ProjectRole.from_dict({})
        assert role.role_name == ""
        assert role.status == "open"

    def test_roundtrip(self):
        original = ProjectRole(
            role_name="DevOps", description="CI/CD",
            agent_url="http://peer:9003", agent_name="Bob",
            negotiation_id="xyz", status="confirmed",
        )
        restored = ProjectRole.from_dict(original.to_dict())
        assert restored.role_name == original.role_name
        assert restored.agent_name == original.agent_name
        assert restored.status == original.status


# ── Project ──────────────────────────────────────────────────

class TestProject:
    def test_default_values(self):
        p = Project(name="Test", description="Testing")
        assert p.state == ProjectState.DRAFT
        assert p.roles == []
        assert p.is_terminal is False
        assert p.progress == 0.0
        assert p.id  # should have auto-generated id

    def test_filled_roles(self):
        p = Project(
            name="Test",
            roles=[
                ProjectRole(role_name="A", description="a", status="confirmed"),
                ProjectRole(role_name="B", description="b", status="open"),
                ProjectRole(role_name="C", description="c", status="confirmed"),
            ],
        )
        assert len(p.filled_roles) == 2
        assert len(p.open_roles) == 1
        assert p.progress == pytest.approx(2 / 3, abs=0.01)

    def test_progress_zero_roles(self):
        p = Project(name="Empty")
        assert p.progress == 0.0

    def test_can_transition_valid(self):
        p = Project(name="X", state=ProjectState.DRAFT)
        assert p.can_transition_to(ProjectState.RECRUITING) is True

    def test_can_transition_invalid(self):
        p = Project(name="X", state=ProjectState.DRAFT)
        assert p.can_transition_to(ProjectState.ACTIVE) is False

    def test_transition_updates_state(self):
        p = Project(name="X", state=ProjectState.DRAFT)
        old_updated = p.updated_at
        p.transition(ProjectState.RECRUITING)
        assert p.state == ProjectState.RECRUITING
        assert p.updated_at >= old_updated

    def test_transition_invalid_raises(self):
        p = Project(name="X", state=ProjectState.DRAFT)
        with pytest.raises(ValueError, match="Invalid project transition"):
            p.transition(ProjectState.COMPLETED)

    def test_is_terminal_completed(self):
        p = Project(name="Done", state=ProjectState.COMPLETED)
        assert p.is_terminal is True

    def test_is_terminal_active(self):
        p = Project(name="Running", state=ProjectState.ACTIVE)
        assert p.is_terminal is False

    def test_to_dict(self):
        p = Project(
            name="Dashboard",
            description="Build a dashboard",
            coordinator_url="http://localhost:9000",
            coordinator_name="Agent-00",
            roles=[
                ProjectRole(role_name="UI", description="Design", status="confirmed"),
            ],
        )
        d = p.to_dict()
        assert d["name"] == "Dashboard"
        assert d["state"] == "draft"
        assert d["total_roles"] == 1
        assert d["filled_roles"] == 1
        assert d["progress"] == 1.0
        assert len(d["roles"]) == 1
        assert d["roles"][0]["role_name"] == "UI"

    def test_from_dict(self):
        data = {
            "id": "abc12345",
            "name": "Restored",
            "description": "From DB",
            "coordinator_url": "http://localhost:9000",
            "coordinator_name": "Agent-00",
            "state": "recruiting",
            "roles": [
                {"role_name": "Dev", "description": "Coding", "status": "negotiating"},
                {"role_name": "Design", "description": "UI", "status": "open"},
            ],
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-02T00:00:00",
        }
        p = Project.from_dict(data)
        assert p.id == "abc12345"
        assert p.name == "Restored"
        assert p.state == ProjectState.RECRUITING
        assert len(p.roles) == 2
        assert p.roles[0].status == "negotiating"

    def test_roundtrip(self):
        original = Project(
            name="Roundtrip",
            description="Test roundtrip",
            coordinator_url="http://localhost:9000",
            coordinator_name="Agent-00",
            state=ProjectState.PARTIAL,
            roles=[
                ProjectRole(role_name="R1", description="D1", status="confirmed",
                           agent_name="A1", agent_url="http://a1"),
                ProjectRole(role_name="R2", description="D2", status="open"),
            ],
        )
        d = original.to_dict()
        # Restore from to_dict output (flatten roles for from_dict)
        d["roles"] = [r for r in d["roles"]]  # already dicts from to_dict
        restored = Project.from_dict(d)
        assert restored.name == original.name
        assert restored.state == original.state
        assert len(restored.roles) == 2
        assert restored.roles[0].agent_name == "A1"

    def test_stalled_to_recruiting_recovery(self):
        p = Project(name="Stalled", state=ProjectState.STALLED)
        p.transition(ProjectState.RECRUITING)
        assert p.state == ProjectState.RECRUITING

    def test_full_lifecycle(self):
        """Test full project lifecycle: DRAFT -> RECRUITING -> PARTIAL -> ACTIVE -> COMPLETED."""
        p = Project(
            name="Lifecycle",
            roles=[
                ProjectRole(role_name="A", description="a"),
                ProjectRole(role_name="B", description="b"),
            ],
        )
        assert p.state == ProjectState.DRAFT

        p.transition(ProjectState.RECRUITING)
        assert p.state == ProjectState.RECRUITING

        p.transition(ProjectState.PARTIAL)
        assert p.state == ProjectState.PARTIAL

        p.transition(ProjectState.ACTIVE)
        assert p.state == ProjectState.ACTIVE

        p.transition(ProjectState.COMPLETED)
        assert p.state == ProjectState.COMPLETED
        assert p.is_terminal is True

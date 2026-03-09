"""Tests for ProjectManager — create, recruit, sync, suggest, persistence."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.negotiation.project import Project, ProjectRole, ProjectState
from src.negotiation.project_manager import ProjectManager
from src.negotiation.states import Negotiation, NegotiationState
from src.negotiation.manager import NegotiationManager
from src.notification.events import EventBus, EventType


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def neg_manager(event_bus):
    engine = MagicMock()
    engine.our_url = "http://localhost:9000"
    engine.our_name = "Agent-00"
    return NegotiationManager(
        engine=engine,
        event_bus=event_bus,
        auto_negotiate=False,
    )


@pytest.fixture
def pm(neg_manager, event_bus):
    return ProjectManager(
        negotiation_manager=neg_manager,
        event_bus=event_bus,
        our_url="http://localhost:9000",
        our_name="Agent-00",
    )


# ── Create ────────────────────────────────────────────────────

class TestCreateProject:
    def test_create_basic(self, pm):
        project = pm.create_project(
            name="AI Dashboard",
            description="Build a collaborative dashboard",
            roles=[
                {"role_name": "UI Designer", "description": "Design interfaces"},
                {"role_name": "Backend Dev", "description": "Build APIs"},
            ],
        )
        assert project.name == "AI Dashboard"
        assert project.state == ProjectState.DRAFT
        assert len(project.roles) == 2
        assert project.coordinator_url == "http://localhost:9000"

    def test_create_emits_event(self, pm, event_bus):
        pm.create_project("Test", "Desc", [{"role_name": "R", "description": "D"}])
        events = event_bus.get_recent_events(10)
        assert any(e.type == EventType.PROJECT_CREATED for e in events)

    def test_create_multiple(self, pm):
        p1 = pm.create_project("P1", "D1", [{"role_name": "R1", "description": "D1"}])
        p2 = pm.create_project("P2", "D2", [{"role_name": "R2", "description": "D2"}])
        assert p1.id != p2.id
        assert len(pm.get_all_projects()) == 2

    def test_get_project(self, pm):
        p = pm.create_project("X", "Y", [{"role_name": "R", "description": "D"}])
        fetched = pm.get_project(p.id)
        assert fetched is not None
        assert fetched.name == "X"

    def test_get_nonexistent(self, pm):
        assert pm.get_project("nonexistent") is None


# ── Recruit ───────────────────────────────────────────────────

class TestRecruit:
    @pytest.mark.asyncio
    async def test_recruit_transitions_to_recruiting(self, pm):
        p = pm.create_project("Recruit", "Test", [
            {"role_name": "R1", "description": "D1"},
        ])
        assert p.state == ProjectState.DRAFT
        result = await pm.recruit(p.id)
        assert p.state == ProjectState.RECRUITING
        assert "project_id" in result

    @pytest.mark.asyncio
    async def test_recruit_links_existing_negotiation(self, pm, neg_manager):
        # Create a negotiation with a specific peer
        neg = Negotiation(
            our_url="http://localhost:9000",
            their_url="http://localhost:9001",
            our_name="Agent-00",
            their_name="Agent-01",
        )
        neg_manager._negotiations[neg.id] = neg
        neg_manager._by_peer["http://localhost:9001"] = neg.id

        p = pm.create_project("Linked", "Test", [
            {
                "role_name": "Designer",
                "description": "Design stuff",
                "agent_url": "http://localhost:9001",
            },
        ])
        result = await pm.recruit(p.id)
        assert result["recruited"][0]["action"] == "linked_existing"
        assert p.roles[0].negotiation_id == neg.id
        assert p.roles[0].status == "negotiating"

    @pytest.mark.asyncio
    async def test_recruit_nonexistent(self, pm):
        result = await pm.recruit("fake-id")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_recruit_emits_event(self, pm, event_bus):
        p = pm.create_project("E", "D", [{"role_name": "R", "description": "D"}])
        await pm.recruit(p.id)
        events = event_bus.get_recent_events(10)
        assert any(e.type == EventType.PROJECT_RECRUITING for e in events)


# ── Sync ──────────────────────────────────────────────────────

class TestSync:
    @pytest.mark.asyncio
    async def test_sync_updates_confirmed_role(self, pm, neg_manager):
        # Setup negotiation in CONFIRMED state
        neg = Negotiation(
            our_url="http://localhost:9000",
            their_url="http://localhost:9001",
            our_name="Agent-00",
            their_name="Agent-01",
            state=NegotiationState.CONFIRMED,
        )
        neg_manager._negotiations[neg.id] = neg

        p = pm.create_project("Sync", "Test", [
            {"role_name": "Dev", "description": "Build", "agent_url": "http://localhost:9001"},
        ])
        p.roles[0].negotiation_id = neg.id
        p.roles[0].status = "negotiating"
        p.state = ProjectState.RECRUITING

        result = await pm.sync(p.id)
        assert p.roles[0].status == "confirmed"
        assert len(result["changes"]) > 0

    @pytest.mark.asyncio
    async def test_sync_to_active_when_all_confirmed(self, pm, neg_manager):
        neg = Negotiation(
            our_url="http://localhost:9000",
            their_url="http://localhost:9001",
            state=NegotiationState.CONFIRMED,
            their_name="Agent-01",
        )
        neg_manager._negotiations[neg.id] = neg

        p = pm.create_project("AllConfirmed", "Test", [
            {"role_name": "Dev", "description": "Build"},
        ])
        p.roles[0].negotiation_id = neg.id
        p.roles[0].status = "negotiating"
        p.state = ProjectState.RECRUITING

        await pm.sync(p.id)
        assert p.state == ProjectState.ACTIVE

    @pytest.mark.asyncio
    async def test_sync_to_stalled_on_rejection(self, pm, neg_manager):
        neg = Negotiation(
            our_url="http://localhost:9000",
            their_url="http://localhost:9001",
            state=NegotiationState.REJECTED,
            their_name="Agent-01",
        )
        neg_manager._negotiations[neg.id] = neg

        p = pm.create_project("Rejected", "Test", [
            {"role_name": "Dev", "description": "Build"},
        ])
        p.roles[0].negotiation_id = neg.id
        p.roles[0].status = "negotiating"
        p.state = ProjectState.RECRUITING

        await pm.sync(p.id)
        assert p.roles[0].status == "rejected"
        assert p.state == ProjectState.STALLED

    @pytest.mark.asyncio
    async def test_sync_partial_state(self, pm, neg_manager):
        neg1 = Negotiation(
            id="n1", our_url="http://localhost:9000",
            their_url="http://localhost:9001",
            state=NegotiationState.CONFIRMED,
            their_name="Agent-01",
        )
        neg2 = Negotiation(
            id="n2", our_url="http://localhost:9000",
            their_url="http://localhost:9002",
            state=NegotiationState.PROPOSED,
            their_name="Agent-02",
        )
        neg_manager._negotiations["n1"] = neg1
        neg_manager._negotiations["n2"] = neg2

        p = pm.create_project("Partial", "Test", [
            {"role_name": "A", "description": "D1"},
            {"role_name": "B", "description": "D2"},
        ])
        p.roles[0].negotiation_id = "n1"
        p.roles[0].status = "negotiating"
        p.roles[1].negotiation_id = "n2"
        p.roles[1].status = "negotiating"
        p.state = ProjectState.RECRUITING

        await pm.sync(p.id)
        assert p.roles[0].status == "confirmed"
        assert p.roles[1].status == "negotiating"
        assert p.state == ProjectState.PARTIAL

    @pytest.mark.asyncio
    async def test_sync_nonexistent(self, pm):
        result = await pm.sync("fake-id")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_sync_active_emits_event(self, pm, neg_manager, event_bus):
        neg = Negotiation(
            our_url="http://localhost:9000",
            their_url="http://localhost:9001",
            state=NegotiationState.CONFIRMED,
            their_name="Agent-01",
        )
        neg_manager._negotiations[neg.id] = neg

        p = pm.create_project("EventSync", "Test", [
            {"role_name": "Dev", "description": "Build"},
        ])
        p.roles[0].negotiation_id = neg.id
        p.roles[0].status = "negotiating"
        p.state = ProjectState.RECRUITING

        await pm.sync(p.id)
        events = event_bus.get_recent_events(20)
        assert any(e.type == EventType.PROJECT_ACTIVE for e in events)


# ── Complete ──────────────────────────────────────────────────

class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_active_project(self, pm):
        p = pm.create_project("Done", "Test", [
            {"role_name": "R", "description": "D"},
        ])
        p.state = ProjectState.ACTIVE
        result = await pm.complete(p.id)
        assert result["status"] == "completed"
        assert p.state == ProjectState.COMPLETED
        assert p.is_terminal is True

    @pytest.mark.asyncio
    async def test_complete_non_active_fails(self, pm):
        p = pm.create_project("Draft", "Test", [
            {"role_name": "R", "description": "D"},
        ])
        result = await pm.complete(p.id)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_complete_nonexistent(self, pm):
        result = await pm.complete("fake-id")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_complete_emits_event(self, pm, event_bus):
        p = pm.create_project("CompEvent", "Test", [
            {"role_name": "R", "description": "D"},
        ])
        p.state = ProjectState.ACTIVE
        await pm.complete(p.id)
        events = event_bus.get_recent_events(20)
        assert any(e.type == EventType.PROJECT_COMPLETED for e in events)


# ── Suggest ───────────────────────────────────────────────────

class TestSuggest:
    @pytest.mark.asyncio
    async def test_suggest_no_matches(self, pm):
        result = await pm.suggest_project([])
        assert "error" in result

    @pytest.mark.asyncio
    async def test_suggest_fallback_no_api_key(self, pm):
        matches = [
            {
                "agent_name": "Agent-01",
                "agent_url": "http://localhost:9001",
                "overall_score": 0.5,
                "description": "UI/UX Designer",
            },
            {
                "agent_name": "Agent-02",
                "agent_url": "http://localhost:9002",
                "overall_score": 0.4,
                "description": "ML Engineer",
            },
        ]
        result = await pm.suggest_project(matches)
        assert "name" in result
        assert "roles" in result
        assert len(result["roles"]) == 2

    @pytest.mark.asyncio
    async def test_suggest_fallback_structure(self, pm):
        matches = [
            {
                "agent_name": "Alice",
                "agent_url": "http://alice:9001",
                "overall_score": 0.8,
                "description": "Expert in React and TypeScript",
            },
        ]
        result = await pm.suggest_project(matches)
        assert result["roles"][0]["suggested_agent"] == "Alice"
        assert "suggested_agent_url" in result["roles"][0]


# ── Status ────────────────────────────────────────────────────

class TestStatus:
    def test_empty_status(self, pm):
        status = pm.get_status()
        assert status["total"] == 0
        assert status["draft"] == 0

    def test_status_with_projects(self, pm):
        pm.create_project("P1", "D1", [{"role_name": "R", "description": "D"}])
        p2 = pm.create_project("P2", "D2", [{"role_name": "R", "description": "D"}])
        p2.state = ProjectState.ACTIVE
        status = pm.get_status()
        assert status["total"] == 2
        assert status["draft"] == 1
        assert status["active"] == 1

    def test_get_active_projects(self, pm):
        p1 = pm.create_project("P1", "D1", [{"role_name": "R", "description": "D"}])
        p2 = pm.create_project("P2", "D2", [{"role_name": "R", "description": "D"}])
        p2.state = ProjectState.ACTIVE
        active = pm.get_active_projects()
        assert len(active) == 1
        assert active[0].name == "P2"


# ── Storage ───────────────────────────────────────────────────

class TestStorage:
    @pytest.mark.asyncio
    async def test_persist_called(self, neg_manager, event_bus):
        storage = AsyncMock()
        storage.get_all_projects = AsyncMock(return_value=[])
        pm = ProjectManager(
            negotiation_manager=neg_manager,
            event_bus=event_bus,
            our_url="http://localhost:9000",
            our_name="Agent-00",
            storage=storage,
        )
        p = pm.create_project("Persist", "Test", [{"role_name": "R", "description": "D"}])
        await pm._persist(p)
        storage.save_project.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_from_storage(self, neg_manager, event_bus):
        storage = AsyncMock()
        storage.get_all_projects = AsyncMock(return_value=[
            {
                "id": "test123",
                "name": "Loaded",
                "description": "From DB",
                "coordinator_url": "http://localhost:9000",
                "coordinator_name": "Agent-00",
                "state": "recruiting",
                "roles": [{"role_name": "R", "description": "D", "status": "open"}],
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-02T00:00:00",
            }
        ])
        pm = ProjectManager(
            negotiation_manager=neg_manager,
            event_bus=event_bus,
            our_url="http://localhost:9000",
            our_name="Agent-00",
            storage=storage,
        )
        count = await pm.load_from_storage()
        assert count == 1
        p = pm.get_project("test123")
        assert p is not None
        assert p.name == "Loaded"
        assert p.state == ProjectState.RECRUITING

    @pytest.mark.asyncio
    async def test_no_storage_returns_zero(self, pm):
        count = await pm.load_from_storage()
        assert count == 0

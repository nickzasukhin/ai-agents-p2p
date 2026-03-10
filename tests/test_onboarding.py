"""Tests for Phase 12.3 — AI Interview Onboarding."""

import pytest
import httpx

from src.server import create_app
from src.notification.events import EventBus
from src.identity.did import DIDManager
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry
from src.onboarding.interview import (
    OnboardingInterviewer,
    OnboardingSession,
    OnboardingState,
)


# ── Unit Tests: OnboardingInterviewer (no LLM) ───────────────

class TestOnboardingInterviewer:
    def test_create_interviewer_without_llm(self):
        """Interviewer should work without LLM (fallback mode)."""
        interviewer = OnboardingInterviewer(llm=None)
        assert interviewer.llm is None

    async def test_start_session(self):
        """Starting a session should return greeting state."""
        interviewer = OnboardingInterviewer(llm=None)
        result = await interviewer.process_start()

        assert result["state"] == "greeting"
        assert result["session_id"]
        assert result["progress"] == 0.0
        assert len(result["response"]) > 0

    async def test_session_stored(self):
        """Sessions should be retrievable by ID."""
        interviewer = OnboardingInterviewer(llm=None)
        result = await interviewer.process_start()

        session = interviewer.get_session(result["session_id"])
        assert session is not None
        assert session.state == OnboardingState.GREETING

    async def test_full_flow_without_llm(self):
        """Complete onboarding flow should work without LLM."""
        interviewer = OnboardingInterviewer(llm=None)

        # Start
        start = await interviewer.process_start()
        sid = start["session_id"]
        assert start["state"] == "greeting"

        # Step 1: Send name + skills
        r1 = await interviewer.process_message(sid, "Alice, I do Python and FastAPI")
        assert r1["state"] == "collecting_needs"
        assert r1["progress"] > 0

        # Step 2: Send needs → auto-generates profile → review
        r2 = await interviewer.process_message(sid, "Looking for UI designer")
        assert r2["state"] == "review"
        assert r2["progress"] >= 0.9
        assert r2.get("card_preview") is not None
        assert r2.get("files_preview") is not None

    async def test_confirm_after_review(self):
        """Confirming should return files to write."""
        interviewer = OnboardingInterviewer(llm=None)

        # Go through full flow
        start = await interviewer.process_start()
        sid = start["session_id"]
        await interviewer.process_message(sid, "Bob, JavaScript and React developer")
        await interviewer.process_message(sid, "Need backend developer")

        # Confirm
        result = await interviewer.confirm(sid)
        assert result["state"] == "confirmed"
        assert result["progress"] == 1.0
        assert "files" in result
        assert "profile_md" in result["files"]
        assert "skills_md" in result["files"]
        assert "needs_md" in result["files"]

    async def test_confirm_wrong_state(self):
        """Confirming in wrong state should return error."""
        interviewer = OnboardingInterviewer(llm=None)
        start = await interviewer.process_start()
        result = await interviewer.confirm(start["session_id"])
        assert "error" in result

    async def test_confirm_invalid_session(self):
        """Confirming with invalid session should return error."""
        interviewer = OnboardingInterviewer(llm=None)
        result = await interviewer.confirm("nonexistent-id")
        assert "error" in result

    async def test_message_invalid_session(self):
        """Sending message to invalid session should return error."""
        interviewer = OnboardingInterviewer(llm=None)
        result = await interviewer.process_message("nonexistent", "hello")
        assert "error" in result

    async def test_message_after_confirmed(self):
        """Sending message after confirmed should not change state."""
        interviewer = OnboardingInterviewer(llm=None)

        start = await interviewer.process_start()
        sid = start["session_id"]
        await interviewer.process_message(sid, "Charlie, Design and UX")
        await interviewer.process_message(sid, "Need frontend dev")
        await interviewer.confirm(sid)

        result = await interviewer.process_message(sid, "more stuff")
        assert result["state"] == "confirmed"

    async def test_progress_increases(self):
        """Progress should increase with each step."""
        interviewer = OnboardingInterviewer(llm=None)

        start = await interviewer.process_start()
        sid = start["session_id"]
        p0 = start["progress"]

        r1 = await interviewer.process_message(sid, "Dana, Data Science expert")
        p1 = r1["progress"]

        r2 = await interviewer.process_message(sid, "Need ML ops")
        p2 = r2["progress"]

        assert p0 < p1 < p2

    async def test_generated_profile_has_skills(self):
        """Generated profile should include parsed skills."""
        interviewer = OnboardingInterviewer(llm=None)

        start = await interviewer.process_start()
        sid = start["session_id"]
        await interviewer.process_message(sid, "Eve, Rust, Go, Kubernetes")
        r2 = await interviewer.process_message(sid, "Need security expert")

        card = r2["card_preview"]
        assert card["agent_name"]
        assert len(card["skills"]) > 0
        assert len(card["needs"]) > 0

    async def test_generated_files_valid_markdown(self):
        """Generated files should be valid markdown."""
        interviewer = OnboardingInterviewer(llm=None)

        start = await interviewer.process_start()
        sid = start["session_id"]
        await interviewer.process_message(sid, "Frank, DevOps and Docker")
        r2 = await interviewer.process_message(sid, "Need frontend dev")

        files = r2["files_preview"]
        assert files["profile_md"].startswith("# ")
        assert files["skills_md"].startswith("# ")
        assert files["needs_md"].startswith("# ")


# ── OnboardingSession Tests ──────────────────────────────────

class TestOnboardingSession:
    def test_session_defaults(self):
        """New session should have correct defaults."""
        session = OnboardingSession()
        assert session.state == OnboardingState.GREETING
        assert session.conversation == []
        assert session.user_name == ""
        assert session.session_id  # Should auto-generate UUID

    def test_session_unique_ids(self):
        """Each session should get a unique ID."""
        s1 = OnboardingSession()
        s2 = OnboardingSession()
        assert s1.session_id != s2.session_id


# ── API Endpoint Tests ────────────────────────────────────────

@pytest.fixture
def onboarding_app(tmp_path, sample_agent_card):
    """Create a FastAPI app for onboarding testing."""
    did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
    did_mgr.init()

    event_bus = EventBus(max_buffer=20)
    registry = StaticRegistry(registry_path=tmp_path / "registry.json")
    gossip = GossipProtocol(registry=registry, own_url="http://localhost:9000")

    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "profile.md").write_text("# Test\n")
    (ctx_dir / "skills.md").write_text("# Skills\n")
    (ctx_dir / "needs.md").write_text("# Needs\n")

    app = create_app(
        agent_card=sample_agent_card,
        did_manager=did_mgr,
        event_bus=event_bus,
        gossip=gossip,
        data_dir=str(tmp_path),
        own_url="http://localhost:9000",
    )
    return app, tmp_path


@pytest.fixture
async def onboarding_client(onboarding_app):
    """Async httpx test client for onboarding tests."""
    app, _ = onboarding_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestOnboardingStatusEndpoint:
    async def test_status_with_existing_files(self, onboarding_client):
        """Status should show onboarding complete when files exist."""
        resp = await onboarding_client.get("/onboarding/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_profile"] is True
        assert data["has_skills"] is True
        assert data["onboarding_complete"] is True

    async def test_status_without_files(self, tmp_path, sample_agent_card):
        """Status should show not complete when no profile files."""
        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)

        # Empty context dir — no profile files
        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()

        app = create_app(
            agent_card=sample_agent_card,
            did_manager=did_mgr,
            event_bus=event_bus,
            data_dir=str(tmp_path),
            own_url="http://localhost:9000",
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/onboarding/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["has_profile"] is False
            assert data["onboarding_complete"] is False


class TestOnboardingStartEndpoint:
    async def test_start_returns_session(self, onboarding_client):
        """POST /onboarding/start should return session_id and greeting."""
        resp = await onboarding_client.post("/onboarding/start")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["state"] == "greeting"
        assert data["progress"] == 0.0
        assert len(data["response"]) > 0


class TestOnboardingChatEndpoint:
    async def test_chat_advances_state(self, onboarding_client):
        """POST /onboarding/chat should advance the interview state."""
        # Start session
        start = await onboarding_client.post("/onboarding/start")
        sid = start.json()["session_id"]

        # Send first message (name + skills)
        resp = await onboarding_client.post(
            "/onboarding/chat",
            json={"session_id": sid, "message": "Alice, Python developer"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "collecting_needs"

    async def test_chat_missing_session_id(self, onboarding_client):
        """POST /onboarding/chat without session_id should return 400."""
        resp = await onboarding_client.post(
            "/onboarding/chat",
            json={"message": "hello"}
        )
        assert resp.status_code == 400

    async def test_chat_missing_message(self, onboarding_client):
        """POST /onboarding/chat without message should return 400."""
        start = await onboarding_client.post("/onboarding/start")
        sid = start.json()["session_id"]

        resp = await onboarding_client.post(
            "/onboarding/chat",
            json={"session_id": sid}
        )
        assert resp.status_code == 400

    async def test_chat_invalid_session(self, onboarding_client):
        """POST /onboarding/chat with invalid session should return 404."""
        resp = await onboarding_client.post(
            "/onboarding/chat",
            json={"session_id": "fake-id", "message": "hello"}
        )
        assert resp.status_code == 404

    async def test_full_chat_flow(self, onboarding_client):
        """Full chat flow should reach review state with card preview."""
        start = await onboarding_client.post("/onboarding/start")
        sid = start.json()["session_id"]

        # Name + Skills
        await onboarding_client.post(
            "/onboarding/chat", json={"session_id": sid, "message": "Grace, Python, ML, NLP expert"}
        )
        # Needs
        resp = await onboarding_client.post(
            "/onboarding/chat", json={"session_id": sid, "message": "Looking for frontend dev"}
        )

        data = resp.json()
        assert data["state"] == "review"
        assert data["card_preview"] is not None
        assert data["files_preview"] is not None


class TestOnboardingConfirmEndpoint:
    async def test_confirm_writes_files(self, onboarding_app):
        """POST /onboarding/confirm should write profile files."""
        app, tmp_path = onboarding_app
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Go through full flow
            start = await client.post("/onboarding/start")
            sid = start.json()["session_id"]

            await client.post(
                "/onboarding/chat", json={"session_id": sid, "message": "Hank, Go, Rust, Systems"}
            )
            await client.post(
                "/onboarding/chat", json={"session_id": sid, "message": "Need UI help"}
            )

            # Confirm
            resp = await client.post(
                "/onboarding/confirm", json={"session_id": sid}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["state"] == "confirmed"

            # Verify files were written
            ctx_dir = tmp_path / "context"
            assert (ctx_dir / "profile.md").exists()
            assert (ctx_dir / "skills.md").exists()
            assert (ctx_dir / "needs.md").exists()

            # Verify content is markdown
            profile = (ctx_dir / "profile.md").read_text()
            assert profile.startswith("# ")

    async def test_confirm_missing_session_id(self, onboarding_client):
        """POST /onboarding/confirm without session_id should return 400."""
        resp = await onboarding_client.post("/onboarding/confirm", json={})
        assert resp.status_code == 400

    async def test_confirm_wrong_state(self, onboarding_client):
        """POST /onboarding/confirm in wrong state should return 400."""
        start = await onboarding_client.post("/onboarding/start")
        sid = start.json()["session_id"]

        resp = await onboarding_client.post(
            "/onboarding/confirm", json={"session_id": sid}
        )
        assert resp.status_code == 400


class TestOnboardingAuth:
    async def test_onboarding_status_no_auth_required(self, tmp_path, sample_agent_card):
        """GET /onboarding/status should work without auth (it's a GET)."""
        from src.agent.config import AgentConfig

        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        config = AgentConfig(api_token="secret-token")

        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()
        (ctx_dir / "profile.md").write_text("# Test\n")

        app = create_app(
            agent_card=sample_agent_card,
            did_manager=did_mgr,
            event_bus=event_bus,
            data_dir=str(tmp_path),
            own_url="http://localhost:9000",
            config=config,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/onboarding/status")
            assert resp.status_code == 200

    async def test_onboarding_post_requires_auth(self, tmp_path, sample_agent_card):
        """POST /onboarding/* should require auth when API token is set."""
        from src.agent.config import AgentConfig

        did_mgr = DIDManager(identity_path=tmp_path / "identity.json")
        did_mgr.init()
        event_bus = EventBus(max_buffer=20)
        config = AgentConfig(api_token="secret-token")

        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()
        (ctx_dir / "profile.md").write_text("# Test\n")

        app = create_app(
            agent_card=sample_agent_card,
            did_manager=did_mgr,
            event_bus=event_bus,
            data_dir=str(tmp_path),
            own_url="http://localhost:9000",
            config=config,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Without token — should be rejected
            resp = await client.post("/onboarding/start")
            assert resp.status_code == 401

            # With token — should work
            resp = await client.post(
                "/onboarding/start",
                headers={"Authorization": "Bearer secret-token"},
            )
            assert resp.status_code == 200

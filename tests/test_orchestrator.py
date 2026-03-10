"""Tests for Phase 12.6 — Orchestrator Service."""

import pytest
import time
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from orchestrator.config import OrchestratorConfig
from orchestrator.models import OrchestratorDB
from orchestrator.auth.magic_link import MagicLinkManager, SessionManager
from orchestrator.auth.email import EmailSender
from orchestrator.containers.port_allocator import PortAllocator
from orchestrator.containers.manager import ContainerManager
from orchestrator.proxy import NginxProxy
from orchestrator.app import create_orchestrator_app


# ── Unit Tests: MagicLinkManager ──────────────────────────────

class TestMagicLinkManager:
    def test_create_token(self):
        """Should create a valid JWT-like token."""
        mgr = MagicLinkManager(secret="test-secret", expiry_minutes=15)
        token, expires_at = mgr.create_token("user@example.com")

        assert token
        assert "." in token
        assert len(token.split(".")) == 3
        assert expires_at

    def test_verify_valid_token(self):
        """Should verify a freshly created token."""
        mgr = MagicLinkManager(secret="test-secret", expiry_minutes=15)
        token, _ = mgr.create_token("user@example.com")

        payload = mgr.verify_token(token)
        assert payload is not None
        assert payload["email"] == "user@example.com"

    def test_verify_expired_token(self):
        """Should reject an expired token."""
        mgr = MagicLinkManager(secret="test-secret", expiry_minutes=0)
        # Create with 0 expiry → already expired
        token, _ = mgr.create_token("user@example.com")

        # Wait a tiny bit to ensure time passes
        import time
        time.sleep(0.01)

        payload = mgr.verify_token(token)
        assert payload is None

    def test_verify_bad_signature(self):
        """Should reject a token with wrong secret."""
        mgr1 = MagicLinkManager(secret="secret-1", expiry_minutes=15)
        mgr2 = MagicLinkManager(secret="secret-2", expiry_minutes=15)

        token, _ = mgr1.create_token("user@example.com")
        payload = mgr2.verify_token(token)
        assert payload is None

    def test_verify_invalid_format(self):
        """Should reject malformed tokens."""
        mgr = MagicLinkManager(secret="test-secret")
        assert mgr.verify_token("not-a-token") is None
        assert mgr.verify_token("") is None
        assert mgr.verify_token("a.b") is None

    def test_build_link(self):
        """Should build a full magic link URL."""
        mgr = MagicLinkManager(
            secret="test-secret",
            base_url="https://agents.devpunks.io",
        )
        token, _ = mgr.create_token("user@example.com")
        link = mgr.build_link(token)

        assert link.startswith("https://agents.devpunks.io/app?token=")
        assert token in link

    def test_email_normalized(self):
        """Token email should be lowercase and stripped."""
        mgr = MagicLinkManager(secret="test-secret")
        token, _ = mgr.create_token("  User@Example.COM  ")
        payload = mgr.verify_token(token)
        assert payload["email"] == "user@example.com"

    def test_unique_tokens(self):
        """Each token should be unique (nonce)."""
        mgr = MagicLinkManager(secret="test-secret")
        t1, _ = mgr.create_token("user@example.com")
        t2, _ = mgr.create_token("user@example.com")
        assert t1 != t2


# ── Unit Tests: SessionManager ────────────────────────────────

class TestSessionManager:
    def test_create_session(self):
        """Should create a session token."""
        mgr = SessionManager(secret="test-secret", expiry_hours=72)
        token = mgr.create_session("user-123", "user@example.com")

        assert token
        assert len(token.split(".")) == 3

    def test_verify_session(self):
        """Should verify a valid session token."""
        mgr = SessionManager(secret="test-secret", expiry_hours=72)
        token = mgr.create_session("user-123", "user@example.com")

        payload = mgr.verify_session(token)
        assert payload is not None
        assert payload["user_id"] == "user-123"
        assert payload["email"] == "user@example.com"
        assert payload["type"] == "session"

    def test_session_wrong_secret(self):
        """Should reject session with wrong secret."""
        mgr1 = SessionManager(secret="secret-1")
        mgr2 = SessionManager(secret="secret-2")

        token = mgr1.create_session("user-123", "user@example.com")
        assert mgr2.verify_session(token) is None

    def test_session_expiry(self):
        """Should reject expired session."""
        mgr = SessionManager(secret="test-secret", expiry_hours=0)
        token = mgr.create_session("user-123", "user@example.com")
        time.sleep(0.01)
        assert mgr.verify_session(token) is None


# ── Unit Tests: PortAllocator ─────────────────────────────────

class TestPortAllocator:
    def test_allocate_first_port(self):
        """Should allocate the first port in range."""
        alloc = PortAllocator(start=9100, end=9110)
        port = alloc.allocate(set())
        assert port == 9100

    def test_allocate_skips_used(self):
        """Should skip used ports."""
        alloc = PortAllocator(start=9100, end=9110)
        port = alloc.allocate({9100, 9101})
        assert port == 9102

    def test_allocate_exhausted(self):
        """Should return None when all ports used."""
        alloc = PortAllocator(start=9100, end=9102)
        port = alloc.allocate({9100, 9101, 9102})
        assert port is None

    def test_capacity(self):
        """Should report correct capacity."""
        alloc = PortAllocator(start=9100, end=9199)
        assert alloc.capacity == 100

    def test_invalid_range(self):
        """Should reject invalid port range."""
        with pytest.raises(ValueError):
            PortAllocator(start=9200, end=9100)


# ── Unit Tests: OrchestratorDB ────────────────────────────────

class TestOrchestratorDB:
    @pytest.fixture
    async def db(self, tmp_path):
        """Fresh orchestrator database."""
        db = OrchestratorDB(db_path=str(tmp_path / "test.db"))
        await db.init()
        yield db
        await db.close()

    async def test_create_user(self, db):
        """Should create a new user."""
        user = await db.create_user("test@example.com")
        assert user["id"]
        assert user["email"] == "test@example.com"
        assert user["created_at"]

    async def test_get_user_by_email(self, db):
        """Should find user by email."""
        await db.create_user("test@example.com")
        user = await db.get_user_by_email("test@example.com")
        assert user is not None
        assert user["email"] == "test@example.com"

    async def test_get_user_by_email_case_insensitive(self, db):
        """Email lookup should be case-insensitive."""
        await db.create_user("Test@Example.COM")
        user = await db.get_user_by_email("test@example.com")
        assert user is not None

    async def test_get_user_not_found(self, db):
        """Should return None for unknown email."""
        user = await db.get_user_by_email("nobody@example.com")
        assert user is None

    async def test_create_agent_instance(self, db):
        """Should create an agent instance."""
        user = await db.create_user("test@example.com")
        instance = await db.create_agent_instance(
            user_id=user["id"],
            container_id="abc123",
            port=9100,
            api_token="token-xyz",
            agent_url="https://user.agents.devpunks.io",
            status="running",
        )
        assert instance["id"]
        assert instance["port"] == 9100
        assert instance["status"] == "running"

    async def test_get_agent_by_user(self, db):
        """Should find agent by user ID."""
        user = await db.create_user("test@example.com")
        await db.create_agent_instance(
            user_id=user["id"], port=9100, status="running"
        )

        agent = await db.get_agent_by_user(user["id"])
        assert agent is not None
        assert agent["port"] == 9100

    async def test_no_agent_for_user(self, db):
        """Should return None when user has no agent."""
        user = await db.create_user("test@example.com")
        agent = await db.get_agent_by_user(user["id"])
        assert agent is None

    async def test_update_agent_status(self, db):
        """Should update agent status."""
        user = await db.create_user("test@example.com")
        instance = await db.create_agent_instance(
            user_id=user["id"], status="starting"
        )

        await db.update_agent_status(instance["id"], "running")
        agent = await db.get_agent_by_user(user["id"])
        assert agent["status"] == "running"

    async def test_delete_agent_instance(self, db):
        """Should delete agent instance."""
        user = await db.create_user("test@example.com")
        instance = await db.create_agent_instance(
            user_id=user["id"], status="running"
        )

        deleted = await db.delete_agent_instance(instance["id"])
        assert deleted is True

        agent = await db.get_agent_by_user(user["id"])
        assert agent is None

    async def test_list_all_agents(self, db):
        """Should list all agents with user emails."""
        user1 = await db.create_user("user1@example.com")
        user2 = await db.create_user("user2@example.com")
        await db.create_agent_instance(user_id=user1["id"], port=9100, status="running")
        await db.create_agent_instance(user_id=user2["id"], port=9101, status="running")

        agents = await db.list_all_agents()
        assert len(agents) == 2
        emails = {a["email"] for a in agents}
        assert "user1@example.com" in emails
        assert "user2@example.com" in emails

    async def test_magic_link_lifecycle(self, db):
        """Should create, use, and invalidate magic links."""
        await db.create_magic_link(
            token="test-token",
            email="test@example.com",
            expires_at="2099-01-01T00:00:00+00:00",
        )

        # First use succeeds
        link = await db.use_magic_link("test-token")
        assert link is not None
        assert link["email"] == "test@example.com"

        # Second use fails (already used)
        link2 = await db.use_magic_link("test-token")
        assert link2 is None

    async def test_magic_link_not_found(self, db):
        """Should return None for unknown token."""
        link = await db.use_magic_link("nonexistent")
        assert link is None

    async def test_count_users(self, db):
        """Should count users."""
        assert await db.count_users() == 0
        await db.create_user("a@b.com")
        assert await db.count_users() == 1
        await db.create_user("c@d.com")
        assert await db.count_users() == 2

    async def test_count_agents(self, db):
        """Should count agents."""
        assert await db.count_agents() == 0
        user = await db.create_user("a@b.com")
        await db.create_agent_instance(user_id=user["id"], status="running")
        assert await db.count_agents() == 1


# ── Unit Tests: EmailSender ───────────────────────────────────

class TestEmailSender:
    async def test_send_disabled(self):
        """Should log and return True when disabled."""
        sender = EmailSender(enabled=False)
        result = await sender.send_magic_link("test@example.com", "https://link", "Agent")
        assert result is True

    async def test_send_no_provider(self):
        """Should log and return True when no provider configured."""
        sender = EmailSender(resend_api_key="", enabled=True)
        result = await sender.send_magic_link("test@example.com", "https://link")
        assert result is True

    def test_build_email_html(self):
        """HTML should contain DevPunks branding and the link."""
        sender = EmailSender()
        html = sender._build_email_html("https://magic-link.example.com", "My Agent")

        assert "DevPunks" in html or "Dev" in html
        assert "https://magic-link.example.com" in html
        assert "#E50051" in html  # DevPunks accent color
        assert "My Agent" in html


# ── Unit Tests: NginxProxy ────────────────────────────────────

class TestNginxProxy:
    async def test_add_proxy_writes_config(self, tmp_path):
        """Should write nginx config file."""
        proxy = NginxProxy(conf_dir=str(tmp_path / "nginx"), domain="agents.test.io")

        # Mock nginx reload
        with patch.object(proxy, "_reload_nginx", new_callable=AsyncMock) as mock_reload:
            mock_reload.return_value = True
            url = await proxy.add_proxy("user-123", 9100)

        assert url == "https://user-123.agents.test.io"

        conf_file = tmp_path / "nginx" / "user-123.conf"
        assert conf_file.exists()
        content = conf_file.read_text()
        assert "user-123.agents.test.io" in content
        assert "localhost:9100" in content
        assert "proxy_pass" in content
        assert "Upgrade" in content  # WebSocket support

    async def test_remove_proxy(self, tmp_path):
        """Should remove nginx config file."""
        conf_dir = tmp_path / "nginx"
        conf_dir.mkdir()
        conf_file = conf_dir / "user-123.conf"
        conf_file.write_text("server {}")

        proxy = NginxProxy(conf_dir=str(conf_dir), domain="agents.test.io")

        with patch.object(proxy, "_reload_nginx", new_callable=AsyncMock):
            await proxy.remove_proxy("user-123")

        assert not conf_file.exists()

    def test_get_subdomain(self):
        """Should return correct subdomain URL."""
        proxy = NginxProxy(domain="agents.devpunks.io")
        assert proxy.get_subdomain("abc") == "https://abc.agents.devpunks.io"


# ── Unit Tests: ContainerManager ──────────────────────────────

class TestContainerManager:
    async def test_spawn_agent(self, tmp_path):
        """Should spawn a container and return info."""
        mock_docker = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "container-abc123"
        mock_docker.containers.run.return_value = mock_container

        mgr = ContainerManager(
            agent_image="test-image",
            data_root=str(tmp_path / "agents"),
            docker_client=mock_docker,
            domain="agents.test.io",
            seed_node_url="https://seed.test.io",
        )

        result = await mgr.spawn_agent(
            user_id="user-123",
            agent_name="Test Agent",
            used_ports=set(),
        )

        assert result["container_id"] == "container-abc123"
        assert result["port"] == 9100
        assert result["api_token"]
        assert result["agent_url"] == "https://user-123.agents.test.io"

        # Verify data dir was created
        assert (tmp_path / "agents" / "user-123" / "context").exists()

    async def test_spawn_agent_no_ports(self, tmp_path):
        """Should raise when all ports are used."""
        mgr = ContainerManager(
            data_root=str(tmp_path),
            port_allocator=PortAllocator(start=9100, end=9100),
            docker_client=MagicMock(),
        )

        with pytest.raises(RuntimeError, match="No available ports"):
            await mgr.spawn_agent("user-123", used_ports={9100})

    async def test_health_check(self):
        """Should return container health status."""
        mock_docker = MagicMock()
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_container.attrs = {"State": {"Health": {"Status": "healthy"}}}
        mock_docker.containers.get.return_value = mock_container

        mgr = ContainerManager(docker_client=mock_docker)
        result = await mgr.health_check("container-123")

        assert result["status"] == "running"
        assert result["running"] is True
        assert result["health"] == "healthy"

    async def test_stop_agent(self):
        """Should stop and remove container."""
        mock_docker = MagicMock()
        mock_container = MagicMock()
        mock_docker.containers.get.return_value = mock_container

        mgr = ContainerManager(docker_client=mock_docker)
        result = await mgr.stop_agent("container-123")

        assert result is True
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()


# ── API Endpoint Tests ────────────────────────────────────────

@pytest.fixture
async def orch_db(tmp_path):
    """Fresh orchestrator database for API tests."""
    db = OrchestratorDB(db_path=str(tmp_path / "orch.db"))
    await db.init()
    yield db
    await db.close()


@pytest.fixture
def orch_config(tmp_path):
    """Orchestrator config for testing."""
    return OrchestratorConfig(
        db_path=str(tmp_path / "orch.db"),
        jwt_secret="test-secret-key-12345",
        magic_link_expiry_minutes=15,
        session_expiry_hours=72,
        base_url="https://test.agents.io",
        email_enabled=False,
        port_range_start=9100,
        port_range_end=9200,
        admin_emails=["admin@test.com"],
        agent_data_root=str(tmp_path / "agent-data"),
        nginx_conf_dir=str(tmp_path / "nginx"),
        domain="agents.test.io",
    )


@pytest.fixture
def mock_container_manager(tmp_path):
    """Mock container manager that doesn't need Docker."""
    mgr = MagicMock(spec=ContainerManager)

    async def mock_spawn(user_id, agent_name="Agent", used_ports=None):
        return {
            "container_id": f"mock-container-{user_id}",
            "port": 9100,
            "api_token": "mock-api-token-xyz",
            "agent_url": f"https://{user_id}.agents.test.io",
            "status": "starting",
        }

    async def mock_stop(container_id):
        return True

    async def mock_health(container_id):
        return {"status": "running", "running": True, "health": "healthy"}

    async def mock_logs(container_id, tail=100):
        return "mock container logs"

    async def mock_restart(container_id):
        return True

    mgr.spawn_agent = AsyncMock(side_effect=mock_spawn)
    mgr.stop_agent = AsyncMock(side_effect=mock_stop)
    mgr.health_check = AsyncMock(side_effect=mock_health)
    mgr.get_logs = AsyncMock(side_effect=mock_logs)
    mgr.restart_agent = AsyncMock(side_effect=mock_restart)

    return mgr


@pytest.fixture
def mock_nginx_proxy(tmp_path):
    """Mock nginx proxy."""
    proxy = MagicMock(spec=NginxProxy)

    async def mock_add(user_id, port):
        return f"https://{user_id}.agents.test.io"

    async def mock_remove(user_id):
        pass

    proxy.add_proxy = AsyncMock(side_effect=mock_add)
    proxy.remove_proxy = AsyncMock(side_effect=mock_remove)
    return proxy


@pytest.fixture
def orch_app(orch_config, orch_db, mock_container_manager, mock_nginx_proxy):
    """Orchestrator FastAPI app for testing."""
    return create_orchestrator_app(
        config=orch_config,
        db=orch_db,
        container_manager=mock_container_manager,
        nginx_proxy=mock_nginx_proxy,
    )


@pytest.fixture
async def orch_client(orch_app):
    """Async httpx test client for orchestrator."""
    transport = httpx.ASGITransport(app=orch_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _get_session_token(client, orch_app, email="user@test.com"):
    """Helper: request magic link, verify it, return session token."""
    # Request magic link
    resp = await client.post("/auth/request-magic-link", json={"email": email})
    assert resp.status_code == 200

    # Find the token in DB
    db = orch_app.state.db
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT token FROM magic_links WHERE email = ? AND used = 0 ORDER BY rowid DESC LIMIT 1",
            (email.lower(),)
        )
        row = await cursor.fetchone()
        assert row is not None
        token = row["token"]

    # Verify magic link
    resp = await client.get(f"/auth/verify?token={token}")
    assert resp.status_code == 200
    data = resp.json()
    return data["session_token"]


class TestOrchestratorHealth:
    async def test_health_endpoint(self, orch_client):
        """GET /health should return 200."""
        resp = await orch_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "agent-orchestrator"
        assert "users" in data
        assert "agents" in data


class TestAuthFlow:
    async def test_request_magic_link(self, orch_client):
        """POST /auth/request-magic-link should send link."""
        resp = await orch_client.post(
            "/auth/request-magic-link", json={"email": "user@test.com"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    async def test_request_magic_link_invalid_email(self, orch_client):
        """Should reject invalid email."""
        resp = await orch_client.post(
            "/auth/request-magic-link", json={"email": "not-an-email"}
        )
        assert resp.status_code == 400

    async def test_verify_magic_link(self, orch_client, orch_app):
        """GET /auth/verify should return session token."""
        session_token = await _get_session_token(orch_client, orch_app)
        assert session_token

    async def test_verify_creates_new_user(self, orch_client, orch_app):
        """First verify should create a new user."""
        resp = await orch_client.post(
            "/auth/request-magic-link", json={"email": "newbie@test.com"}
        )
        assert resp.status_code == 200

        # Get token from DB
        db = orch_app.state.db
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT token FROM magic_links WHERE email = 'newbie@test.com' LIMIT 1"
            )
            row = await cursor.fetchone()
            token = row["token"]

        resp = await orch_client.get(f"/auth/verify?token={token}")
        data = resp.json()
        assert data["is_new_user"] is True
        assert data["email"] == "newbie@test.com"
        assert data["user_id"]

    async def test_verify_invalid_token(self, orch_client):
        """Should reject invalid token."""
        resp = await orch_client.get("/auth/verify?token=invalid-token")
        assert resp.status_code == 400

    async def test_verify_used_token(self, orch_client, orch_app):
        """Should reject already-used token."""
        # First request and use
        await orch_client.post(
            "/auth/request-magic-link", json={"email": "reuse@test.com"}
        )
        db = orch_app.state.db
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT token FROM magic_links WHERE email = 'reuse@test.com' LIMIT 1"
            )
            row = await cursor.fetchone()
            token = row["token"]

        # First use — OK
        resp1 = await orch_client.get(f"/auth/verify?token={token}")
        assert resp1.status_code == 200

        # Second use — rejected
        resp2 = await orch_client.get(f"/auth/verify?token={token}")
        assert resp2.status_code == 400

    async def test_get_me(self, orch_client, orch_app):
        """GET /auth/me should return user info."""
        session = await _get_session_token(orch_client, orch_app)

        resp = await orch_client.get(
            "/auth/me", headers={"Authorization": f"Bearer {session}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "user@test.com"
        assert data["user_id"]
        assert data["has_agent"] is False

    async def test_get_me_no_auth(self, orch_client):
        """GET /auth/me without auth should return 401."""
        resp = await orch_client.get("/auth/me")
        assert resp.status_code == 401

    async def test_logout(self, orch_client):
        """POST /auth/logout should clear session."""
        resp = await orch_client.post("/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestAgentManagement:
    async def test_create_agent(self, orch_client, orch_app, mock_container_manager):
        """POST /agents/create should spawn container."""
        session = await _get_session_token(orch_client, orch_app)

        resp = await orch_client.post(
            "/agents/create",
            json={"agent_name": "My Test Agent"},
            headers={"Authorization": f"Bearer {session}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["agent_url"]
        assert data["api_token"]
        assert data["status"] == "running"

        mock_container_manager.spawn_agent.assert_called_once()

    async def test_create_agent_duplicate(self, orch_client, orch_app):
        """Should reject creating second agent."""
        session = await _get_session_token(orch_client, orch_app)
        headers = {"Authorization": f"Bearer {session}"}

        # Create first
        await orch_client.post("/agents/create", json={}, headers=headers)

        # Try second — should fail
        resp = await orch_client.post("/agents/create", json={}, headers=headers)
        assert resp.status_code == 409

    async def test_create_agent_no_auth(self, orch_client):
        """Should reject unauthenticated agent creation."""
        resp = await orch_client.post("/agents/create", json={})
        assert resp.status_code == 401

    async def test_get_my_agent(self, orch_client, orch_app):
        """GET /agents/mine should return agent info."""
        session = await _get_session_token(orch_client, orch_app)
        headers = {"Authorization": f"Bearer {session}"}

        # No agent yet
        resp = await orch_client.get("/agents/mine", headers=headers)
        assert resp.json()["has_agent"] is False

        # Create one
        await orch_client.post("/agents/create", json={}, headers=headers)

        # Now has agent
        resp = await orch_client.get("/agents/mine", headers=headers)
        data = resp.json()
        assert data["has_agent"] is True
        assert data["agent_url"]
        assert data["status"] == "running"

    async def test_delete_agent(self, orch_client, orch_app, mock_container_manager, mock_nginx_proxy):
        """DELETE /agents/mine should stop and remove agent."""
        session = await _get_session_token(orch_client, orch_app)
        headers = {"Authorization": f"Bearer {session}"}

        # Create then delete
        await orch_client.post("/agents/create", json={}, headers=headers)
        resp = await orch_client.delete("/agents/mine", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        mock_container_manager.stop_agent.assert_called_once()
        mock_nginx_proxy.remove_proxy.assert_called_once()

        # Verify agent is gone
        resp = await orch_client.get("/agents/mine", headers=headers)
        assert resp.json()["has_agent"] is False

    async def test_delete_agent_no_agent(self, orch_client, orch_app):
        """DELETE /agents/mine with no agent should return 404."""
        session = await _get_session_token(orch_client, orch_app)
        resp = await orch_client.delete(
            "/agents/mine", headers={"Authorization": f"Bearer {session}"}
        )
        assert resp.status_code == 404


class TestAdminEndpoints:
    async def _get_admin_session(self, client, app):
        """Get an admin user's session token."""
        return await _get_session_token(client, app, email="admin@test.com")

    async def test_admin_list_agents(self, orch_client, orch_app):
        """GET /admin/agents should list all agents."""
        session = await self._get_admin_session(orch_client, orch_app)
        resp = await orch_client.get(
            "/admin/agents", headers={"Authorization": f"Bearer {session}"}
        )
        assert resp.status_code == 200
        assert "total" in resp.json()
        assert "agents" in resp.json()

    async def test_admin_list_agents_non_admin(self, orch_client, orch_app):
        """Non-admin should be rejected from admin endpoints."""
        session = await _get_session_token(orch_client, orch_app, "regular@test.com")
        resp = await orch_client.get(
            "/admin/agents", headers={"Authorization": f"Bearer {session}"}
        )
        assert resp.status_code == 403

    async def test_admin_agent_logs(self, orch_client, orch_app, mock_container_manager):
        """GET /admin/agents/{id}/logs should return logs."""
        admin_session = await self._get_admin_session(orch_client, orch_app)
        admin_headers = {"Authorization": f"Bearer {admin_session}"}

        # Create a user + agent first
        user_session = await _get_session_token(orch_client, orch_app, "worker@test.com")
        await orch_client.post(
            "/agents/create", json={}, headers={"Authorization": f"Bearer {user_session}"}
        )

        # Get the agent instance ID
        agents_resp = await orch_client.get("/admin/agents", headers=admin_headers)
        agents = agents_resp.json()["agents"]
        worker_agents = [a for a in agents if a.get("email") == "worker@test.com"]
        assert len(worker_agents) > 0
        instance_id = worker_agents[0]["id"]

        # Get logs
        resp = await orch_client.get(
            f"/admin/agents/{instance_id}/logs", headers=admin_headers
        )
        assert resp.status_code == 200
        assert "logs" in resp.json()

    async def test_admin_restart_agent(self, orch_client, orch_app, mock_container_manager):
        """POST /admin/agents/{id}/restart should restart container."""
        admin_session = await self._get_admin_session(orch_client, orch_app)
        admin_headers = {"Authorization": f"Bearer {admin_session}"}

        # Create a user + agent first
        user_session = await _get_session_token(orch_client, orch_app, "worker2@test.com")
        await orch_client.post(
            "/agents/create", json={}, headers={"Authorization": f"Bearer {user_session}"}
        )

        # Get instance ID
        agents_resp = await orch_client.get("/admin/agents", headers=admin_headers)
        agents = agents_resp.json()["agents"]
        worker_agents = [a for a in agents if a.get("email") == "worker2@test.com"]
        instance_id = worker_agents[0]["id"]

        resp = await orch_client.post(
            f"/admin/agents/{instance_id}/restart", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_container_manager.restart_agent.assert_called_once()

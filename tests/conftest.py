"""Shared pytest fixtures for the Agent Social Network test suite."""

import json
import pytest
from pathlib import Path

from a2a.types import AgentCard, AgentSkill, AgentCapabilities

from src.identity.did import DIDManager
from src.discovery.registry import StaticRegistry
from src.privacy.guard import PrivacyGuard
from src.notification.events import EventBus
from src.storage.db import Storage
from src.matching.embeddings import EmbeddingEngine


# ── Identity fixtures ──────────────────────────────────────────

@pytest.fixture
def did_manager(tmp_path):
    """DIDManager initialized with a fresh keypair saved to tmp_path."""
    identity_path = tmp_path / "identity.json"
    mgr = DIDManager(identity_path=identity_path)
    mgr.init()
    return mgr


@pytest.fixture
def did_manager_no_file():
    """DIDManager initialized in-memory (no file persistence)."""
    mgr = DIDManager()
    mgr.init()
    return mgr


# ── Agent Card fixtures ────────────────────────────────────────

@pytest.fixture
def sample_agent_card():
    """A minimal valid AgentCard for testing."""
    return AgentCard(
        name="Test Agent",
        description="A test agent for unit tests",
        url="http://localhost:9000/",
        version="0.1.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="skill-0",
                name="Python Development",
                description="Expert Python developer with FastAPI and asyncio",
                tags=["python", "fastapi"],
                examples=[],
            ),
            AgentSkill(
                id="skill-1",
                name="Machine Learning",
                description="ML model training and deployment",
                tags=["ml", "ai"],
                examples=[],
            ),
        ],
        security=[],
    )


@pytest.fixture
def sample_agent_card_dict(sample_agent_card):
    """AgentCard as a dict (for signing tests)."""
    return json.loads(sample_agent_card.model_dump_json())


# ── Registry fixtures ──────────────────────────────────────────

@pytest.fixture
def registry(tmp_path):
    """StaticRegistry backed by a temp JSON file."""
    path = tmp_path / "registry.json"
    reg = StaticRegistry(registry_path=path)
    return reg


@pytest.fixture
def populated_registry(registry):
    """StaticRegistry pre-populated with 3 agents."""
    registry.add("http://localhost:9001", name="Agent-A")
    registry.add("http://localhost:9002", name="Agent-B")
    registry.add("http://localhost:9003", name="Agent-C")
    return registry


# ── Privacy fixtures ───────────────────────────────────────────

@pytest.fixture
def privacy_guard():
    """Default PrivacyGuard."""
    return PrivacyGuard()


@pytest.fixture
def strict_privacy_guard():
    """PrivacyGuard in strict mode."""
    return PrivacyGuard(strict_mode=True)


# ── EventBus fixtures ─────────────────────────────────────────

@pytest.fixture
def event_bus():
    """EventBus with no storage backend."""
    return EventBus(max_buffer=50)


# ── Storage fixtures ───────────────────────────────────────────

@pytest.fixture
async def storage(tmp_path):
    """Initialized async SQLite storage with a temp database file."""
    db_path = tmp_path / "test.db"
    store = Storage(db_path=db_path)
    await store.init()
    yield store
    await store.close()


# ── Embedding fixtures ─────────────────────────────────────────

@pytest.fixture(scope="session")
def embedding_engine():
    """Session-scoped EmbeddingEngine (loads model once for all tests)."""
    return EmbeddingEngine()


# ── Context/profile fixtures ──────────────────────────────────

@pytest.fixture
def context_dir(tmp_path):
    """Temp directory with sample context markdown files."""
    ctx = tmp_path / "context"
    ctx.mkdir()

    (ctx / "profile.md").write_text(
        "# Profile\n\nName: Test User\nRole: Software Engineer\n",
        encoding="utf-8",
    )
    (ctx / "skills.md").write_text(
        "# Skills\n\n## Expert\n- Python\n- FastAPI\n- Machine Learning\n",
        encoding="utf-8",
    )
    (ctx / "needs.md").write_text(
        "# Needs\n\n## Looking For\n- UI/UX Designer\n- DevOps Engineer\n",
        encoding="utf-8",
    )
    return tmp_path  # return parent so data_dir / "context" works


@pytest.fixture
def sample_raw_context():
    """Raw context text mimicking what read_context_from_files returns."""
    return """--- skills.md ---
# Skills

## Expert
- Python backend development with FastAPI
- Machine learning model deployment
- Distributed systems design

--- needs.md ---
# Needs

## Looking For
- UI/UX designer for dashboard interfaces
- DevOps engineer for Kubernetes infrastructure
"""

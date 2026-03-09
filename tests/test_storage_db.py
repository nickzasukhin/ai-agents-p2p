"""Tests for Storage — async SQLite CRUD for agents, negotiations, events, matches."""

import pytest
from datetime import datetime, timezone


class TestStorageInit:
    async def test_init_creates_db(self, storage):
        # storage fixture already calls init(); verify it's usable
        agents = await storage.get_all_agents()
        assert isinstance(agents, list)


class TestAgentsCRUD:
    async def test_save_and_get_agent(self, storage):
        await storage.save_agent(
            url="http://localhost:9001",
            name="Agent-A",
            did="did:key:z6MkTest",
            status="online",
        )
        agent = await storage.get_agent("http://localhost:9001")
        assert agent is not None
        assert agent["name"] == "Agent-A"
        assert agent["did"] == "did:key:z6MkTest"

    async def test_get_agent_not_found(self, storage):
        agent = await storage.get_agent("http://nonexistent:9999")
        assert agent is None

    async def test_get_all_agents(self, storage):
        await storage.save_agent(url="http://a:9000", name="A")
        await storage.save_agent(url="http://b:9000", name="B")
        await storage.save_agent(url="http://c:9000", name="C")
        agents = await storage.get_all_agents()
        assert len(agents) == 3

    async def test_get_agent_urls(self, storage):
        await storage.save_agent(url="http://a:9000")
        await storage.save_agent(url="http://b:9000")
        urls = await storage.get_agent_urls()
        assert "http://a:9000" in urls
        assert "http://b:9000" in urls

    async def test_save_agent_upsert(self, storage):
        await storage.save_agent(url="http://a:9000", name="Old")
        await storage.save_agent(url="http://a:9000", name="New")
        agent = await storage.get_agent("http://a:9000")
        assert agent["name"] == "New"


class TestNegotiationsCRUD:
    async def test_save_and_get_negotiation(self, storage):
        neg_dict = {
            "id": "neg-001",
            "our_url": "http://a:9000",
            "their_url": "http://b:9000",
            "our_name": "A",
            "their_name": "B",
            "state": "proposed",
            "match_score": 0.75,
            "match_reasons": ["skill match"],
            "messages": [{"sender": "a", "content": "hi", "round": 1}],
            "collaboration_summary": "Test collab",
            "owner_decision": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await storage.save_negotiation(neg_dict)
        result = await storage.get_negotiation("neg-001")
        assert result is not None
        assert result["state"] == "proposed"

    async def test_get_all_negotiations(self, storage):
        for i in range(3):
            await storage.save_negotiation({
                "id": f"neg-{i}",
                "our_url": "http://a:9000",
                "their_url": f"http://b{i}:9000",
                "our_name": "A",
                "their_name": f"B{i}",
                "state": "proposed",
                "match_score": 0.5 + i * 0.1,
                "match_reasons": [],
                "messages": [],
                "collaboration_summary": "",
                "owner_decision": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        negs = await storage.get_all_negotiations()
        assert len(negs) == 3


class TestEventsCRUD:
    async def test_save_and_get_events(self, storage):
        ts = datetime.now(timezone.utc).isoformat()
        row_id = await storage.save_event("match_found", {"agent": "test"}, ts)
        assert row_id > 0
        events = await storage.get_recent_events(count=10)
        assert len(events) >= 1
        assert events[-1]["type"] == "match_found"

    async def test_get_recent_events_with_type_filter(self, storage):
        ts = datetime.now(timezone.utc).isoformat()
        await storage.save_event("match_found", {"a": 1}, ts)
        await storage.save_event("negotiation_started", {"b": 2}, ts)
        await storage.save_event("match_found", {"c": 3}, ts)

        matches = await storage.get_recent_events(count=10, event_type="match_found")
        assert all(e["type"] == "match_found" for e in matches)


class TestMatchesCRUD:
    async def test_save_and_get_matches(self, storage):
        await storage.save_match(
            our_url="http://a:9000",
            their_url="http://b:9000",
            their_name="B",
            score=0.85,
            is_mutual=True,
            skill_matches_json="[]",
            their_skills_text="Python, ML",
            their_description="A test agent",
            discovered_at=datetime.now(timezone.utc).isoformat(),
        )
        matches = await storage.get_all_matches()
        assert len(matches) == 1
        assert matches[0]["score"] == 0.85

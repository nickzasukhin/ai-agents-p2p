"""Tests for relay message store."""

import time
import pytest

from src.network.relay import RelayStore, RelayMessage


class TestRelayRegistration:
    def test_register_agent(self):
        store = RelayStore()
        store.register("did:key:z123", {"name": "Test Agent"})
        assert store.is_registered("did:key:z123")

    def test_not_registered_by_default(self):
        store = RelayStore()
        assert not store.is_registered("did:key:z999")

    def test_get_registration(self):
        store = RelayStore()
        store.register("did:key:z123", {"name": "Test", "url": "http://example.com"})
        reg = store.get_registration("did:key:z123")
        assert reg is not None
        assert reg["name"] == "Test"
        assert "registered_at" in reg

    def test_get_registration_not_found(self):
        store = RelayStore()
        assert store.get_registration("did:key:z999") is None

    def test_unregister(self):
        store = RelayStore()
        store.register("did:key:z123", {"name": "Test"})
        assert store.unregister("did:key:z123")
        assert not store.is_registered("did:key:z123")

    def test_unregister_nonexistent(self):
        store = RelayStore()
        assert not store.unregister("did:key:z999")

    def test_list_registered(self):
        store = RelayStore()
        store.register("did:key:z1", {"name": "A"})
        store.register("did:key:z2", {"name": "B"})
        listed = store.list_registered()
        assert len(listed) == 2
        dids = {r["did"] for r in listed}
        assert "did:key:z1" in dids
        assert "did:key:z2" in dids


class TestRelayMessageQueue:
    def test_enqueue_dequeue(self):
        store = RelayStore()
        store.register("did:key:z123", {"name": "Test"})

        success = store.enqueue("did:key:z123", "http://sender:9000", {"msg": "hello"})
        assert success

        msgs = store.dequeue("did:key:z123")
        assert len(msgs) == 1
        assert msgs[0]["body"]["msg"] == "hello"
        assert msgs[0]["sender_url"] == "http://sender:9000"

    def test_dequeue_clears_queue(self):
        store = RelayStore()
        store.register("did:key:z123", {"name": "Test"})
        store.enqueue("did:key:z123", "s", {"n": 1})

        store.dequeue("did:key:z123")
        msgs = store.dequeue("did:key:z123")
        assert len(msgs) == 0

    def test_enqueue_unregistered_fails(self):
        store = RelayStore()
        success = store.enqueue("did:key:z999", "http://sender:9000", {"msg": "hello"})
        assert not success

    def test_queue_limit(self):
        store = RelayStore(max_messages=2)
        store.register("did:key:z123", {"name": "Test"})

        store.enqueue("did:key:z123", "s", {"n": 1})
        store.enqueue("did:key:z123", "s", {"n": 2})
        success = store.enqueue("did:key:z123", "s", {"n": 3})
        assert not success

    def test_multiple_messages(self):
        store = RelayStore()
        store.register("did:key:z123", {"name": "Test"})

        store.enqueue("did:key:z123", "s1", {"n": 1})
        store.enqueue("did:key:z123", "s2", {"n": 2})

        msgs = store.dequeue("did:key:z123")
        assert len(msgs) == 2


class TestRelayStats:
    def test_stats_empty(self):
        store = RelayStore()
        stats = store.get_stats()
        assert stats["registered_agents"] == 0
        assert stats["pending_messages"] == 0

    def test_stats_with_data(self):
        store = RelayStore()
        store.register("did:key:z1", {"name": "A"})
        store.register("did:key:z2", {"name": "B"})
        store.enqueue("did:key:z1", "s", {"n": 1})

        stats = store.get_stats()
        assert stats["registered_agents"] == 2
        assert stats["pending_messages"] == 1


class TestRelayTTL:
    def test_expired_messages_evicted_on_enqueue(self):
        store = RelayStore(ttl=0.01)  # 10ms TTL
        store.register("did:key:z123", {"name": "Test"})
        store.enqueue("did:key:z123", "s", {"n": 1})

        time.sleep(0.02)  # Wait for TTL to expire

        # Enqueue triggers eviction of expired messages
        store.enqueue("did:key:z123", "s", {"n": 2})
        msgs = store.dequeue("did:key:z123")
        # Only the second message should remain
        assert len(msgs) == 1
        assert msgs[0]["body"]["n"] == 2

    def test_expired_messages_not_returned_on_dequeue(self):
        store = RelayStore(ttl=0.01)
        store.register("did:key:z123", {"name": "Test"})
        store.enqueue("did:key:z123", "s", {"n": 1})

        time.sleep(0.02)

        msgs = store.dequeue("did:key:z123")
        assert len(msgs) == 0

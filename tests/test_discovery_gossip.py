"""Tests for GossipProtocol — peer list merge and exchange."""

import pytest
from src.discovery.gossip import GossipProtocol
from src.discovery.registry import StaticRegistry


class TestGossipPeerList:
    def test_get_peer_list_excludes_self(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://localhost:9001")
        peers = gossip.get_peer_list()
        urls = [p["url"] for p in peers]
        assert "http://localhost:9001" not in urls

    def test_get_peer_list_returns_others(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://localhost:9999")
        peers = gossip.get_peer_list()
        assert len(peers) == 3


class TestGossipMerge:
    def test_merge_adds_new_peers(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://self:9000")
        new = gossip.merge_peer_list(
            [{"url": "http://new-agent:9005"}],
            source_url="http://source:9000",
        )
        assert "http://new-agent:9005" in new
        assert len(populated_registry) == 4  # 3 original + 1 new

    def test_merge_skips_self(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://self:9000")
        new = gossip.merge_peer_list(
            [{"url": "http://self:9000"}],
            source_url="http://other:9000",
        )
        assert "http://self:9000" not in new

    def test_merge_skips_known(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://self:9000")
        new = gossip.merge_peer_list(
            [{"url": "http://localhost:9001"}],  # already in registry
            source_url="http://source:9000",
        )
        assert len(new) == 0

    def test_merge_returns_only_new_urls(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://self:9000")
        new = gossip.merge_peer_list(
            [
                {"url": "http://localhost:9001"},  # known
                {"url": "http://brand-new:9000"},  # new
            ],
            source_url="http://source:9000",
        )
        assert "http://brand-new:9000" in new
        assert "http://localhost:9001" not in new


class TestGossipStats:
    def test_get_stats_structure(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://self:9000")
        stats = gossip.get_stats()
        assert "rounds" in stats
        assert "peers_learned" in stats
        assert "known_peers" in stats

    def test_stats_peers_learned_updates(self, populated_registry):
        gossip = GossipProtocol(registry=populated_registry, own_url="http://self:9000")
        gossip.merge_peer_list([{"url": "http://new:9000"}], "http://src:9000")
        stats = gossip.get_stats()
        assert stats["peers_learned"] >= 1


class TestGossipExchange:
    async def test_exchange_with_unreachable_peer(self, populated_registry):
        gossip = GossipProtocol(
            registry=populated_registry,
            own_url="http://self:9000",
            timeout=1.0,
        )
        # Exchange with non-existent peer should not raise
        result = await gossip.exchange_with_peer("http://nonexistent:9999")
        assert isinstance(result, list)

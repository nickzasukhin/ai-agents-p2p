"""Tests for tunnel management."""

import pytest
from unittest.mock import patch

from src.network.tunnel import start_tunnel, TunnelInfo, TUNNEL_PATTERNS


class TestTunnelPatterns:
    def test_bore_pattern_matches(self):
        match = TUNNEL_PATTERNS["bore"].search("listening at bore.pub:12345")
        assert match is not None
        assert match.group(1) == "bore.pub:12345"

    def test_bore_pattern_with_dash(self):
        match = TUNNEL_PATTERNS["bore"].search("listening at my-relay.example.com:8080")
        assert match is not None

    def test_cloudflared_pattern_matches(self):
        match = TUNNEL_PATTERNS["cloudflared"].search(
            "INF +---  https://abc-123-xyz.trycloudflare.com  ---+"
        )
        assert match is not None
        assert "trycloudflare.com" in match.group(1)

    def test_ngrok_pattern_matches(self):
        match = TUNNEL_PATTERNS["ngrok"].search(
            'msg="started tunnel" url=https://abc123.ngrok-free.app'
        )
        assert match is not None
        assert "ngrok" in match.group(1)

    def test_ngrok_pattern_no_match_on_random(self):
        match = TUNNEL_PATTERNS["ngrok"].search("random text without url")
        assert match is None


class TestStartTunnel:
    async def test_missing_binary_returns_none(self):
        with patch("shutil.which", return_value=None):
            result = await start_tunnel("bore", 9000)
            assert result is None

    async def test_unknown_provider_returns_none(self):
        result = await start_tunnel("unknown_provider", 9000)
        assert result is None


class TestTunnelInfo:
    def test_to_dict(self):
        info = TunnelInfo(provider="bore", public_url="http://bore.pub:12345")
        d = info.to_dict()
        assert d["provider"] == "bore"
        assert d["public_url"] == "http://bore.pub:12345"
        assert d["running"] is False

    def test_to_dict_no_process(self):
        info = TunnelInfo(provider="ngrok", public_url="https://abc.ngrok.app")
        assert info.to_dict()["running"] is False

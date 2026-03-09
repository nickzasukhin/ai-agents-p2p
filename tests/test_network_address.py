"""Tests for NAT traversal address resolution."""

import struct
import pytest

from src.network.address import (
    resolve_public_url,
    check_reachability,
    _parse_stun_response,
    STUN_MAGIC_COOKIE,
    STUN_ATTR_XOR_MAPPED_ADDRESS,
    STUN_ATTR_MAPPED_ADDRESS,
    STUN_FAMILY_IPV4,
)


class TestResolvePublicUrl:
    async def test_explicit_url_wins(self):
        url = await resolve_public_url(port=9000, public_url="https://my-agent.example.com")
        assert url == "https://my-agent.example.com"

    async def test_explicit_url_strips_trailing_slash(self):
        url = await resolve_public_url(port=9000, public_url="https://example.com/")
        assert url == "https://example.com"

    async def test_default_is_localhost(self):
        url = await resolve_public_url(port=9000)
        assert url == "http://localhost:9000"

    async def test_custom_port_in_localhost(self):
        url = await resolve_public_url(port=9001)
        assert url == "http://localhost:9001"

    async def test_detect_ip_false_uses_localhost(self):
        url = await resolve_public_url(port=9002, detect_ip=False)
        assert url == "http://localhost:9002"

    async def test_explicit_url_takes_priority_over_detect_ip(self):
        url = await resolve_public_url(
            port=9000,
            public_url="http://my-server.com:8080",
            detect_ip=True,
        )
        assert url == "http://my-server.com:8080"


class TestParseStunResponse:
    def test_parse_empty_returns_none(self):
        assert _parse_stun_response(b"") is None

    def test_parse_short_data_returns_none(self):
        assert _parse_stun_response(b"\x00" * 10) is None

    def test_parse_header_only_returns_none(self):
        assert _parse_stun_response(b"\x00" * 20) is None

    def test_parse_xor_mapped_address(self):
        """Build a valid STUN response with XOR-MAPPED-ADDRESS for 203.0.113.5."""
        # 20-byte header
        header = b"\x01\x01" + b"\x00\x0c" + struct.pack("!I", STUN_MAGIC_COOKIE) + b"\x00" * 12

        # XOR-MAPPED-ADDRESS attribute (type=0x0020, length=8)
        # Family: IPv4 (0x01), XOR'd port and IP
        ip_int = (203 << 24) | (0 << 16) | (113 << 8) | 5
        xor_ip = struct.pack("!I", ip_int ^ STUN_MAGIC_COOKIE)
        xor_port = struct.pack("!H", 9000 ^ (STUN_MAGIC_COOKIE >> 16))

        attr = struct.pack("!HH", STUN_ATTR_XOR_MAPPED_ADDRESS, 8)
        attr += b"\x00"  # reserved
        attr += bytes([STUN_FAMILY_IPV4])  # family
        attr += xor_port
        attr += xor_ip

        data = header + attr
        result = _parse_stun_response(data)
        assert result == "203.0.113.5"

    def test_parse_mapped_address_fallback(self):
        """Build a STUN response with MAPPED-ADDRESS (legacy) for 198.51.100.1."""
        header = b"\x01\x01" + b"\x00\x0c" + struct.pack("!I", STUN_MAGIC_COOKIE) + b"\x00" * 12

        # MAPPED-ADDRESS attribute (type=0x0001, length=8)
        import socket
        ip_bytes = socket.inet_aton("198.51.100.1")
        attr = struct.pack("!HH", STUN_ATTR_MAPPED_ADDRESS, 8)
        attr += b"\x00"  # reserved
        attr += bytes([STUN_FAMILY_IPV4])  # family
        attr += struct.pack("!H", 9000)  # port
        attr += ip_bytes

        data = header + attr
        result = _parse_stun_response(data)
        assert result == "198.51.100.1"


class TestCheckReachability:
    async def test_unreachable_url(self):
        result = await check_reachability("http://192.0.2.1:9999", timeout=1.0)
        assert result["reachable"] is False
        assert result["url"] == "http://192.0.2.1:9999"

    async def test_result_has_error_field(self):
        result = await check_reachability("http://192.0.2.1:9999", timeout=1.0)
        assert "error" in result

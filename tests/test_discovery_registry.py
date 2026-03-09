"""Tests for StaticRegistry — JSON-backed agent URL storage."""

import json
import pytest
from src.discovery.registry import StaticRegistry


class TestRegistryBasics:
    def test_empty_registry(self, registry):
        assert len(registry) == 0
        assert registry.get_all_urls() == []

    def test_add_agent(self, registry):
        registry.add("http://localhost:9001")
        assert len(registry) == 1
        assert "http://localhost:9001" in registry.get_all_urls()

    def test_add_with_name(self, registry):
        registry.add("http://localhost:9001", name="Agent-A")
        records = registry.get_all_records()
        assert records[0].name == "Agent-A"

    def test_add_duplicate_ignored(self, registry):
        registry.add("http://localhost:9001")
        registry.add("http://localhost:9001")
        assert len(registry) == 1

    def test_remove_agent(self, registry):
        registry.add("http://localhost:9001")
        registry.remove("http://localhost:9001")
        assert len(registry) == 0

    def test_remove_nonexistent_no_error(self, registry):
        registry.remove("http://nonexistent:9999")  # should not raise


class TestRegistryStatus:
    def test_update_status(self, populated_registry):
        populated_registry.update_status("http://localhost:9001", status="online", name="Updated")
        records = populated_registry.get_all_records()
        rec = next(r for r in records if r.url == "http://localhost:9001")
        assert rec.status == "online"
        assert rec.name == "Updated"

    def test_update_status_unknown_url(self, registry):
        # Should not raise
        registry.update_status("http://unknown:9999", status="online")

    def test_get_online_urls(self, populated_registry):
        populated_registry.update_status("http://localhost:9001", status="online")
        populated_registry.update_status("http://localhost:9002", status="offline")
        online = populated_registry.get_online_urls()
        assert "http://localhost:9001" in online
        assert "http://localhost:9002" not in online


class TestRegistryPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "reg.json"
        reg1 = StaticRegistry(registry_path=path)
        reg1.add("http://a:9000", name="A")
        reg1.add("http://b:9000", name="B")
        reg1.save()

        reg2 = StaticRegistry(registry_path=path)
        reg2.load()
        assert len(reg2) == 2
        urls = reg2.get_all_urls()
        assert "http://a:9000" in urls
        assert "http://b:9000" in urls

    def test_load_string_list_format(self, tmp_path):
        path = tmp_path / "reg.json"
        path.write_text(json.dumps(["http://a:9000", "http://b:9000"]))
        reg = StaticRegistry(registry_path=path)
        reg.load()
        assert len(reg) == 2

    def test_load_nonexistent_file(self, tmp_path):
        path = tmp_path / "missing.json"
        reg = StaticRegistry(registry_path=path)
        reg.load()  # should not raise
        assert len(reg) == 0

    def test_get_all_records_type(self, populated_registry):
        records = populated_registry.get_all_records()
        assert len(records) == 3
        assert all(hasattr(r, "url") for r in records)

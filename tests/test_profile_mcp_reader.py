"""Tests for read_context_from_files — reading markdown profile files."""

import pytest
from src.profile.mcp_reader import read_context_from_files


class TestReadContextFromFiles:
    async def test_reads_all_files(self, context_dir):
        ctx = await read_context_from_files(str(context_dir))
        assert len(ctx.capabilities) == 3  # profile.md, skills.md, needs.md
        assert len(ctx.raw_text) > 0

    async def test_raw_text_contains_content(self, context_dir):
        ctx = await read_context_from_files(str(context_dir))
        assert "Python" in ctx.raw_text
        assert "UI/UX Designer" in ctx.raw_text

    async def test_capabilities_have_names(self, context_dir):
        ctx = await read_context_from_files(str(context_dir))
        names = [c.name for c in ctx.capabilities]
        # names are derived from filenames
        assert len(names) == 3

    async def test_empty_context_dir(self, tmp_path):
        ctx_dir = tmp_path / "context"
        ctx_dir.mkdir()
        ctx = await read_context_from_files(str(tmp_path))
        assert len(ctx.capabilities) == 0
        assert ctx.raw_text == ""

    async def test_nonexistent_dir(self, tmp_path):
        ctx = await read_context_from_files(str(tmp_path / "missing"))
        assert len(ctx.capabilities) == 0

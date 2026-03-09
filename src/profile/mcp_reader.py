"""MCP Reader — connects to filesystem MCP server and reads owner context."""

import asyncio
import structlog
from dataclasses import dataclass, field
from pathlib import Path

log = structlog.get_logger()


@dataclass
class OwnerCapability:
    name: str
    description: str
    category: str


@dataclass
class OwnerContext:
    """Raw context collected from MCP servers."""
    capabilities: list[OwnerCapability] = field(default_factory=list)
    raw_text: str = ""


async def read_context_from_files(data_dir: str) -> OwnerContext:
    """Read owner context directly from files in the data directory.

    This is a simplified approach that reads markdown files directly.
    In production, this would use MCP protocol to connect to various
    data sources (filesystem, databases, APIs, etc).
    """
    context_dir = Path(data_dir) / "context"
    if not context_dir.exists():
        log.warning("context_dir_not_found", path=str(context_dir))
        return OwnerContext()

    raw_parts: list[str] = []
    capabilities: list[OwnerCapability] = []

    for md_file in sorted(context_dir.glob("*.md")):
        log.info("reading_context_file", file=md_file.name)
        content = md_file.read_text(encoding="utf-8")
        raw_parts.append(f"--- {md_file.stem} ---\n{content}")

        # Derive a capability entry from each file
        capabilities.append(OwnerCapability(
            name=md_file.stem.replace("_", " ").title(),
            description=content[:200].strip(),
            category=md_file.stem,
        ))

    raw_text = "\n\n".join(raw_parts)
    log.info("context_loaded", files=len(raw_parts), chars=len(raw_text))

    return OwnerContext(capabilities=capabilities, raw_text=raw_text)


async def read_context_via_mcp(data_dir: str) -> OwnerContext:
    """Read owner context via MCP filesystem server.

    Connects to the MCP filesystem server via stdio transport,
    lists available resources, and reads each one.
    """
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        log.warning("mcp_not_available", msg="Falling back to direct file reading")
        return await read_context_from_files(data_dir)

    context_path = str(Path(data_dir).resolve() / "context")

    server_params = StdioServerParameters(
        command="uvx",
        args=["mcp-server-filesystem", context_path],
    )

    raw_parts: list[str] = []
    capabilities: list[OwnerCapability] = []

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                log.info("mcp_session_initialized")

                # List available tools and try to read files
                tools = await session.list_tools()
                log.info("mcp_tools_available", count=len(tools.tools if hasattr(tools, 'tools') else tools))

                # Use read_file tool to read each context file
                context_dir = Path(context_path)
                for md_file in sorted(context_dir.glob("*.md")):
                    try:
                        result = await session.call_tool(
                            "read_file",
                            arguments={"path": str(md_file)},
                        )
                        content = ""
                        if hasattr(result, 'content'):
                            for block in result.content:
                                if hasattr(block, 'text'):
                                    content += block.text
                        raw_parts.append(f"--- {md_file.stem} ---\n{content}")
                        capabilities.append(OwnerCapability(
                            name=md_file.stem.replace("_", " ").title(),
                            description=content[:200].strip(),
                            category=md_file.stem,
                        ))
                        log.info("mcp_file_read", file=md_file.name, chars=len(content))
                    except Exception as e:
                        log.warning("mcp_read_error", file=md_file.name, error=str(e))

    except Exception as e:
        log.warning("mcp_connection_failed", error=str(e), msg="Falling back to direct file reading")
        return await read_context_from_files(data_dir)

    raw_text = "\n\n".join(raw_parts)
    log.info("mcp_context_loaded", files=len(raw_parts), chars=len(raw_text))

    return OwnerContext(capabilities=capabilities, raw_text=raw_text)

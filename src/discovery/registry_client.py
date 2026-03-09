"""Registry Client — multi-registry support + a2aregistry.org integration.

Supports registering in and fetching agents from multiple A2A registries
simultaneously, including the global a2aregistry.org directory.
"""

from __future__ import annotations

import asyncio
import httpx
import structlog

log = structlog.get_logger()

A2A_REGISTRY_URL = "https://a2aregistry.org"


class RegistryClient:
    """Client for working with multiple A2A agent registries."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    async def register(self, registry_url: str, our_url: str) -> bool:
        """Register with a custom registry (our format).

        POST {registry_url}/register  {"url": our_url}
        """
        url = f"{registry_url.rstrip('/')}/register"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json={"url": our_url})
                if resp.status_code == 200:
                    data = resp.json()
                    log.info(
                        "registry_registered",
                        registry=registry_url[:50],
                        did=data.get("did", "")[:30],
                    )
                    return True
                else:
                    log.warning(
                        "registry_register_failed",
                        registry=registry_url[:50],
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return False
        except Exception as e:
            log.warning("registry_register_error", registry=registry_url[:50], error=str(e))
            return False

    async def register_a2a_global(self, our_url: str) -> bool:
        """Register with the global a2aregistry.org.

        POST https://a2aregistry.org/api/agents/register
        {"wellKnownURI": "https://agents.example.com"}
        """
        url = f"{A2A_REGISTRY_URL}/api/agents/register"
        # a2aregistry.org requires full path to agent card
        well_known = our_url.rstrip("/") + "/.well-known/agent-card.json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json={"wellKnownURI": well_known})
                if resp.status_code in (200, 201):
                    log.info("a2a_global_registered", url=our_url)
                    return True
                else:
                    log.warning(
                        "a2a_global_register_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return False
        except Exception as e:
            log.warning("a2a_global_register_error", error=str(e))
            return False

    async def fetch_agents(self, registry_url: str, query: str = "") -> list[dict]:
        """Fetch agents from a custom registry (our format).

        GET {registry_url}/agents?q=query
        """
        url = f"{registry_url.rstrip('/')}/agents"
        params = {}
        if query:
            params["q"] = query

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    agents = data.get("agents", [])
                    log.info(
                        "registry_fetched",
                        registry=registry_url[:50],
                        count=len(agents),
                    )
                    return agents
                else:
                    log.warning(
                        "registry_fetch_failed",
                        registry=registry_url[:50],
                        status=resp.status_code,
                    )
                    return []
        except Exception as e:
            log.warning("registry_fetch_error", registry=registry_url[:50], error=str(e))
            return []

    async def fetch_a2a_global(self, query: str = "") -> list[dict]:
        """Fetch agents from the global a2aregistry.org.

        GET https://a2aregistry.org/api/agents?search=query
        GET https://a2aregistry.org/api/agents?conformance=standard
        """
        url = f"{A2A_REGISTRY_URL}/api/agents"
        params = {"conformance": "standard"}
        if query:
            params["search"] = query

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    # a2aregistry.org returns agents in various formats
                    # Normalize to our format: {url, name, did, description, skills}
                    raw_agents = data if isinstance(data, list) else data.get("agents", [])
                    agents = []
                    for agent in raw_agents:
                        agents.append({
                            "url": agent.get("url", agent.get("wellKnownURI", "")),
                            "name": agent.get("name", ""),
                            "did": agent.get("did", ""),
                            "description": agent.get("description", ""),
                            "skills": agent.get("skills", []),
                        })
                    log.info("a2a_global_fetched", count=len(agents))
                    return agents
                else:
                    log.warning("a2a_global_fetch_failed", status=resp.status_code)
                    return []
        except Exception as e:
            log.warning("a2a_global_fetch_error", error=str(e))
            return []

    async def register_all(
        self,
        registry_urls: list[str],
        our_url: str,
        a2a_registry_enabled: bool = True,
    ) -> dict[str, bool]:
        """Register in all registries concurrently (including a2aregistry.org).

        Returns dict of {registry_url: success}.
        """
        tasks: dict[str, asyncio.Task] = {}

        async with asyncio.TaskGroup() as tg:
            for reg_url in registry_urls:
                tasks[reg_url] = tg.create_task(self.register(reg_url, our_url))

            if a2a_registry_enabled:
                tasks[A2A_REGISTRY_URL] = tg.create_task(
                    self.register_a2a_global(our_url)
                )

        results = {url: task.result() for url, task in tasks.items()}
        success = sum(1 for v in results.values() if v)
        log.info("register_all_complete", total=len(results), success=success)
        return results

    async def fetch_all(
        self,
        registry_urls: list[str],
        query: str = "",
        a2a_registry_enabled: bool = True,
    ) -> list[dict]:
        """Fetch agents from all registries concurrently, deduplicate by URL.

        Returns combined list of agents from all sources.
        """
        all_agents: list[dict] = []
        tasks = []

        for reg_url in registry_urls:
            tasks.append(self.fetch_agents(reg_url, query))

        if a2a_registry_enabled:
            tasks.append(self.fetch_a2a_global(query))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_urls: set[str] = set()
        for result in results:
            if isinstance(result, list):
                for agent in result:
                    url = agent.get("url", "").rstrip("/")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_agents.append(agent)
            elif isinstance(result, Exception):
                log.warning("registry_fetch_exception", error=str(result))

        log.info("fetch_all_complete", total=len(all_agents), sources=len(tasks))
        return all_agents

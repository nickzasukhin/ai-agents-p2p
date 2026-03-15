"""Discovery Loop — background task that periodically discovers and matches agents."""

import asyncio
import structlog
from dataclasses import dataclass, field

from src.discovery.registry import StaticRegistry
from src.discovery.gossip import GossipProtocol
from src.discovery.registry_client import RegistryClient
from src.a2a_client.client import A2AClient, DiscoveredAgent
from src.matching.engine import MatchingEngine, AgentMatch
from src.matching.scorer import MatchContext

log = structlog.get_logger()

# Default interval between discovery rounds (seconds)
DEFAULT_DISCOVERY_INTERVAL = 30


@dataclass
class DiscoveryState:
    """Current state of the discovery loop."""
    discovered_agents: dict[str, DiscoveredAgent] = field(default_factory=dict)  # url -> agent
    matches: list[AgentMatch] = field(default_factory=list)
    last_run: str | None = None
    runs_completed: int = 0
    is_running: bool = False


class DiscoveryLoop:
    """Background task that discovers and matches agents periodically.

    1. Reads URLs from the static registry
    2. Fetches Agent Cards via A2A Client
    3. Runs the matching engine
    4. Stores results for the API to serve
    """

    def __init__(
        self,
        registry: StaticRegistry,
        a2a_client: A2AClient,
        matching_engine: MatchingEngine,
        own_context_raw: str,
        interval: float = DEFAULT_DISCOVERY_INTERVAL,
        gossip: GossipProtocol | None = None,
        dht_node=None,
        dht_agent_info: dict | None = None,
        storage=None,
        our_tags: list[str] | None = None,
        registry_client: RegistryClient | None = None,
        registry_urls: list[str] | None = None,
        a2a_registry_enabled: bool = True,
        our_url: str = "",
    ):
        self.registry = registry
        self.a2a_client = a2a_client
        self.matching = matching_engine
        self.own_context_raw = own_context_raw
        self.interval = interval
        self.gossip = gossip
        self.dht_node = dht_node
        self.dht_agent_info = dht_agent_info or {}
        self.storage = storage
        self.our_tags = our_tags or []
        self.registry_client = registry_client
        self.registry_urls = registry_urls or []
        self.a2a_registry_enabled = a2a_registry_enabled
        self.our_url = our_url
        self.state = DiscoveryState()
        self._task: asyncio.Task | None = None

    async def run_once(self) -> list[AgentMatch]:
        """Run a single discovery + matching cycle."""
        log.info("discovery_cycle_start", run=self.state.runs_completed + 1)

        # Step 1: Fetch from public registries first (Phase 10)
        # This populates the local registry with agents before discovery
        if self.registry_client and (self.registry_urls or self.a2a_registry_enabled):
            try:
                registry_agents = await self.registry_client.fetch_all(
                    self.registry_urls,
                    a2a_registry_enabled=self.a2a_registry_enabled,
                )
                new_from_registry = 0
                known_urls = {u.rstrip("/") for u in self.registry.get_all_urls()}
                for agent_info in registry_agents:
                    agent_url = agent_info.get("url", "").rstrip("/")
                    if agent_url and agent_url not in known_urls:
                        self.registry.add(agent_url)
                        known_urls.add(agent_url)
                        new_from_registry += 1
                if new_from_registry:
                    self.registry.save()
                    log.info("discovery_registry_new_peers", count=new_from_registry)
            except Exception as e:
                log.debug("discovery_registry_error", error=str(e))

        # Step 2: Get URLs from registry
        urls = self.registry.get_all_urls()
        if not urls:
            log.info("discovery_no_peers")
            return []

        # Step 3: Fetch Agent Cards
        discovered = await self.a2a_client.discover_agents(urls)

        # Update registry statuses
        for url in urls:
            found = any(a.url.rstrip("/") == url.rstrip("/") for a in discovered)
            self.registry.update_status(
                url,
                status="online" if found else "offline",
                name=next((a.card.name for a in discovered if a.url.rstrip("/") == url.rstrip("/")), None),
            )

        # Store discovered agents
        for agent in discovered:
            self.state.discovered_agents[agent.url] = agent

        # Step 4: Filter self-matches and deduplicate
        if discovered:
            own = self.our_url.rstrip("/") if self.our_url else ""
            seen_urls: set[str] = set()
            seen_canonical: set[str] = set()
            filtered: list[DiscoveredAgent] = []
            for a in discovered:
                u = a.url.rstrip("/")
                # Filter self
                if own and u == own:
                    continue
                # Dedup by URL
                if u in seen_urls:
                    continue
                # Dedup by canonical URL (provider.url in agent card) to avoid
                # multiple subdomains pointing to the same agent
                canonical = ""
                if a.card and a.card.provider and a.card.provider.url:
                    canonical = a.card.provider.url.rstrip("/")
                if canonical and canonical in seen_canonical:
                    continue
                seen_urls.add(u)
                if canonical:
                    seen_canonical.add(canonical)
                filtered.append(a)
            if len(filtered) < len(discovered):
                log.info("discovery_filtered", original=len(discovered), filtered=len(filtered))
            discovered = filtered

        # Step 5: Build match contexts (Phase 6.7) and run matching
        if discovered:
            match_contexts = await self._build_match_contexts(discovered)
            self.state.matches = self.matching.find_matches(
                self.own_context_raw, discovered,
                match_contexts=match_contexts,
                our_tags=self.our_tags,
            )
            log.info(
                "discovery_matches_found",
                count=len(self.state.matches),
                top=self.state.matches[0].agent_name if self.state.matches else "none",
            )
        else:
            log.info("discovery_no_agents_found")

        # Step 4: Run gossip exchange (Phase 5.3)
        if self.gossip:
            try:
                new_peers = await self.gossip.run_round()
                if new_peers:
                    log.info("discovery_gossip_new_peers", count=len(new_peers))
            except Exception as e:
                log.debug("discovery_gossip_error", error=str(e))

        # Step 5: Re-publish to DHT (Phase 5.4)
        if self.dht_node and self.dht_agent_info.get("did"):
            try:
                await self.dht_node.publish(
                    self.dht_agent_info["did"],
                    self.dht_agent_info,
                )
            except Exception as e:
                log.debug("discovery_dht_publish_error", error=str(e))

        from datetime import datetime, timezone
        self.state.last_run = datetime.now(timezone.utc).isoformat()
        self.state.runs_completed += 1

        return self.state.matches

    async def _loop(self) -> None:
        """Internal loop that runs discovery periodically."""
        self.state.is_running = True
        log.info("discovery_loop_started", interval=self.interval)

        # Initial delay to let the server start
        await asyncio.sleep(3)

        while self.state.is_running:
            try:
                await self.run_once()
            except Exception as e:
                log.error("discovery_loop_error", error=str(e))

            await asyncio.sleep(self.interval)

    def start(self) -> None:
        """Start the discovery loop as a background task."""
        if self._task is not None and not self._task.done():
            log.warning("discovery_loop_already_running")
            return

        self._task = asyncio.create_task(self._loop())
        log.info("discovery_loop_task_created")

    def stop(self) -> None:
        """Stop the discovery loop."""
        self.state.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        log.info("discovery_loop_stopped")

    async def _build_match_contexts(
        self, discovered: list[DiscoveredAgent],
    ) -> dict[str, MatchContext]:
        """Gather per-agent contextual data for multi-factor scoring."""
        contexts: dict[str, MatchContext] = {}
        for agent in discovered:
            url = agent.url
            status = self.registry.get_agent_status(url)
            last_seen = self.registry.get_last_seen(url)

            their_tags: list[str] = []
            if agent.card.skills:
                for skill in agent.card.skills:
                    their_tags.extend(skill.tags or [])

            active_negs = 0
            successful = 0
            failed = 0

            if self.storage:
                try:
                    active_negs = await self.storage.get_active_negotiation_count(url)
                    history = await self.storage.get_negotiation_history_by_peer(url)
                    successful = history.get("successful", 0)
                    failed = history.get("failed", 0)
                except Exception as e:
                    log.debug("match_context_storage_error", url=url, error=str(e))

            contexts[url] = MatchContext(
                agent_url=url,
                status=status,
                active_negotiations=active_negs,
                successful_negotiations=successful,
                failed_negotiations=failed,
                their_tags=their_tags,
                last_seen=last_seen,
            )

        return contexts

    def get_matches(self) -> list[AgentMatch]:
        """Get current match results."""
        return self.state.matches

    def get_discovered_agents(self) -> list[DiscoveredAgent]:
        """Get all discovered agents."""
        return list(self.state.discovered_agents.values())

    def get_status(self) -> dict:
        """Get current discovery status."""
        status = {
            "is_running": self.state.is_running,
            "runs_completed": self.state.runs_completed,
            "last_run": self.state.last_run,
            "discovered_agents": len(self.state.discovered_agents),
            "matches": len(self.state.matches),
            "peers_in_registry": len(self.registry),
        }
        if self.gossip:
            status["gossip"] = self.gossip.get_stats()
        return status

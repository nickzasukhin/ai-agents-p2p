"""Run a single agent node with discovery, negotiation, and SSE notifications.

Usage:
    uv run python scripts/run_node.py
    uv run python scripts/run_node.py --port 9001 --data-dir data/agent-01
    uv run python scripts/run_node.py --port 9000 --peers http://localhost:9001
    uv run python scripts/run_node.py --port 9000 --tunnel bore
    uv run python scripts/run_node.py --port 9000 --public-url http://203.0.113.5:9000
    uv run python scripts/run_node.py --port 9000 --detect-ip
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import structlog
import uvicorn

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.config import AgentConfig
from src.profile.mcp_reader import read_context_from_files
from src.profile.builder import build_agent_card_from_context
from src.discovery.registry import StaticRegistry
from src.discovery.gossip import GossipProtocol
from src.discovery.loop import DiscoveryLoop
from src.discovery.registry_client import RegistryClient
from src.a2a_client.client import A2AClient
from src.matching.embeddings import EmbeddingEngine
from src.matching.engine import MatchingEngine
from src.negotiation.engine import NegotiationEngine
from src.negotiation.manager import NegotiationManager
from src.notification.events import EventBus
from src.privacy.guard import PrivacyGuard
from src.storage.db import Storage
from src.identity.did import DIDManager
from src.discovery.dht import DHTNode
from src.network.address import resolve_public_url
from src.network.tunnel import start_tunnel, stop_tunnel
from src.negotiation.project_manager import ProjectManager
from src.llm.factory import LLMFactory
from src.chat.manager import ChatManager
from src.server import create_app

# Default logging (reconfigured after config is loaded)
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(colors=True),
    ],
)
log = structlog.get_logger()


def configure_logging(log_level: str = "info") -> None:
    """Reconfigure structlog with proper log level filtering."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )
    log.info("logging_configured", level=log_level)


async def build_card(config: AgentConfig, own_url: str, llm=None):
    """Read context and build Agent Card."""
    log.info("reading_context", data_dir=config.data_dir)
    context = await read_context_from_files(config.data_dir)

    agent_url = f"{own_url.rstrip('/')}/"
    log.info("building_agent_card", agent=config.agent_name, url=agent_url)

    card = build_agent_card_from_context(
        context=context,
        agent_name=config.agent_name,
        agent_url=agent_url,
        llm=llm,
    )
    return card, context


def setup_discovery(
    config: AgentConfig,
    context_raw: str,
    own_url: str,
    peers: list[str] | None = None,
    registry_path: str | None = None,
    discovery_interval: float = 30.0,
    dht_node=None,
    dht_agent_info: dict | None = None,
    storage=None,
    our_tags: list[str] | None = None,
    registry_client: RegistryClient | None = None,
    registry_urls: list[str] | None = None,
    a2a_registry_enabled: bool = True,
) -> tuple[DiscoveryLoop | None, GossipProtocol | None]:
    """Set up the discovery loop with registry, gossip, and matching engine."""
    reg_path = registry_path or str(Path(config.data_dir) / "registry.json")
    registry = StaticRegistry(registry_path=reg_path)
    registry.load()

    if peers:
        for peer in peers:
            peer_clean = peer.rstrip("/")
            if peer_clean != own_url.rstrip("/"):
                registry.add(peer_clean)

    # Phase 12.1: Inject seed nodes when no peers and no registries configured
    if not config.skip_seeds and config.seed_nodes and len(registry) == 0:
        seeds_added = 0
        for seed_url in config.seed_nodes:
            seed_clean = seed_url.rstrip("/")
            if seed_clean != own_url.rstrip("/"):
                registry.add(seed_clean)
                seeds_added += 1
        if seeds_added:
            log.info("seed_nodes_injected", count=seeds_added, seeds=config.seed_nodes)

    has_registries = bool(registry_urls) or a2a_registry_enabled
    if len(registry) == 0 and not has_registries:
        log.info("no_peers_configured", msg="Discovery passive — no peers or registries")
        return None, None

    registry.save()

    # Gossip protocol for peer exchange
    # Skip localhost peers when we're operating cross-network
    is_cross_network = "localhost" not in own_url and "127.0.0.1" not in own_url
    gossip = GossipProtocol(
        registry=registry,
        own_url=own_url,
        skip_localhost_peers=is_cross_network,
        timeout=config.gossip_timeout if hasattr(config, 'gossip_timeout') else 5.0,
    )
    log.info("gossip_configured", own_url=own_url, peers=len(registry))

    a2a_client = A2AClient(
        timeout=config.http_timeout if hasattr(config, 'http_timeout') else 10.0,
        own_url=own_url,
        retry_attempts=config.retry_attempts if hasattr(config, 'retry_attempts') else 3,
        retry_base_delay=config.retry_base_delay if hasattr(config, 'retry_base_delay') else 1.0,
    )
    embedding_engine = EmbeddingEngine()
    matching_engine = MatchingEngine(embedding_engine=embedding_engine)

    loop = DiscoveryLoop(
        registry=registry,
        a2a_client=a2a_client,
        matching_engine=matching_engine,
        own_context_raw=context_raw,
        interval=discovery_interval,
        gossip=gossip,
        dht_node=dht_node,
        dht_agent_info=dht_agent_info,
        storage=storage,
        our_tags=our_tags,
        registry_client=registry_client,
        registry_urls=registry_urls,
        a2a_registry_enabled=a2a_registry_enabled,
        our_url=own_url,
    )

    log.info("discovery_configured", peers=len(registry), interval=discovery_interval)
    return loop, gossip


def setup_negotiation(
    config: AgentConfig,
    context_raw: str,
    card_name: str,
    own_url: str,
    event_bus: EventBus,
    privacy_guard: PrivacyGuard,
    storage: Storage | None = None,
    llm=None,
) -> NegotiationManager:
    """Set up the negotiation engine and manager."""
    neg_engine = NegotiationEngine(
        our_context_raw=context_raw,
        our_name=card_name,
        our_url=own_url,
        llm=llm,
        privacy_guard=privacy_guard,
    )

    manager = NegotiationManager(
        engine=neg_engine,
        event_bus=event_bus,
        storage=storage,
    )

    log.info("negotiation_configured", agent=card_name)
    return manager


def setup_project_manager(
    config: AgentConfig,
    negotiation_manager: NegotiationManager,
    event_bus: EventBus,
    own_url: str,
    card_name: str,
    storage: Storage | None = None,
    llm=None,
) -> ProjectManager:
    """Set up the project manager for multi-agent collaborations."""
    pm = ProjectManager(
        negotiation_manager=negotiation_manager,
        event_bus=event_bus,
        our_url=own_url,
        our_name=card_name,
        storage=storage,
        llm=llm,
    )
    log.info("project_manager_configured", agent=card_name)
    return pm


def main():
    parser = argparse.ArgumentParser(description="Run an AI agent node")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument("--data-dir", type=str, default=None, help="Agent data directory")
    parser.add_argument("--name", type=str, default=None, help="Agent name")
    parser.add_argument(
        "--peers", type=str, nargs="*", default=None,
        help="Peer agent URLs"
    )
    parser.add_argument("--registry", type=str, default=None, help="Registry JSON path")
    parser.add_argument(
        "--discovery-interval", type=float, default=30.0,
        help="Seconds between discovery rounds (default: 30)"
    )
    parser.add_argument(
        "--dht-port", type=int, default=None,
        help="UDP port for Kademlia DHT (default: HTTP port + 1000)"
    )
    parser.add_argument(
        "--bootstrap", type=str, nargs="*", default=None,
        help="DHT bootstrap nodes as host:port (e.g., localhost:10000)"
    )
    # NAT Traversal args (Phase 6.3)
    parser.add_argument(
        "--public-url", type=str, default=None,
        help="Public URL for this agent (overrides localhost)"
    )
    parser.add_argument(
        "--detect-ip", action="store_true",
        help="Auto-detect public IP via STUN/HTTP"
    )
    parser.add_argument(
        "--tunnel", type=str, default=None,
        choices=["bore", "ngrok", "cloudflared"],
        help="Start a tunnel for NAT traversal"
    )
    parser.add_argument(
        "--tunnel-server", type=str, default="bore.pub",
        help="Bore relay server (default: bore.pub)"
    )
    parser.add_argument(
        "--relay-url", type=str, default=None,
        help="Register with a relay node at this URL"
    )
    parser.add_argument(
        "--relay-mode", action="store_true",
        help="Enable relay endpoints on this node"
    )
    parser.add_argument(
        "--chat-mode", type=str, default=None,
        choices=["auto", "manual"],
        help="Chat mode: auto (agent chats via LLM) or manual (owner chats)"
    )
    # Phase 10: API Security + Registry
    parser.add_argument(
        "--api-token", type=str, default=None,
        help="Bearer token for owner-facing API endpoints"
    )
    parser.add_argument(
        "--registry-url", type=str, nargs="*", default=None,
        help="Registry URL(s) to register with and fetch agents from (can specify multiple)"
    )
    parser.add_argument(
        "--no-a2a-registry", action="store_true",
        help="Disable auto-registration on a2aregistry.org"
    )
    # Phase 12.1: Seed Nodes
    parser.add_argument(
        "--seed-nodes", type=str, nargs="*", default=None,
        help="Seed node URLs for cold-start bootstrap (overrides defaults)"
    )
    parser.add_argument(
        "--no-seeds", action="store_true",
        help="Disable seed node injection (for isolated testing)"
    )
    args = parser.parse_args()

    config = AgentConfig()
    if args.port:
        config.port = args.port
    if args.data_dir:
        config.data_dir = args.data_dir
    if args.name:
        config.agent_name = args.name
    # Apply NAT args to config
    if args.public_url:
        config.public_url = args.public_url
    if args.detect_ip:
        config.detect_ip = True
    if args.tunnel:
        config.tunnel = args.tunnel
    if args.tunnel_server:
        config.tunnel_server = args.tunnel_server
    if args.relay_url:
        config.relay_url = args.relay_url
    if args.relay_mode:
        config.relay_mode = True
    if args.chat_mode:
        config.chat_mode = args.chat_mode
    # Phase 10: API Security + Registry
    if args.api_token:
        config.api_token = args.api_token
    if args.registry_url:
        config.registry_urls = args.registry_url
    if args.no_a2a_registry:
        config.a2a_registry_enabled = False
    # Phase 12.1: Seed Nodes
    if args.seed_nodes is not None:
        config.seed_nodes = args.seed_nodes
    if args.no_seeds:
        config.skip_seeds = True

    # Apply structured logging with proper level (Phase 6.6)
    configure_logging(config.log_level)

    log.info(
        "starting_agent",
        name=config.agent_name,
        port=config.port,
        data_dir=config.data_dir,
    )

    # ── Phase 6.3: Resolve public URL ──────────────────────────────────
    # Centralize URL resolution: tunnel → explicit → STUN → localhost
    tunnel_info = None

    async def async_resolve():
        nonlocal tunnel_info

        # Step 1: Try tunnel first (it provides a URL)
        if config.tunnel:
            tunnel_info = await start_tunnel(
                provider=config.tunnel,
                local_port=config.port,
                bore_server=config.tunnel_server,
            )
            if tunnel_info:
                config.public_url = tunnel_info.public_url
                log.info("tunnel_started", provider=config.tunnel, url=tunnel_info.public_url)

        # Step 2: Resolve the best URL
        url = await resolve_public_url(
            port=config.port,
            public_url=config.public_url or None,
            detect_ip=config.detect_ip,
        )
        return url

    own_url = asyncio.run(async_resolve())
    log.info("resolved_address", own_url=own_url)

    # ── LLM Provider (Phase 6.9) ─────────────────────────────────────
    llm = None
    if config.openai_api_key:
        llm = LLMFactory.create(
            provider=config.llm_provider,
            api_key=config.openai_api_key,
            model=config.openai_model,
        )
        log.info("llm_provider_ready", provider=llm.name, model=llm.model)

    # ── Build Agent Card + init storage ────────────────────────────────
    async def async_init():
        c, ctx = await build_card(config, own_url, llm=llm)
        db_path = Path(config.data_dir) / "agent.db"
        st = Storage(db_path)
        await st.init()
        log.info("storage_ready", path=str(db_path))
        return c, ctx, st

    card, context, storage = asyncio.run(async_init())
    log.info("agent_card_ready", name=card.name, skills=[s.name for s in card.skills])

    # Init DID identity (generates keypair on first run, loads from file on subsequent)
    identity_path = Path(config.data_dir) / "identity.json"
    did_manager = DIDManager(identity_path=identity_path)
    did_manager.init()
    log.info("did_ready", did=did_manager.did)

    # Create shared components
    event_bus = EventBus(storage=storage)
    privacy_guard = PrivacyGuard()

    # Setup DHT config (actual start deferred to FastAPI startup)
    dht_port = args.dht_port or (config.port + 1000)
    dht_node = DHTNode(
        udp_port=dht_port,
        own_url=own_url,
        node_id=did_manager.node_id(),
    )
    dht_agent_info = {
        "url": own_url,
        "name": card.name,
        "did": did_manager.did,
        "skills_summary": ", ".join(s.name for s in card.skills),
    }

    # Extract our tags from card skills for multi-factor scoring (Phase 6.7)
    our_tags = []
    for skill in card.skills:
        our_tags.extend(skill.tags or [])

    # Merge peers: CLI --peers takes priority, else PEERS env var
    peers_list = args.peers
    if not peers_list and config.peers:
        peers_list = [p.strip() for p in config.peers.split(",") if p.strip()]
        log.info("peers_from_env", peers=peers_list)

    # Setup registry client for public registries (Phase 10)
    registry_client = None
    if config.registry_urls or config.a2a_registry_enabled:
        registry_client = RegistryClient(timeout=config.http_timeout)
        log.info(
            "registry_client_configured",
            urls=config.registry_urls,
            a2a_global=config.a2a_registry_enabled,
        )

    # Setup discovery + gossip (with DHT reference for re-publish)
    discovery_loop, gossip = setup_discovery(
        config=config,
        context_raw=context.raw_text,
        own_url=own_url,
        peers=peers_list,
        registry_path=args.registry,
        discovery_interval=args.discovery_interval,
        dht_node=dht_node,
        dht_agent_info=dht_agent_info,
        storage=storage,
        our_tags=our_tags,
        registry_client=registry_client,
        registry_urls=config.registry_urls,
        a2a_registry_enabled=config.a2a_registry_enabled,
    )

    # Setup negotiation
    negotiation_manager = setup_negotiation(
        config=config,
        context_raw=context.raw_text,
        card_name=card.name,
        own_url=own_url,
        event_bus=event_bus,
        privacy_guard=privacy_guard,
        storage=storage,
        llm=llm,
    )

    # Setup project manager (Phase 6.4)
    project_manager = setup_project_manager(
        config=config,
        negotiation_manager=negotiation_manager,
        event_bus=event_bus,
        own_url=own_url,
        card_name=card.name,
        storage=storage,
        llm=llm,
    )

    # Parse bootstrap nodes (Kademlia requires IP addresses, not hostnames)
    import socket
    bootstrap_nodes = []
    if args.bootstrap:
        for b in args.bootstrap:
            parts = b.split(":")
            if len(parts) == 2:
                host = parts[0]
                port = int(parts[1])
                try:
                    ip = socket.gethostbyname(host)
                    bootstrap_nodes.append((ip, port))
                except socket.gaierror:
                    log.warning("dht_bootstrap_resolve_failed", host=host)
                    bootstrap_nodes.append((host, port))

    log.info("dht_bootstrap_resolved", nodes=bootstrap_nodes)

    # DHT start config for server.py startup event
    dht_config = {
        "bootstrap_nodes": bootstrap_nodes,
        "agent_info": dht_agent_info,
    }

    # Load persisted data in a single event loop
    async def async_load():
        await event_bus.load_from_storage()
        await negotiation_manager.load_from_storage()
        await project_manager.load_from_storage()

    asyncio.run(async_load())

    # Card config for live regeneration (Phase 6.1)
    card_config = {
        "agent_name": config.agent_name,
        "agent_url": f"{own_url.rstrip('/')}/",
        "llm": llm,
    }

    # Relay config (Phase 6.3)
    relay_config = None
    if config.relay_mode or config.relay_url:
        relay_config = {
            "relay_mode": config.relay_mode,
            "relay_url": config.relay_url or None,
            "our_did": did_manager.did,
        }

    # Setup chat manager (Phase 9)
    chat_manager = None
    if llm:
        chat_manager = ChatManager(
            llm=llm,
            event_bus=event_bus,
            privacy_guard=privacy_guard,
            storage=storage,
            our_url=own_url,
            our_name=card.name,
            chat_mode=config.chat_mode,
            max_rounds=config.chat_max_rounds,
        )
        log.info("chat_manager_configured", mode=config.chat_mode, max_rounds=config.chat_max_rounds)

    # Create and run app
    app = create_app(
        card,
        discovery_loop=discovery_loop,
        negotiation_manager=negotiation_manager,
        event_bus=event_bus,
        privacy_guard=privacy_guard,
        storage=storage,
        did_manager=did_manager,
        gossip=gossip,
        dht_node=dht_node,
        dht_config=dht_config,
        data_dir=config.data_dir,
        card_config=card_config,
        project_manager=project_manager,
        relay_config=relay_config,
        tunnel_info=tunnel_info,
        own_url=own_url,
        config=config,
        chat_manager=chat_manager,
    )

    # Phase 10: Auto-register in public registries on startup
    if registry_client and own_url and ("localhost" not in own_url and "127.0.0.1" not in own_url):
        async def _auto_register():
            await asyncio.sleep(10)  # Wait for server to be ready
            try:
                results = await registry_client.register_all(
                    config.registry_urls, own_url, config.a2a_registry_enabled,
                )
                log.info("auto_registration_complete", results=results)
            except Exception as e:
                log.warning("auto_registration_error", error=str(e))

        # Store task ref so it's not garbage collected
        app.state.registry_registration_task = _auto_register

    log.info(
        "server_starting",
        url=own_url,
        agent_card_url=f"{own_url}/.well-known/agent-card.json",
        version="1.1.0",
        discovery="enabled" if discovery_loop else "disabled",
        negotiation="enabled",
        projects="enabled",
        events="enabled",
        tunnel=tunnel_info.provider if tunnel_info else None,
        relay_mode=config.relay_mode,
        registries=len(config.registry_urls),
        a2a_registry=config.a2a_registry_enabled,
    )

    # Signal handler for graceful shutdown (Phase 6.6)
    def _signal_handler(sig, frame):
        log.info("shutdown_signal_received", signal=sig)

    signal.signal(signal.SIGTERM, _signal_handler)

    uvicorn.run(app, host="0.0.0.0", port=config.port, log_level=config.log_level)


if __name__ == "__main__":
    main()

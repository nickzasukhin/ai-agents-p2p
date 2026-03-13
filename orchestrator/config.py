"""Orchestrator configuration via environment variables."""

from __future__ import annotations

import os
from pydantic_settings import BaseSettings


class OrchestratorConfig(BaseSettings):
    """Orchestrator service settings."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Database
    db_path: str = "/opt/orchestrator/data/orchestrator.db"

    # Auth
    jwt_secret: str = "change-me-in-production"  # Must override in production
    magic_link_expiry_minutes: int = 15
    session_expiry_hours: int = 72  # 3 days
    base_url: str = "https://agents.devpunks.io"

    # Email (Resend)
    resend_api_key: str = ""
    email_from: str = "noreply@devpunks.io"
    email_enabled: bool = True

    # Container management
    agent_image: str = "agent-image:latest"
    agent_data_root: str = "/opt/agents/data"
    port_range_start: int = 9100
    port_range_end: int = 9999
    max_agents: int = 100

    # Networking
    domain: str = "agents.devpunks.io"
    nginx_conf_dir: str = "/etc/nginx/conf.d/agents"
    nginx_host_port: int = 8002  # orchestrator port as seen from host (for nginx proxy)
    seed_node_url: str = "https://agents.devpunks.io"
    docker_network: str = ""  # Docker network for agent containers to join (for health checks)

    # Shared agent mode — assign all users to one existing agent
    # (used when not spawning individual containers)
    shared_agent_url: str = ""   # e.g. "https://agents.devpunks.io"
    shared_agent_token: str = "" # API token for the shared agent

    # Agent container environment (passed to spawned containers)
    agent_openai_api_key: str = ""
    agent_openai_model: str = "gpt-4o-mini"
    agent_llm_provider: str = "openai"
    agent_registry_urls: str = '["https://registry.devpunks.io"]'

    # SSL (for nginx proxy template — wildcard cert)
    ssl_cert_path: str = "/etc/letsencrypt/live/agents.devpunks.io/fullchain.pem"
    ssl_key_path: str = "/etc/letsencrypt/live/agents.devpunks.io/privkey.pem"

    # Admin
    admin_emails: list[str] = []  # Emails with admin privileges

    model_config = {
        "env_prefix": "ORCH_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # Ignore non-ORCH_ env vars from .env
    }

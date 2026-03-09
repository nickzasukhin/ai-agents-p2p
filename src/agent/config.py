"""Agent configuration via environment variables / .env file."""

import os
from pydantic import field_validator
from pydantic_settings import BaseSettings


class AgentConfig(BaseSettings):
    agent_name: str = "Agent-000"
    port: int = 9000
    data_dir: str = "data/agent-00"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    llm_provider: str = "openai"
    log_level: str = "info"
    peers: str = ""  # Comma-separated peer URLs (for Docker/K8s; CLI --peers takes priority)

    # --- NAT Traversal (Phase 6.3) ---
    public_url: str = ""          # Explicit public URL override (e.g. http://203.0.113.5:9000)
    detect_ip: bool = False       # Auto-detect public IP via STUN/HTTP
    tunnel: str = ""              # Tunnel provider: "bore", "ngrok", "cloudflared"
    tunnel_server: str = "bore.pub"  # Bore relay server address
    relay_url: str = ""           # URL of a relay node to register with
    relay_mode: bool = False      # Enable relay endpoints on this node

    # --- Chat (Phase 9) ---
    chat_mode: str = "auto"  # "auto" = agent chats via LLM; "manual" = owner chats manually
    chat_max_rounds: int = 10  # Max auto-reply rounds per chat

    # --- API Security (Phase 10) ---
    api_token: str = ""                          # Bearer token for owner endpoints (empty = no auth)
    trusted_proxies: list[str] = ["127.0.0.1"]   # Trusted proxy IPs for X-Forwarded-For

    # --- Registry (Phase 10) ---
    registry_urls: list[str] = []       # List of registry URLs (our + external)
    registry_interval: int = 300        # Re-register interval in seconds
    a2a_registry_enabled: bool = True   # Auto-register on a2aregistry.org

    # --- Production Hardening (Phase 6.6) ---
    cors_origins: list[str] = ["*"]        # Allowed CORS origins
    http_timeout: float = 10.0             # Default httpx client timeout (seconds)
    retry_attempts: int = 3                # HTTP retry count for outbound requests
    retry_base_delay: float = 1.0          # Base delay for exponential backoff (seconds)
    gossip_timeout: float = 5.0            # Gossip exchange timeout (seconds)
    discovery_interval: float = 30.0       # Seconds between discovery rounds
    rate_limit_rpm: int = 120              # Max POST requests per minute per IP (0 = disabled)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be 1-65535, got {v}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"debug", "info", "warning", "error", "critical"}
        if v.lower() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v}")
        return v.lower()

    @field_validator("http_timeout", "retry_base_delay", "gossip_timeout", "discovery_interval")
    @classmethod
    def validate_positive_float(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Must be positive, got {v}")
        return v

    @field_validator("data_dir")
    @classmethod
    def validate_data_dir(cls, v: str) -> str:
        from pathlib import Path
        parent = Path(v).parent
        if parent.exists() and not os.access(str(parent), os.W_OK):
            raise ValueError(f"Parent directory not writable: {parent}")
        return v

    @field_validator("registry_urls", mode="before")
    @classmethod
    def parse_registry_urls(cls, v):
        """Parse registry URLs from comma-separated string or list."""
        if isinstance(v, str):
            return [u.strip() for u in v.split(",") if u.strip()]
        return v

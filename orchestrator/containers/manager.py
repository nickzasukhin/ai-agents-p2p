"""Container manager — spawns and manages Docker containers for user agents.

Uses the Docker SDK (docker-py) for container lifecycle management.
Each user gets an isolated container with its own:
  - DID identity
  - SQLite database
  - API token
  - Data directory
"""

from __future__ import annotations

import secrets
import asyncio
from pathlib import Path

import structlog

from orchestrator.containers.port_allocator import PortAllocator

log = structlog.get_logger()


class ContainerManager:
    """Manage Docker containers for personal agent instances."""

    def __init__(
        self,
        agent_image: str = "agent-image:latest",
        data_root: str = "/opt/agents/data",
        port_allocator: PortAllocator | None = None,
        seed_node_url: str = "https://agents.devpunks.io",
        domain: str = "agents.devpunks.io",
        docker_client=None,
        extra_env: dict[str, str] | None = None,
        orch_network: str = "",
    ):
        self.agent_image = agent_image
        self.data_root = Path(data_root)
        self.ports = port_allocator or PortAllocator()
        self.seed_node_url = seed_node_url
        self.domain = domain
        self._docker = docker_client  # Lazy init
        self.extra_env = extra_env or {}
        self.orch_network = orch_network  # Docker network to join for health checks

    def _get_docker(self):
        """Lazy-initialize Docker client."""
        if self._docker is None:
            try:
                import docker
                self._docker = docker.from_env()
            except Exception as e:
                log.error("docker_client_init_failed", error=str(e))
                raise RuntimeError("Docker is not available") from e
        return self._docker

    async def spawn_agent(
        self,
        user_id: str,
        subdomain: str | None = None,
        agent_name: str = "Agent",
        used_ports: set[int] | None = None,
    ) -> dict:
        """Spawn a new agent container for a user.

        Args:
            user_id: Unique user identifier.
            subdomain: Fun subdomain prefix (e.g. "gandalf"). Falls back to user_id.
            agent_name: Display name for the agent.
            used_ports: Set of currently used ports (from DB).

        Returns:
            Dict with container info: {container_id, port, api_token, agent_url, status}.
        """
        used = used_ports or set()
        sub = subdomain or user_id

        # 1. Allocate port
        port = self.ports.allocate(used)
        if port is None:
            raise RuntimeError("No available ports — maximum agents reached")

        # 2. Create data directory
        data_dir = self.data_root / user_id
        data_dir.mkdir(parents=True, exist_ok=True)
        context_dir = data_dir / "context"
        context_dir.mkdir(exist_ok=True)

        # 3. Generate API token
        api_token = secrets.token_urlsafe(32)

        # 4. Build agent URL (use fun subdomain)
        agent_url = f"https://{sub}.{self.domain}"

        # 5. Run container
        container_id = await self._run_container(
            user_id=user_id,
            subdomain=sub,
            port=port,
            data_dir=str(data_dir),
            api_token=api_token,
            agent_name=agent_name,
            agent_url=agent_url,
        )

        log.info(
            "agent_spawned",
            user_id=user_id,
            subdomain=sub,
            port=port,
            container_id=container_id[:12] if container_id else None,
            url=agent_url,
        )

        return {
            "container_id": container_id,
            "port": port,
            "api_token": api_token,
            "agent_url": agent_url,
            "status": "starting",
        }

    async def _run_container(
        self,
        user_id: str,
        subdomain: str,
        port: int,
        data_dir: str,
        api_token: str,
        agent_name: str,
        agent_url: str,
    ) -> str:
        """Actually run the Docker container. Returns container ID."""
        docker = self._get_docker()

        env = {
            "AGENT_NAME": agent_name,
            "PORT": "9000",
            "DATA_DIR": "/data",
            "API_TOKEN": api_token,
            "PUBLIC_URL": agent_url,
            "PEERS": self.seed_node_url,
            "LOG_LEVEL": "info",
            "A2A_REGISTRY_ENABLED": "true",
        }
        # Merge extra env vars (OPENAI_API_KEY, LLM_PROVIDER, etc.)
        if self.extra_env:
            env.update(self.extra_env)

        # Run in event loop executor to avoid blocking
        orch_network = self.orch_network

        def _run():
            container = docker.containers.run(
                self.agent_image,
                detach=True,
                name=f"agent-{subdomain}",
                environment=env,
                ports={"9000/tcp": port, "10000/udp": port + 1000},
                volumes={data_dir: {"bind": "/data", "mode": "rw"}},
                restart_policy={"Name": "unless-stopped"},
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,  # 50% of one CPU
            )
            # Connect to orchestrator network so health checks work
            if orch_network:
                try:
                    net = docker.networks.get(orch_network)
                    net.connect(container)
                    log.info("container_joined_network", network=orch_network,
                             container=container.name)
                except Exception as e:
                    log.warning("network_connect_failed", network=orch_network,
                                error=str(e))
            return container.id

        loop = asyncio.get_event_loop()
        container_id = await loop.run_in_executor(None, _run)
        return container_id

    async def stop_agent(self, container_id: str) -> bool:
        """Stop and remove an agent container."""
        try:
            docker = self._get_docker()

            def _stop():
                try:
                    container = docker.containers.get(container_id)
                    container.stop(timeout=10)
                    container.remove()
                    return True
                except Exception as e:
                    log.warning("container_stop_error", error=str(e))
                    return False

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _stop)

        except Exception as e:
            log.error("stop_agent_error", error=str(e))
            return False

    async def get_container_ip(self, container_id: str) -> str | None:
        """Get the container's IP address on the Docker bridge network.

        This is needed because the orchestrator runs inside Docker and can't
        reach host-mapped ports via 127.0.0.1. Instead, we use the container's
        internal IP on the bridge network.
        """
        try:
            docker = self._get_docker()

            def _get_ip():
                container = docker.containers.get(container_id)
                networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
                # Try bridge network first, then any available network
                for net_name in ("bridge", *networks.keys()):
                    if net_name in networks:
                        ip = networks[net_name].get("IPAddress")
                        if ip:
                            return ip
                return None

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _get_ip)
        except Exception as e:
            log.warning("get_container_ip_failed", error=str(e))
            return None

    async def health_check(self, container_id: str) -> dict:
        """Check health of an agent container."""
        try:
            docker = self._get_docker()

            def _check():
                try:
                    container = docker.containers.get(container_id)
                    return {
                        "status": container.status,
                        "running": container.status == "running",
                        "health": container.attrs.get("State", {}).get("Health", {}).get("Status", "unknown"),
                    }
                except Exception:
                    return {"status": "not_found", "running": False, "health": "unknown"}

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _check)

        except Exception:
            return {"status": "error", "running": False, "health": "unknown"}

    async def get_logs(self, container_id: str, tail: int = 100) -> str:
        """Get container logs."""
        try:
            docker = self._get_docker()

            def _logs():
                container = docker.containers.get(container_id)
                return container.logs(tail=tail).decode("utf-8", errors="replace")

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _logs)

        except Exception as e:
            return f"Error fetching logs: {e}"

    async def restart_agent(self, container_id: str) -> bool:
        """Restart an agent container."""
        try:
            docker = self._get_docker()

            def _restart():
                container = docker.containers.get(container_id)
                container.restart(timeout=10)
                return True

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _restart)

        except Exception as e:
            log.error("restart_agent_error", error=str(e))
            return False

"""A2A Client — fetches Agent Cards from remote agents via HTTP.

Supports DID identity verification (TOFU — Trust On First Use):
- On first contact, the peer's DID is recorded
- On subsequent contacts, the DID is checked against the stored value
- Cards with invalid signatures are flagged but not rejected (soft TOFU)

Production features (Phase 6.6):
- Shared httpx.AsyncClient for connection pooling
- Exponential backoff retry on transient errors (ConnectError, TimeoutException)
- Configurable timeout and retry parameters
"""

import asyncio
import httpx
import structlog
from dataclasses import dataclass, field
from a2a.types import AgentCard

log = structlog.get_logger()

# Well-known path for A2A Agent Cards
AGENT_CARD_PATH = "/.well-known/agent-card.json"
IDENTITY_PATH = "/identity"


@dataclass
class DiscoveredAgent:
    """An agent discovered via A2A protocol."""
    url: str
    card: AgentCard
    skills_text: str = ""  # Concatenated skill descriptions for embedding
    did: str = ""          # DID identity (if available)
    verified: bool = False  # Whether the card signature was verified


class A2AClient:
    """HTTP client for fetching A2A Agent Cards from remote agents.

    Connects to other agent nodes, retrieves their public Agent Cards,
    and parses them into structured data for the matching engine.

    Supports DID identity verification via the /identity endpoint.

    Features:
    - Shared httpx.AsyncClient for connection pooling
    - Retry with exponential backoff on transient errors
    """

    def __init__(
        self,
        timeout: float = 10.0,
        own_url: str | None = None,
        retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
    ):
        self.timeout = timeout
        self.own_url = own_url  # Skip self-discovery
        self.retry_attempts = retry_attempts
        self.retry_base_delay = retry_base_delay
        # TOFU store: url → first-seen DID
        self._known_dids: dict[str, str] = {}
        # Shared HTTP client (lazy-initialized)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init a shared httpx client for connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the shared HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request_with_retry(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        """HTTP request with exponential backoff retry.

        Retries on ConnectError and TimeoutException.
        Does NOT retry on HTTP status errors (4xx, 5xx).
        """
        client = await self._get_client()
        last_exc: Exception | None = None
        for attempt in range(self.retry_attempts):
            try:
                resp = await getattr(client, method)(url, **kwargs)
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exc = e
                if attempt < self.retry_attempts - 1:
                    delay = self.retry_base_delay * (2 ** attempt)
                    log.debug("http_retry", url=url[:60], attempt=attempt + 1, delay=delay)
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    async def _fetch_identity(self, base_url: str) -> dict | None:
        """Fetch DID identity and signed card from a peer.

        Returns dict with {did, public_key, signed_card} or None.
        """
        url = base_url.rstrip("/") + IDENTITY_PATH
        try:
            resp = await self._request_with_retry("get", url)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    async def _verify_peer_identity(self, base_url: str) -> tuple[str, bool]:
        """Verify peer identity using TOFU (Trust On First Use).

        Returns (did, verified) tuple.
        """
        identity = await self._fetch_identity(base_url)
        if not identity or "error" in identity:
            return "", False

        did = identity.get("did", "")
        signed_card = identity.get("signed_card")

        if not did or not signed_card:
            return "", False

        # Lazy import to avoid circular dependency
        from src.identity.did import DIDManager

        # Verify the signature
        verified = DIDManager.verify_card(signed_card)

        if verified:
            # TOFU: check if DID changed since first contact
            known = self._known_dids.get(base_url)
            if known and known != did:
                log.warning(
                    "did_changed",
                    url=base_url,
                    old_did=known[:30],
                    new_did=did[:30],
                    msg="DID changed since first contact! Possible impersonation.",
                )
                # Still mark as verified (signature is valid), but log warning
            elif not known:
                # First contact — record DID (Trust On First Use)
                self._known_dids[base_url] = did
                log.info("did_first_contact", url=base_url, did=did[:30])
            else:
                log.debug("did_verified", url=base_url, did=did[:30])
        else:
            log.warning("did_verification_failed", url=base_url, did=did[:30])

        return did, verified

    async def fetch_agent_card(self, base_url: str) -> DiscoveredAgent | None:
        """Fetch an Agent Card from a remote agent.

        Args:
            base_url: The base URL of the agent (e.g., "http://localhost:9001")

        Returns:
            DiscoveredAgent with parsed card, or None if unreachable.
        """
        # Don't discover ourselves
        if self.own_url and base_url.rstrip("/") == self.own_url.rstrip("/"):
            log.debug("skipping_self_discovery", url=base_url)
            return None

        url = base_url.rstrip("/") + AGENT_CARD_PATH

        try:
            response = await self._request_with_retry("get", url)
            response.raise_for_status()
            data = response.json()

            card = AgentCard(**data)

            # Build a text representation of skills for embedding
            skills_parts = []
            if card.skills:
                for skill in card.skills:
                    parts = [skill.name]
                    if skill.description:
                        parts.append(skill.description)
                    if skill.tags:
                        parts.append(", ".join(skill.tags))
                    skills_parts.append(" — ".join(parts))

            skills_text = "\n".join(skills_parts)

            # Verify DID identity (non-blocking — soft TOFU)
            did, verified = await self._verify_peer_identity(base_url)

            log.info(
                "agent_card_fetched",
                url=base_url,
                name=card.name,
                skills=len(card.skills) if card.skills else 0,
                did=did[:30] if did else "none",
                verified=verified,
            )

            return DiscoveredAgent(
                url=base_url,
                card=card,
                skills_text=skills_text,
                did=did,
                verified=verified,
            )

        except httpx.ConnectError:
            log.warning("agent_unreachable", url=base_url)
            return None
        except httpx.TimeoutException:
            log.warning("agent_timeout", url=base_url)
            return None
        except httpx.HTTPStatusError as e:
            log.warning("agent_card_http_error", url=base_url, status=e.response.status_code)
            return None
        except Exception as e:
            log.warning("agent_card_fetch_error", url=base_url, error=str(e))
            return None

    async def discover_agents(self, urls: list[str]) -> list[DiscoveredAgent]:
        """Fetch Agent Cards from multiple URLs concurrently.

        Args:
            urls: List of agent base URLs to discover.

        Returns:
            List of successfully discovered agents.
        """
        tasks = [self.fetch_agent_card(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        discovered = []
        for result in results:
            if isinstance(result, DiscoveredAgent):
                discovered.append(result)
            elif isinstance(result, Exception):
                log.warning("discovery_error", error=str(result))

        log.info("discovery_complete", tried=len(urls), found=len(discovered))
        return discovered

"""Port allocator for agent containers.

Assigns unique ports from a configurable range and tracks used ports
via the orchestrator database.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


class PortAllocator:
    """Allocate unique ports for agent containers."""

    def __init__(self, start: int = 9100, end: int = 9999):
        if start > end:
            raise ValueError(f"Invalid port range: {start}-{end}")
        self.start = start
        self.end = end

    def allocate(self, used_ports: set[int]) -> int | None:
        """Find the next available port.

        Args:
            used_ports: Set of currently used ports.

        Returns:
            Available port number, or None if exhausted.
        """
        for port in range(self.start, self.end + 1):
            if port not in used_ports:
                log.info("port_allocated", port=port)
                return port

        log.error("port_exhausted", range=f"{self.start}-{self.end}")
        return None

    @property
    def capacity(self) -> int:
        """Total number of ports in the range."""
        return self.end - self.start + 1

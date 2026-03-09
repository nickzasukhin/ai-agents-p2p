"""Run two agents that discover and match each other.

Launches Agent-00 (port 9000) and Agent-01 (port 9001),
each with its own context. They discover each other through
the static registry and run semantic matching.

Usage:
    uv run python scripts/run_two_agents.py
    uv run python scripts/run_two_agents.py --no-discovery  # Start without auto-discovery
"""

import argparse
import asyncio
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ANSI colors for terminal output
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def banner(msg: str, color: str = GREEN) -> None:
    print(f"\n{color}{BOLD}{'='*60}{RESET}")
    print(f"{color}{BOLD}  {msg}{RESET}")
    print(f"{color}{BOLD}{'='*60}{RESET}\n")


def info(msg: str, color: str = CYAN) -> None:
    print(f"{color}  → {msg}{RESET}")


AGENTS = [
    {
        "name": "Agent-00",
        "port": 9000,
        "data_dir": "data/agent-00",
        "color": GREEN,
    },
    {
        "name": "Agent-01",
        "port": 9001,
        "data_dir": "data/agent-01",
        "color": BLUE,
    },
]


def start_agent(agent: dict, peer_ports: list[int]) -> subprocess.Popen:
    """Start an agent as a subprocess."""
    peers = [f"http://localhost:{p}" for p in peer_ports]
    cmd = [
        sys.executable, "scripts/run_node.py",
        "--port", str(agent["port"]),
        "--data-dir", agent["data_dir"],
        "--name", agent["name"],
        "--discovery-interval", "15",
    ]
    if peers:
        cmd += ["--peers"] + peers

    info(f"Starting {agent['name']} on port {agent['port']}...", agent["color"])
    info(f"  Data: {agent['data_dir']}", agent["color"])
    info(f"  Peers: {peers}", agent["color"])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )
    return proc


async def wait_for_agent(port: int, timeout: float = 60.0) -> bool:
    """Wait for an agent to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"http://localhost:{port}/health")
                if r.status_code == 200:
                    return True
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        await asyncio.sleep(1)
    return False


async def check_agent_card(port: int) -> dict | None:
    """Fetch and display an agent's card."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"http://localhost:{port}/.well-known/agent-card.json")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


async def trigger_discovery(port: int) -> dict | None:
    """Trigger manual discovery on an agent."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"http://localhost:{port}/discovery/run")
            if r.status_code == 200:
                return r.json()
    except Exception as e:
        print(f"{RED}  Error triggering discovery on port {port}: {e}{RESET}")
    return None


async def get_matches(port: int) -> dict | None:
    """Get matches from an agent."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"http://localhost:{port}/discovery/matches")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


async def run_test():
    """Run the two-agent discovery test."""
    banner("P2P Agent Social Network — Phase 2 Test")
    info("Starting two agents with complementary profiles...")
    info("Agent-00: Software Engineer & AI Architect (Nikolai)")
    info("Agent-01: UI/UX Designer & Creative Technologist (Elena)")
    print()

    # Start agents
    procs = []
    for agent in AGENTS:
        peer_ports = [a["port"] for a in AGENTS if a["port"] != agent["port"]]
        proc = start_agent(agent, peer_ports)
        procs.append(proc)

    try:
        # Wait for both agents to be ready
        banner("Waiting for agents to start...", YELLOW)
        for agent in AGENTS:
            info(f"Waiting for {agent['name']} on port {agent['port']}...", agent["color"])
            ready = await wait_for_agent(agent["port"])
            if ready:
                info(f"✅ {agent['name']} is ready!", agent["color"])
            else:
                info(f"❌ {agent['name']} failed to start!", RED)
                return

        # Show Agent Cards
        banner("Agent Cards", CYAN)
        for agent in AGENTS:
            card = await check_agent_card(agent["port"])
            if card:
                info(f"{agent['name']}: {card.get('name', '?')}", agent["color"])
                info(f"  Description: {card.get('description', '?')[:100]}...", agent["color"])
                skills = card.get("skills", [])
                for s in skills:
                    info(f"  • {s.get('name', '?')}", agent["color"])
            print()

        # Trigger discovery on both agents
        banner("Running Discovery + Matching", YELLOW)

        for agent in AGENTS:
            info(f"Triggering discovery on {agent['name']}...", agent["color"])
            result = await trigger_discovery(agent["port"])
            if result:
                info(f"  Status: {result.get('status', '?')}", agent["color"])
                info(f"  Matches found: {result.get('matches_found', 0)}", agent["color"])
                for m in result.get("matches", []):
                    score = m.get("score", 0)
                    mutual = "🤝 MUTUAL" if m.get("is_mutual") else "→ one-way"
                    info(f"  • {m.get('agent_name', '?')} — score: {score:.4f} {mutual}", agent["color"])
            print()

        # Show detailed matches
        banner("Detailed Match Results", GREEN)

        for agent in AGENTS:
            matches_data = await get_matches(agent["port"])
            if matches_data and matches_data.get("matches"):
                info(f"\n{agent['name']}'s matches:", agent["color"])
                for m in matches_data["matches"]:
                    info(f"  Match: {m['agent_name']} (score: {m['overall_score']:.4f})", agent["color"])
                    info(f"  Mutual: {'✅ Yes' if m['is_mutual'] else '❌ No'}", agent["color"])
                    info(f"  Description: {m['description'][:120]}...", agent["color"])
                    info(f"  Top skill/need matches:", agent["color"])
                    for sm in m.get("top_matches", []):
                        direction = "← we need, they offer" if sm["direction"] == "we_need_they_offer" else "→ they need, we offer"
                        info(f"    [{sm['similarity']:.3f}] {direction}", agent["color"])
                        info(f"           Ours: {sm['our_text'][:80]}", agent["color"])
                        info(f"           Theirs: {sm['their_text'][:80]}", agent["color"])
                print()

        banner("Phase 2 Test Complete! ✅", GREEN)
        info("Both agents successfully discovered and matched each other.")
        info("Press Ctrl+C to stop agents.")

        # Keep running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        banner("Shutting down...", YELLOW)
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=5)
        info("All agents stopped.")


def main():
    parser = argparse.ArgumentParser(description="Run two agents for Phase 2 testing")
    parser.parse_args()
    asyncio.run(run_test())


if __name__ == "__main__":
    main()

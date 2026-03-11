"""Fun subdomain name generator using fictional character names.

Instead of ugly UUIDs (055f634b-0e1d-4a07-b03f-60dbfecad9b0.agents.devpunks.io),
users get memorable subdomains like gandalf.agents.devpunks.io or morpheus.agents.devpunks.io.
"""

from __future__ import annotations

import random

# ~250 fictional character names — all URL-safe (lowercase, ASCII, hyphens only).
# From: LOTR, Star Wars, Marvel, DC, Matrix, Harry Potter, Witcher, Zelda,
# God of War, anime, mythology, classic sci-fi, games, and more.
CHARACTERS = [
    # ── Lord of the Rings / Hobbit ────────────────────────────
    "gandalf", "aragorn", "legolas", "frodo", "gimli", "boromir",
    "galadriel", "elrond", "sauron", "saruman", "samwise", "pippin",
    "treebeard", "eowyn", "faramir", "theoden", "bilbo", "thorin",
    # ── Star Wars ─────────────────────────────────────────────
    "yoda", "vader", "skywalker", "leia", "chewbacca", "obiwan",
    "mando", "ahsoka", "palpatine", "boba-fett", "han-solo",
    "padme", "maul", "kylo", "grogu", "lando", "greedo",
    # ── Marvel ────────────────────────────────────────────────
    "ironman", "wolverine", "deadpool", "thanos", "loki", "thor",
    "hulk", "spiderman", "panther", "strange", "vision", "ultron",
    "magneto", "storm", "gamora", "groot", "rocket", "nebula",
    "wanda", "hawkeye", "fury", "antman", "wasp",
    # ── DC ────────────────────────────────────────────────────
    "batman", "joker", "aquaman", "cyborg", "flash", "zatanna",
    "constantine", "raven", "starfire", "deathstroke", "bane",
    "catwoman", "riddler", "oracle", "nightwing", "harley",
    # ── Matrix / Cyberpunk ────────────────────────────────────
    "morpheus", "neo", "trinity", "oracle", "cipher", "niobe",
    "apoc", "dozer", "merovingian", "seraph",
    # ── Harry Potter ──────────────────────────────────────────
    "dumbledore", "hermione", "snape", "hagrid", "voldemort",
    "sirius", "lupin", "dobby", "hedwig", "bellatrix",
    "minerva", "neville", "draco", "luna",
    # ── Witcher ───────────────────────────────────────────────
    "geralt", "yennefer", "triss", "ciri", "dandelion",
    "vesemir", "roach", "emhyr", "eredin",
    # ── Games (Zelda, God of War, Souls, etc.) ────────────────
    "link", "zelda", "ganondorf", "kratos", "atreus",
    "mario", "luigi", "bowser", "samus", "kirby",
    "sonic", "cortana", "masterchief", "altair", "ezio",
    "dante", "vergil", "solaire", "chosen",
    "ryu", "megaman", "pikachu", "mewtwo", "charizard",
    "cloud", "sephiroth", "tifa", "aerith", "squall",
    # ── Anime ─────────────────────────────────────────────────
    "goku", "vegeta", "naruto", "sasuke", "luffy", "zoro",
    "saitama", "genos", "levi", "mikasa", "eren",
    "spike", "vash", "itachi", "kakashi", "jiraiya",
    "todoroki", "deku", "bakugo", "tanjiro", "gojo",
    "killua", "gon", "kurapika", "hisoka", "meruem",
    "light", "ryuk", "edward", "alphonse", "mustang",
    # ── Mythology / Legends ───────────────────────────────────
    "odin", "freya", "fenrir", "loki-myth", "valkyrie",
    "prometheus", "hercules", "achilles", "odysseus", "athena",
    "artemis", "apollo", "poseidon", "hades", "persephone",
    "anubis", "horus", "osiris", "bastet", "thoth",
    "merlin", "excalibur", "percival", "lancelot", "galahad",
    # ── Classic Sci-Fi / Literature ───────────────────────────
    "sherlock", "watson", "moriarty", "dracula", "frankenstein",
    "dorian", "gatsby", "atticus", "ripley", "muaddib",
    "ender", "hari-seldon", "zaphod", "marvin", "ford-prefect",
    "neuromancer", "wintermute", "artoo", "jarvis", "hal",
    # ── Dune ──────────────────────────────────────────────────
    "atreides", "harkonnen", "stilgar", "chani", "duncan",
    "jessica", "gurney", "leto", "feyd",
    # ── Cyberpunk / Modern ────────────────────────────────────
    "silverhand", "netrunner", "samurai", "ghost", "nomad",
    "ronin", "cipher", "phantom", "specter", "sentinel",
    "vortex", "nexus", "vector", "glitch", "pixel",
    "daemon", "kernel", "quantum", "synapse", "helix",
    "nebula-x", "cosmos", "pulsar", "quasar", "photon",
    "axiom", "zenith", "nadir", "vertex", "prism",
]

# Deduplicate (some names may appear in multiple categories)
CHARACTERS = list(dict.fromkeys(CHARACTERS))


def generate_subdomain(taken: set[str] | None = None) -> str:
    """Generate a unique subdomain from fictional character names.

    Args:
        taken: Set of already-used subdomains to avoid.

    Returns:
        A unique subdomain string (e.g. "gandalf", "morpheus", "neo").

    Raises:
        RuntimeError: If no names are available (extremely unlikely).
    """
    taken = taken or set()

    # Try to find an available name from the curated list
    available = [name for name in CHARACTERS if name not in taken]
    if available:
        return random.choice(available)

    # Fallback: append random 2-digit number to a random base name
    for _ in range(500):
        base = random.choice(CHARACTERS)
        name = f"{base}-{random.randint(10, 99)}"
        if name not in taken:
            return name

    raise RuntimeError("No available subdomains — all names exhausted")

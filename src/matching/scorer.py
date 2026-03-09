"""Multi-factor scoring for agent matching.

Combines embedding similarity with availability, collaboration history,
tag overlap, and profile freshness into a single weighted score.
"""

from __future__ import annotations

import math
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = structlog.get_logger()

DEFAULT_WEIGHTS = {
    "embedding": 0.40,
    "availability": 0.15,
    "history": 0.15,
    "tags": 0.15,
    "freshness": 0.15,
}

FRESHNESS_HALFLIFE_HOURS = 24.0
MAX_ACTIVE_NEGOTIATIONS = 5


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of how a match score was computed."""
    embedding: float = 0.0
    availability: float = 0.0
    history: float = 0.0
    tags: float = 0.0
    freshness: float = 0.0
    weighted_total: float = 0.0
    weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "embedding": round(self.embedding, 4),
            "availability": round(self.availability, 4),
            "history": round(self.history, 4),
            "tags": round(self.tags, 4),
            "freshness": round(self.freshness, 4),
            "weighted_total": round(self.weighted_total, 4),
            "weights": {k: round(v, 2) for k, v in self.weights.items()},
        }


@dataclass
class MatchContext:
    """Contextual information about a candidate agent, used by the scorer."""
    agent_url: str
    status: str = "unknown"
    active_negotiations: int = 0
    successful_negotiations: int = 0
    failed_negotiations: int = 0
    their_tags: list[str] = field(default_factory=list)
    last_seen: str | None = None


class MultiFactorScorer:
    """Scores agent matches using multiple weighted factors.

    Factors:
        embedding    — cosine similarity between skills/needs (from MatchingEngine)
        availability — online status and negotiation load
        history      — past collaboration success ratio with this peer
        tags         — keyword overlap between skill tags
        freshness    — recency of the peer's last_seen timestamp
    """

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)
        total = sum(self.weights.values())
        if total > 0 and abs(total - 1.0) > 0.01:
            for k in self.weights:
                self.weights[k] /= total

    def score(
        self,
        embedding_score: float,
        context: MatchContext,
        our_tags: list[str],
    ) -> ScoreBreakdown:
        """Compute a multi-factor score for a single candidate.

        Args:
            embedding_score: Raw cosine-similarity score from MatchingEngine.
            context: Contextual data about the candidate (status, history, etc.).
            our_tags: Our agent's skill tags for overlap calculation.

        Returns:
            ScoreBreakdown with per-factor values and the weighted total.
        """
        bd = ScoreBreakdown(weights=dict(self.weights))

        bd.embedding = max(0.0, min(1.0, embedding_score))
        bd.availability = self._availability(context)
        bd.history = self._history(context)
        bd.tags = self._tag_overlap(our_tags, context.their_tags)
        bd.freshness = self._freshness(context.last_seen)

        bd.weighted_total = (
            self.weights["embedding"] * bd.embedding
            + self.weights["availability"] * bd.availability
            + self.weights["history"] * bd.history
            + self.weights["tags"] * bd.tags
            + self.weights["freshness"] * bd.freshness
        )
        bd.weighted_total = max(0.0, min(1.0, bd.weighted_total))

        return bd

    # ── Individual factor computations ────────────────────────────

    @staticmethod
    def _availability(ctx: MatchContext) -> float:
        """Score based on online status and negotiation load.

        Returns 1.0 for online+idle, 0.0 for offline.
        Active negotiations reduce the score linearly.
        """
        if ctx.status == "offline":
            return 0.0

        base = 1.0 if ctx.status == "online" else 0.5

        if ctx.active_negotiations >= MAX_ACTIVE_NEGOTIATIONS:
            load_penalty = 1.0
        else:
            load_penalty = ctx.active_negotiations / MAX_ACTIVE_NEGOTIATIONS

        return max(0.0, base * (1.0 - load_penalty * 0.6))

    @staticmethod
    def _history(ctx: MatchContext) -> float:
        """Score based on past negotiation success/failure ratio.

        No history → neutral 0.5. Good track record → up to 1.0.
        Bad track record → down to 0.0.
        """
        total = ctx.successful_negotiations + ctx.failed_negotiations
        if total == 0:
            return 0.5

        success_rate = ctx.successful_negotiations / total
        confidence = min(1.0, total / 5.0)
        return 0.5 + (success_rate - 0.5) * confidence

    @staticmethod
    def _tag_overlap(our_tags: list[str], their_tags: list[str]) -> float:
        """Jaccard-like overlap between tag sets (case-insensitive)."""
        if not our_tags or not their_tags:
            return 0.0

        ours = {t.lower().strip() for t in our_tags if t.strip()}
        theirs = {t.lower().strip() for t in their_tags if t.strip()}

        if not ours or not theirs:
            return 0.0

        intersection = len(ours & theirs)
        union = len(ours | theirs)
        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _freshness(last_seen: str | None) -> float:
        """Exponential decay based on how recently the agent was seen.

        Returns 1.0 for just-seen agents, decaying with a 24-hour half-life.
        Unknown last_seen → 0.3 (conservative default).
        """
        if not last_seen:
            return 0.3

        try:
            seen_dt = datetime.fromisoformat(last_seen)
            if seen_dt.tzinfo is None:
                seen_dt = seen_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_ago = max(0.0, (now - seen_dt).total_seconds() / 3600.0)
            return math.exp(-0.693 * hours_ago / FRESHNESS_HALFLIFE_HOURS)
        except (ValueError, TypeError):
            return 0.3

    # ── Auto-threshold ────────────────────────────────────────────

    @staticmethod
    def auto_threshold(scores: list[float], min_threshold: float = 0.25) -> float:
        """Compute an adaptive threshold from a set of scores.

        Uses mean - 0.5*stddev, clamped to [min_threshold, 0.8].
        This keeps the top matches while filtering noise.
        """
        if not scores:
            return min_threshold

        n = len(scores)
        mean = sum(scores) / n

        if n < 2:
            return max(min_threshold, mean * 0.7)

        variance = sum((s - mean) ** 2 for s in scores) / n
        stddev = math.sqrt(variance)
        threshold = mean - 0.5 * stddev

        return max(min_threshold, min(0.8, threshold))

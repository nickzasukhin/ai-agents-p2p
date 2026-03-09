"""Tests for MultiFactorScorer — weighted multi-factor agent matching."""

import pytest
from datetime import datetime, timezone, timedelta

from src.matching.scorer import (
    MultiFactorScorer,
    ScoreBreakdown,
    MatchContext,
    DEFAULT_WEIGHTS,
    MAX_ACTIVE_NEGOTIATIONS,
)


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def scorer():
    return MultiFactorScorer()


@pytest.fixture
def online_context():
    now = datetime.now(timezone.utc).isoformat()
    return MatchContext(
        agent_url="http://test:9000",
        status="online",
        active_negotiations=0,
        successful_negotiations=0,
        failed_negotiations=0,
        their_tags=["python", "fastapi", "ml"],
        last_seen=now,
    )


# ── Weight Normalization ─────────────────────────────────────

class TestWeights:
    def test_default_weights_sum_to_one(self):
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01

    def test_custom_weights_normalized(self):
        scorer = MultiFactorScorer(weights={"embedding": 2, "availability": 1, "history": 1, "tags": 1, "freshness": 1})
        total = sum(scorer.weights.values())
        assert abs(total - 1.0) < 0.01

    def test_partial_weight_override(self):
        scorer = MultiFactorScorer(weights={"embedding": 0.6})
        assert scorer.weights["embedding"] >= 0.5


# ── Embedding Factor ─────────────────────────────────────────

class TestEmbeddingFactor:
    def test_embedding_passed_through(self, scorer, online_context):
        bd = scorer.score(0.75, online_context, ["python"])
        assert bd.embedding == 0.75

    def test_embedding_clamped_to_range(self, scorer, online_context):
        bd_high = scorer.score(1.5, online_context, [])
        assert bd_high.embedding == 1.0
        bd_low = scorer.score(-0.3, online_context, [])
        assert bd_low.embedding == 0.0


# ── Availability Factor ──────────────────────────────────────

class TestAvailability:
    def test_online_idle_gives_max(self, scorer):
        ctx = MatchContext(agent_url="x", status="online", active_negotiations=0)
        bd = scorer.score(0.5, ctx, [])
        assert bd.availability == 1.0

    def test_offline_gives_zero(self, scorer):
        ctx = MatchContext(agent_url="x", status="offline")
        bd = scorer.score(0.5, ctx, [])
        assert bd.availability == 0.0

    def test_unknown_status_gives_half(self, scorer):
        ctx = MatchContext(agent_url="x", status="unknown")
        bd = scorer.score(0.5, ctx, [])
        assert 0.4 <= bd.availability <= 0.6

    def test_load_reduces_availability(self, scorer):
        idle = MatchContext(agent_url="x", status="online", active_negotiations=0)
        busy = MatchContext(agent_url="x", status="online", active_negotiations=4)
        bd_idle = scorer.score(0.5, idle, [])
        bd_busy = scorer.score(0.5, busy, [])
        assert bd_idle.availability > bd_busy.availability

    def test_max_load_still_positive_if_online(self, scorer):
        ctx = MatchContext(agent_url="x", status="online", active_negotiations=MAX_ACTIVE_NEGOTIATIONS)
        bd = scorer.score(0.5, ctx, [])
        assert bd.availability > 0.0


# ── History Factor ────────────────────────────────────────────

class TestHistory:
    def test_no_history_gives_neutral(self, scorer):
        ctx = MatchContext(agent_url="x")
        bd = scorer.score(0.5, ctx, [])
        assert bd.history == 0.5

    def test_all_success_gives_high(self, scorer):
        ctx = MatchContext(agent_url="x", successful_negotiations=5, failed_negotiations=0)
        bd = scorer.score(0.5, ctx, [])
        assert bd.history > 0.8

    def test_all_failure_gives_low(self, scorer):
        ctx = MatchContext(agent_url="x", successful_negotiations=0, failed_negotiations=5)
        bd = scorer.score(0.5, ctx, [])
        assert bd.history < 0.2

    def test_mixed_history(self, scorer):
        ctx = MatchContext(agent_url="x", successful_negotiations=3, failed_negotiations=2)
        bd = scorer.score(0.5, ctx, [])
        assert 0.4 <= bd.history <= 0.7


# ── Tag Overlap Factor ───────────────────────────────────────

class TestTagOverlap:
    def test_full_overlap(self, scorer):
        ctx = MatchContext(agent_url="x", their_tags=["python", "ml"])
        bd = scorer.score(0.5, ctx, ["python", "ml"])
        assert bd.tags == 1.0

    def test_no_overlap(self, scorer):
        ctx = MatchContext(agent_url="x", their_tags=["java", "spring"])
        bd = scorer.score(0.5, ctx, ["python", "ml"])
        assert bd.tags == 0.0

    def test_partial_overlap(self, scorer):
        ctx = MatchContext(agent_url="x", their_tags=["python", "java"])
        bd = scorer.score(0.5, ctx, ["python", "ml"])
        assert 0.2 <= bd.tags <= 0.5

    def test_case_insensitive(self, scorer):
        ctx = MatchContext(agent_url="x", their_tags=["Python", "ML"])
        bd = scorer.score(0.5, ctx, ["python", "ml"])
        assert bd.tags == 1.0

    def test_empty_tags_give_zero(self, scorer):
        ctx = MatchContext(agent_url="x", their_tags=[])
        bd = scorer.score(0.5, ctx, [])
        assert bd.tags == 0.0


# ── Freshness Factor ─────────────────────────────────────────

class TestFreshness:
    def test_just_seen_gives_near_one(self, scorer):
        now = datetime.now(timezone.utc).isoformat()
        ctx = MatchContext(agent_url="x", last_seen=now)
        bd = scorer.score(0.5, ctx, [])
        assert bd.freshness > 0.95

    def test_old_timestamp_decays(self, scorer):
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        ctx = MatchContext(agent_url="x", last_seen=old)
        bd = scorer.score(0.5, ctx, [])
        assert bd.freshness < 0.2

    def test_no_timestamp_gives_default(self, scorer):
        ctx = MatchContext(agent_url="x", last_seen=None)
        bd = scorer.score(0.5, ctx, [])
        assert bd.freshness == 0.3

    def test_invalid_timestamp_gives_default(self, scorer):
        ctx = MatchContext(agent_url="x", last_seen="not-a-date")
        bd = scorer.score(0.5, ctx, [])
        assert bd.freshness == 0.3


# ── Weighted Total ────────────────────────────────────────────

class TestWeightedTotal:
    def test_total_in_range(self, scorer, online_context):
        bd = scorer.score(0.8, online_context, ["python"])
        assert 0.0 <= bd.weighted_total <= 1.0

    def test_all_perfect_gives_high_total(self, scorer):
        now = datetime.now(timezone.utc).isoformat()
        ctx = MatchContext(
            agent_url="x",
            status="online",
            active_negotiations=0,
            successful_negotiations=10,
            failed_negotiations=0,
            their_tags=["python", "ml"],
            last_seen=now,
        )
        bd = scorer.score(1.0, ctx, ["python", "ml"])
        assert bd.weighted_total > 0.85

    def test_all_bad_gives_low_total(self, scorer):
        old = (datetime.now(timezone.utc) - timedelta(hours=168)).isoformat()
        ctx = MatchContext(
            agent_url="x",
            status="offline",
            active_negotiations=10,
            successful_negotiations=0,
            failed_negotiations=10,
            their_tags=["java"],
            last_seen=old,
        )
        bd = scorer.score(0.0, ctx, ["python"])
        assert bd.weighted_total < 0.15


# ── ScoreBreakdown Serialization ──────────────────────────────

class TestBreakdownSerialization:
    def test_to_dict_has_all_fields(self, scorer, online_context):
        bd = scorer.score(0.7, online_context, ["python"])
        d = bd.to_dict()
        for key in ("embedding", "availability", "history", "tags", "freshness", "weighted_total", "weights"):
            assert key in d

    def test_to_dict_values_are_rounded(self, scorer, online_context):
        bd = scorer.score(0.7, online_context, ["python"])
        d = bd.to_dict()
        assert isinstance(d["embedding"], float)
        assert len(str(d["embedding"]).split(".")[-1]) <= 4


# ── Auto-Threshold ────────────────────────────────────────────

class TestAutoThreshold:
    def test_empty_scores_returns_min(self):
        assert MultiFactorScorer.auto_threshold([]) == 0.25

    def test_single_score(self):
        t = MultiFactorScorer.auto_threshold([0.6])
        assert 0.25 <= t <= 0.8

    def test_tight_cluster(self):
        scores = [0.7, 0.72, 0.68, 0.71, 0.69]
        t = MultiFactorScorer.auto_threshold(scores)
        assert t > 0.5

    def test_spread_scores_lower_threshold(self):
        scores = [0.3, 0.5, 0.7, 0.9]
        t = MultiFactorScorer.auto_threshold(scores)
        assert t < 0.6

    def test_threshold_respects_min(self):
        scores = [0.05, 0.1, 0.08]
        t = MultiFactorScorer.auto_threshold(scores, min_threshold=0.2)
        assert t >= 0.2

    def test_threshold_capped_at_max(self):
        scores = [0.95, 0.96, 0.97, 0.98]
        t = MultiFactorScorer.auto_threshold(scores)
        assert t <= 0.8

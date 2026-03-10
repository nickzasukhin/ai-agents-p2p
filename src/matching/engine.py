"""Matching Engine — finds complementary agents based on skills/needs similarity."""

from __future__ import annotations

import structlog
import numpy as np
from dataclasses import dataclass, field

from src.matching.embeddings import EmbeddingEngine
from src.matching.scorer import MultiFactorScorer, ScoreBreakdown, MatchContext
from src.a2a_client.client import DiscoveredAgent

log = structlog.get_logger()

# Minimum similarity score to consider a match
DEFAULT_MATCH_THRESHOLD = 0.35


@dataclass
class SkillNeedMatch:
    """A specific match between our need and their skill (or vice versa)."""
    our_text: str
    their_text: str
    similarity: float
    direction: str  # "we_need_they_offer" or "they_need_we_offer"


@dataclass
class AgentMatch:
    """A match result between our agent and a discovered agent."""
    agent_url: str
    agent_name: str
    overall_score: float
    skill_matches: list[SkillNeedMatch] = field(default_factory=list)
    their_skills_text: str = ""
    their_description: str = ""
    score_breakdown: ScoreBreakdown | None = None

    @property
    def is_mutual(self) -> bool:
        """True if both agents can offer something to each other."""
        directions = {m.direction for m in self.skill_matches}
        return "we_need_they_offer" in directions and "they_need_we_offer" in directions


class MatchingEngine:
    """Finds complementary agents by comparing skills vs needs.

    The engine works bidirectionally:
    1. Our NEEDS vs Their SKILLS → what they can do for us
    2. Their NEEDS vs Our SKILLS → what we can do for them

    A good match is one where both sides have something to offer.
    """

    def __init__(
        self,
        embedding_engine: EmbeddingEngine | None = None,
        threshold: float = DEFAULT_MATCH_THRESHOLD,
        scorer: MultiFactorScorer | None = None,
    ):
        self.embeddings = embedding_engine or EmbeddingEngine()
        self.threshold = threshold
        self.scorer = scorer or MultiFactorScorer()

    def _parse_skills_and_needs(self, raw_text: str) -> tuple[list[str], list[str]]:
        """Extract skills and needs from raw context text.

        Looks for sections marked with '--- skills ---' and '--- needs ---'.
        Falls back to treating everything as skills if no sections found.
        """
        skills_lines = []
        needs_lines = []
        current_section = None

        for line in raw_text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                # Detect section headers
                lower = stripped.lower()
                if "skills" in lower or "expertise" in lower:
                    current_section = "skills"
                elif "need" in lower or "looking for" in lower:
                    current_section = "needs"
                continue

            if stripped.startswith("- ") or stripped.startswith("* "):
                clean = stripped.lstrip("-* ").strip()
                if clean:
                    if current_section == "needs":
                        needs_lines.append(clean)
                    else:
                        skills_lines.append(clean)

        return skills_lines, needs_lines

    def _parse_card_skills(self, agent: DiscoveredAgent) -> list[str]:
        """Extract skill descriptions from an Agent Card."""
        skills = []
        if agent.card.skills:
            for skill in agent.card.skills:
                parts = []
                if skill.name:
                    parts.append(skill.name)
                if skill.description:
                    parts.append(skill.description)
                if parts:
                    skills.append(" — ".join(parts))
        return skills

    def find_matches(
        self,
        our_context_raw: str,
        discovered_agents: list[DiscoveredAgent],
        match_contexts: dict[str, MatchContext] | None = None,
        our_tags: list[str] | None = None,
    ) -> list[AgentMatch]:
        """Find matching agents from a list of discovered agents.

        Args:
            our_context_raw: Our agent's raw context text (from MCP reader).
            discovered_agents: List of agents discovered via A2A.
            match_contexts: Per-agent contextual data for multi-factor scoring
                (status, negotiations, history, tags, last_seen).
            our_tags: Our agent's skill tags for overlap calculation.

        Returns:
            Sorted list of AgentMatch results (best matches first).
        """
        if not discovered_agents:
            return []

        match_contexts = match_contexts or {}
        our_tags = our_tags or []

        # Parse our skills and needs
        our_skills, our_needs = self._parse_skills_and_needs(our_context_raw)

        if not our_skills and not our_needs:
            log.warning("no_skills_or_needs_found")
            return []

        log.info("matching_start", our_skills=len(our_skills), our_needs=len(our_needs),
                 candidates=len(discovered_agents))

        # Embed our skills and needs
        our_skill_embeddings = self.embeddings.embed_batch(our_skills) if our_skills else None
        our_need_embeddings = self.embeddings.embed_batch(our_needs) if our_needs else None

        matches = []

        for agent in discovered_agents:
            their_skills = self._parse_card_skills(agent)
            if not their_skills:
                log.debug("agent_no_skills", url=agent.url)
                continue

            # Embed their skills
            their_skill_embeddings = self.embeddings.embed_batch(their_skills)

            skill_matches = []

            # Direction 1: Our NEEDS vs Their SKILLS
            if our_need_embeddings is not None and len(our_need_embeddings) > 0:
                sim_matrix = EmbeddingEngine.cosine_similarity_matrix(
                    our_need_embeddings, their_skill_embeddings
                )
                for i, our_need in enumerate(our_needs):
                    for j, their_skill in enumerate(their_skills):
                        score = float(sim_matrix[i, j])
                        if score >= self.threshold:
                            skill_matches.append(SkillNeedMatch(
                                our_text=our_need,
                                their_text=their_skill,
                                similarity=score,
                                direction="we_need_they_offer",
                            ))

            # Direction 2: Their card description as "needs" vs Our SKILLS
            if our_skill_embeddings is not None and len(our_skill_embeddings) > 0:
                their_desc = agent.card.description or ""
                if their_desc:
                    their_desc_embedding = self.embeddings.embed(their_desc)
                    for i, our_skill in enumerate(our_skills):
                        score = EmbeddingEngine.cosine_similarity(
                            our_skill_embeddings[i], their_desc_embedding
                        )
                        if score >= self.threshold:
                            skill_matches.append(SkillNeedMatch(
                                our_text=our_skill,
                                their_text=f"[need inferred from profile] {their_desc[:100]}",
                                similarity=score,
                                direction="they_need_we_offer",
                            ))

            if not skill_matches:
                continue

            # Overall score: average of top matches from each direction
            we_need_scores = [m.similarity for m in skill_matches if m.direction == "we_need_they_offer"]
            they_need_scores = [m.similarity for m in skill_matches if m.direction == "they_need_we_offer"]

            avg_we_need = np.mean(we_need_scores) if we_need_scores else 0.0
            avg_they_need = np.mean(they_need_scores) if they_need_scores else 0.0

            if we_need_scores and they_need_scores:
                embedding_score = (avg_we_need + avg_they_need) / 2 * 1.2
            else:
                embedding_score = max(avg_we_need, avg_they_need)

            embedding_score = min(float(embedding_score), 1.0)

            # Multi-factor scoring (Phase 6.7)
            ctx = match_contexts.get(agent.url)
            if ctx is None:
                ctx = MatchContext(agent_url=agent.url)

            breakdown = self.scorer.score(embedding_score, ctx, our_tags)
            overall_score = breakdown.weighted_total

            # Sort skill matches by similarity (best first)
            skill_matches.sort(key=lambda m: m.similarity, reverse=True)

            matches.append(AgentMatch(
                agent_url=agent.url,
                agent_name=agent.card.name,
                overall_score=overall_score,
                skill_matches=skill_matches[:10],
                their_skills_text=agent.skills_text,
                their_description=agent.card.description or "",
                score_breakdown=breakdown,
            ))

        # Auto-threshold: filter weak matches
        if matches:
            all_scores = [m.overall_score for m in matches]
            threshold = MultiFactorScorer.auto_threshold(all_scores)
            before = len(matches)
            matches = [m for m in matches if m.overall_score >= threshold]
            if len(matches) < before:
                log.info("auto_threshold_filtered",
                         threshold=round(threshold, 4),
                         before=before,
                         after=len(matches))

        # Sort by overall score (best first)
        matches.sort(key=lambda m: m.overall_score, reverse=True)

        log.info(
            "matching_complete",
            candidates=len(discovered_agents),
            matches=len(matches),
            top_score=matches[0].overall_score if matches else 0,
        )

        return matches

    def search_agents(
        self,
        query_text: str,
        agents: list[DiscoveredAgent],
        limit: int = 20,
    ) -> list[dict]:
        """Search agents by natural language query using embedding similarity.

        Compares the query against each agent's skills and description.

        Args:
            query_text: Natural language search query.
            agents: List of discovered agents to search through.
            limit: Maximum number of results to return.

        Returns:
            List of dicts sorted by match_score (best first):
            [{agent_url, agent_name, description, skills, match_score, source}]
        """
        if not query_text or not agents:
            return []

        query_embedding = self.embeddings.embed(query_text)

        results = []
        for agent in agents:
            # Build a text representation of the agent
            skill_texts = self._parse_card_skills(agent)
            desc = agent.card.description or ""

            # Combine description + skills for matching
            combined_texts = []
            if desc:
                combined_texts.append(desc)
            combined_texts.extend(skill_texts)

            if not combined_texts:
                continue

            # Compute similarity against each text
            text_embeddings = self.embeddings.embed_batch(combined_texts)
            similarities = [
                float(EmbeddingEngine.cosine_similarity(query_embedding, emb))
                for emb in text_embeddings
            ]

            # Use max similarity as the match score
            match_score = max(similarities) if similarities else 0.0

            if match_score >= 0.2:  # Low threshold for search
                results.append({
                    "agent_url": agent.url,
                    "agent_name": agent.card.name,
                    "description": desc,
                    "skills": [
                        {"name": s.name, "description": s.description, "tags": s.tags}
                        for s in (agent.card.skills or [])
                    ],
                    "match_score": round(match_score, 4),
                    "source": "local",
                })

        # Sort by score descending
        results.sort(key=lambda r: r["match_score"], reverse=True)

        log.info("search_complete", query=query_text[:50], candidates=len(agents), results=len(results))
        return results[:limit]

"""Negotiation Engine — LLM-powered proposal generation and evaluation."""

from __future__ import annotations

import json
import structlog

from src.negotiation.states import (
    Negotiation, NegotiationState, NegotiationMessage,
)
from src.privacy.guard import PrivacyGuard
from src.llm.provider import LLMProvider, ChatMessage

log = structlog.get_logger()

PROPOSAL_SYSTEM_PROMPT = """You are an AI agent negotiating a collaboration on behalf of your owner.

YOUR OWNER'S PROFILE:
{our_context}

MATCH INFORMATION:
- Partner: {their_name}
- Partner description: {their_description}
- Match score: {match_score}
- Match reasons: {match_reasons}

NEGOTIATION RULES:
1. Be professional, concise, and constructive
2. Focus on MUTUAL BENEFIT — what both sides gain
3. Propose SPECIFIC collaboration formats (consulting, project, partnership)
4. NEVER reveal internal file names, raw data, or sensitive details
5. Keep proposals under 150 words
6. If this is a counter-proposal, address the other agent's concerns

Previous messages in this negotiation:
{history}

Generate a {message_type} for this collaboration. Be specific about:
- What you can offer them
- What you'd like from them
- Proposed format (async consulting, joint project, etc.)
- Suggested next steps"""

EVALUATION_SYSTEM_PROMPT = """You are evaluating a collaboration proposal between two AI agents.

YOUR OWNER'S PROFILE:
{our_context}

NEGOTIATION HISTORY:
{history}

LATEST PROPOSAL FROM PARTNER:
{latest_proposal}

Evaluate this proposal and decide:
1. ACCEPT — if the proposal is reasonable and beneficial for your owner
2. COUNTER — if you want to suggest modifications (explain what to change)
3. REJECT — if the proposal is not beneficial or feasible

Return JSON:
{{
  "decision": "accept" | "counter" | "reject",
  "reasoning": "Brief explanation of your decision",
  "counter_proposal": "If decision is counter, your modified proposal. Otherwise empty.",
  "collaboration_summary": "If accepting, a one-sentence summary of the agreed collaboration."
}}"""


class NegotiationEngine:
    """Handles LLM-powered negotiation between agents.

    Generates proposals, evaluates incoming proposals, and manages
    the negotiation state machine transitions.
    """

    def __init__(
        self,
        our_context_raw: str,
        our_name: str,
        our_url: str,
        llm: LLMProvider | None = None,
        privacy_guard: PrivacyGuard | None = None,
        # Legacy params (ignored if llm is provided)
        openai_api_key: str = "",
        model: str = "gpt-4o-mini",
    ):
        # Backward compat: create provider from raw key if no LLMProvider given
        if llm is None and openai_api_key:
            from src.llm.factory import LLMFactory
            llm = LLMFactory.create("openai", api_key=openai_api_key, model=model)

        self.llm = llm
        self.our_context = our_context_raw
        self.our_name = our_name
        self.our_url = our_url
        self.privacy = privacy_guard or PrivacyGuard()

    def _format_history(self, negotiation: Negotiation) -> str:
        if not negotiation.messages:
            return "(No messages yet — this is the opening proposal)"
        lines = []
        for m in negotiation.messages:
            sender = "You" if m.sender == self.our_url else negotiation.their_name
            lines.append(f"[Round {m.round}] {sender}: {m.content}")
        return "\n".join(lines)

    def generate_proposal(self, negotiation: Negotiation) -> str:
        """Generate an initial proposal or counter-proposal using LLM."""
        if not self.llm:
            return self._fallback_proposal(negotiation)

        is_counter = negotiation.state == NegotiationState.COUNTER
        message_type = "counter-proposal" if is_counter else "initial proposal"

        prompt = PROPOSAL_SYSTEM_PROMPT.format(
            our_context=self.privacy.sanitize_context(self.our_context),
            their_name=negotiation.their_name,
            their_description=negotiation.collaboration_summary or "AI agent",
            match_score=negotiation.match_score,
            match_reasons=", ".join(negotiation.match_reasons[:5]),
            history=self._format_history(negotiation),
            message_type=message_type,
        )

        try:
            proposal = self.llm.chat(
                messages=[
                    ChatMessage(role="system", content=prompt),
                    ChatMessage(role="user", content=f"Generate the {message_type}."),
                ],
                temperature=0.7,
                max_tokens=300,
            )
            proposal = self.privacy.filter_output(proposal)
            log.info("proposal_generated", type=message_type, chars=len(proposal))
            return proposal
        except Exception as e:
            log.error("proposal_generation_error", error=str(e))
            return self._fallback_proposal(negotiation)

    def evaluate_proposal(self, negotiation: Negotiation) -> dict:
        """Evaluate the latest incoming proposal using LLM.

        Returns:
            dict with keys: decision, reasoning, counter_proposal, collaboration_summary
        """
        if not self.llm:
            return self._fallback_evaluation(negotiation)

        latest = negotiation.messages[-1] if negotiation.messages else None
        latest_text = latest.content if latest else ""

        prompt = EVALUATION_SYSTEM_PROMPT.format(
            our_context=self.privacy.sanitize_context(self.our_context),
            history=self._format_history(negotiation),
            latest_proposal=latest_text,
        )

        try:
            raw = self.llm.chat(
                messages=[
                    ChatMessage(role="system", content=prompt),
                    ChatMessage(role="user", content="Evaluate the proposal and return JSON."),
                ],
                temperature=0.3,
                max_tokens=400,
                json_mode=True,
            )
            result = json.loads(raw)
            log.info("proposal_evaluated", decision=result.get("decision"))
            return {
                "decision": result.get("decision", "reject"),
                "reasoning": result.get("reasoning", ""),
                "counter_proposal": self.privacy.filter_output(
                    result.get("counter_proposal", "")
                ),
                "collaboration_summary": result.get("collaboration_summary", ""),
            }
        except Exception as e:
            log.error("evaluation_error", error=str(e))
            return self._fallback_evaluation(negotiation)

    def process_incoming(self, negotiation: Negotiation, message: str, sender_url: str) -> dict:
        """Process an incoming negotiation message and decide response.

        Returns action dict: {action, response_text, new_state}
        """
        # Add their message
        negotiation.add_message(
            sender=sender_url,
            content=message,
            message_type="proposal" if negotiation.current_round <= 1 else "counter",
        )

        # Check round limit
        if negotiation.current_round >= negotiation.max_rounds:
            negotiation.transition(NegotiationState.TIMEOUT)
            return {
                "action": "timeout",
                "response_text": "Negotiation timed out — maximum rounds reached.",
                "new_state": NegotiationState.TIMEOUT.value,
            }

        # Evaluate their proposal
        negotiation.transition(NegotiationState.EVALUATING)
        evaluation = self.evaluate_proposal(negotiation)
        decision = evaluation["decision"]

        if decision == "accept":
            negotiation.collaboration_summary = evaluation.get("collaboration_summary", "")
            negotiation.transition(NegotiationState.ACCEPTED)
            negotiation.transition(NegotiationState.OWNER_REVIEW)

            response_text = (
                f"I'm happy to accept this collaboration! "
                f"Summary: {negotiation.collaboration_summary}. "
                f"I'll confirm with my owner and get back to you."
            )
            negotiation.add_message(
                sender=self.our_url, content=response_text, message_type="accept",
            )

            return {
                "action": "accepted",
                "response_text": response_text,
                "new_state": NegotiationState.OWNER_REVIEW.value,
                "summary": negotiation.collaboration_summary,
                "reasoning": evaluation.get("reasoning", ""),
            }

        elif decision == "counter":
            counter_text = evaluation.get("counter_proposal", "")
            if not counter_text:
                counter_text = self.generate_proposal(negotiation)
            negotiation.transition(NegotiationState.COUNTER)
            negotiation.add_message(
                sender=self.our_url, content=counter_text, message_type="counter",
            )
            return {
                "action": "counter",
                "response_text": counter_text,
                "new_state": NegotiationState.COUNTER.value,
                "reasoning": evaluation.get("reasoning", ""),
            }

        else:  # reject
            negotiation.transition(NegotiationState.REJECTED)
            response_text = (
                f"Thank you for the proposal, but I don't think this collaboration "
                f"would be the best fit right now. Reason: {evaluation.get('reasoning', 'N/A')}"
            )
            negotiation.add_message(
                sender=self.our_url, content=response_text, message_type="reject",
            )
            return {
                "action": "rejected",
                "response_text": response_text,
                "new_state": NegotiationState.REJECTED.value,
                "reasoning": evaluation.get("reasoning", ""),
            }

    def initiate_negotiation(self, negotiation: Negotiation) -> str:
        """Generate and send the opening proposal."""
        negotiation.transition(NegotiationState.PROPOSED)
        proposal = self.generate_proposal(negotiation)
        negotiation.add_message(
            sender=self.our_url, content=proposal, message_type="proposal",
        )
        return proposal

    def _fallback_proposal(self, negotiation: Negotiation) -> str:
        return (
            f"Hello {negotiation.their_name}! I'm {self.our_name}. "
            f"Based on our match (score: {negotiation.match_score:.2f}), "
            f"I believe we could collaborate. "
            f"Match areas: {', '.join(negotiation.match_reasons[:3])}. "
            f"Would you be interested in exploring a collaboration?"
        )

    def _fallback_evaluation(self, negotiation: Negotiation) -> dict:
        # Without LLM, auto-accept if match score is high enough
        if negotiation.match_score >= 0.4:
            return {
                "decision": "accept",
                "reasoning": f"Match score {negotiation.match_score:.2f} is above threshold",
                "counter_proposal": "",
                "collaboration_summary": f"Collaboration between {self.our_name} and {negotiation.their_name}",
            }
        return {
            "decision": "reject",
            "reasoning": f"Match score {negotiation.match_score:.2f} is below threshold",
            "counter_proposal": "",
            "collaboration_summary": "",
        }

"""Profile Builder — uses LLM to synthesize owner context into an A2A Agent Card."""

from __future__ import annotations

import json
import structlog

from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentProvider
from src.profile.mcp_reader import OwnerContext
from src.llm.provider import LLMProvider, ChatMessage

log = structlog.get_logger()

SYSTEM_PROMPT = """You are a professional profile summarizer for an AI agent network.
Given an owner's context (skills, projects, needs), create a high-level professional profile.

IMPORTANT RULES:
- Be GENERAL — describe categories of expertise, not specific internal details
- NEVER reveal file names, passwords, internal project names, or sensitive data
- Focus on what the owner CAN OFFER and what they NEED
- Keep descriptions concise and professional

Return JSON with this exact structure:
{
  "name": "Short descriptive agent name",
  "description": "One paragraph about the owner's expertise and what they offer",
  "skills": [
    {
      "id": "unique-skill-id",
      "name": "Skill Name",
      "description": "What this skill covers",
      "tags": ["tag1", "tag2"]
    }
  ],
  "needs": ["What the owner is looking for, one sentence each"]
}"""


def build_agent_card_from_context(
    context: OwnerContext,
    agent_name: str,
    agent_url: str,
    llm: LLMProvider | None = None,
    # Legacy params (ignored if llm is provided, used for backward compat)
    openai_api_key: str = "",
    model: str = "gpt-4o-mini",
) -> AgentCard:
    """Build an A2A AgentCard from raw owner context using LLM."""

    # Backward compat: create provider from raw key if no LLMProvider given
    if llm is None and openai_api_key:
        from src.llm.factory import LLMFactory
        llm = LLMFactory.create("openai", api_key=openai_api_key, model=model)

    if llm is None:
        log.warning("no_llm_provider", msg="Building card without LLM — using raw context")
        return _build_card_without_llm(context, agent_name, agent_url)

    log.info("calling_llm", provider=llm.name, model=llm.model,
             context_chars=len(context.raw_text))

    raw_json = llm.chat(
        messages=[
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=context.raw_text),
        ],
        temperature=0.3,
        max_tokens=1000,
        json_mode=True,
    )
    log.info("llm_response_received", chars=len(raw_json))

    try:
        data = json.loads(raw_json or "{}")
    except json.JSONDecodeError:
        log.error("llm_json_parse_error", raw=raw_json)
        return _build_card_without_llm(context, agent_name, agent_url)

    # Build AgentSkill list
    skills: list[AgentSkill] = []
    for i, s in enumerate(data.get("skills", [])):
        skills.append(AgentSkill(
            id=s.get("id", f"skill-{i}"),
            name=s.get("name", "Unknown"),
            description=s.get("description", ""),
            tags=s.get("tags", []),
            examples=[],
            inputModes=["text"],
            outputModes=["text"],
        ))

    card = AgentCard(
        name=data.get("name", agent_name),
        description=data.get("description", "An AI agent"),
        url=agent_url,
        version="0.1.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
            state_transition_history=False,
        ),
        skills=skills,
        security=[],
        provider=AgentProvider(organization="DevPunks", url=agent_url),
    )

    log.info("agent_card_built", name=card.name, skills=len(skills))
    return card


def _build_card_without_llm(
    context: OwnerContext,
    agent_name: str,
    agent_url: str,
) -> AgentCard:
    """Fallback: build card directly from capabilities without LLM."""
    skills = [
        AgentSkill(
            id=f"skill-{i}",
            name=cap.name,
            description=cap.description[:100],
            tags=[cap.category],
            examples=[],
            inputModes=["text"],
            outputModes=["text"],
        )
        for i, cap in enumerate(context.capabilities)
    ]

    return AgentCard(
        name=agent_name,
        description=f"AI agent representing its owner. Capabilities: {', '.join(s.name for s in skills)}",
        url=agent_url,
        version="0.1.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
            state_transition_history=False,
        ),
        skills=skills,
        security=[],
        provider=AgentProvider(organization="DevPunks", url=agent_url),
    )

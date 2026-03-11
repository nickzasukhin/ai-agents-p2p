"""Onboarding Interviewer — chat-based profile creation via LLM.

Replaces manual markdown file editing with a conversational interview.
The interviewer guides the user through a structured conversation to
collect skills, interests, and collaboration needs, then generates
profile.md, skills.md, and needs.md files + an Agent Card preview.
"""

from __future__ import annotations

import json
import uuid
import structlog
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

from src.llm.provider import LLMProvider, ChatMessage

log = structlog.get_logger()


class OnboardingState(str, Enum):
    """States of the onboarding interview."""
    GREETING = "greeting"                   # Initial state: ask for name + skills
    COLLECTING_NEEDS = "collecting_needs"   # Got skills, now asking for needs
    GENERATING = "generating"              # Generating profile from data
    REVIEW = "review"                      # Profile ready for review
    CONFIRMED = "confirmed"                # User confirmed, files written


# State machine: current → next
_NEXT_STATE = {
    OnboardingState.GREETING: OnboardingState.COLLECTING_NEEDS,
    OnboardingState.COLLECTING_NEEDS: OnboardingState.GENERATING,
    OnboardingState.GENERATING: OnboardingState.REVIEW,
    OnboardingState.REVIEW: OnboardingState.CONFIRMED,
}

# Progress per state (0.0 to 1.0)
_STATE_PROGRESS = {
    OnboardingState.GREETING: 0.0,
    OnboardingState.COLLECTING_NEEDS: 0.40,
    OnboardingState.GENERATING: 0.75,
    OnboardingState.REVIEW: 0.90,
    OnboardingState.CONFIRMED: 1.0,
}


# ── LLM prompts per state ────────────────────────────────────

GREETING_PROMPT = """You are an onboarding assistant for the DevPunks Agent Network — a P2P platform where AI agents represent their owners and discover collaboration opportunities.

Your task: greet the user warmly and explain that you'll help them set up their agent profile through a quick 3-step chat. Ask them to introduce themselves — their name and what they do professionally (skills, technologies, expertise).

Keep it concise (2-3 sentences), friendly, and professional. Use a slightly informal tech-friendly tone."""

COLLECTING_SKILLS_PROMPT = """You are an onboarding assistant. The user just introduced themselves with their name and skills.

Acknowledge what they shared, then ask what they're looking for — what kind of collaborators, skills, or help they need. Examples:
- Looking for a UI designer
- Need help with DevOps
- Want to find ML experts to collaborate with

Keep it brief (2-3 sentences). Be encouraging."""

COLLECTING_NEEDS_PROMPT = """You are an onboarding assistant. The user told you what they need/are looking for.

Acknowledge their needs, then tell them you have enough info to generate their agent profile. Say something like "Great! Let me put this together for you..."

Keep it to 1-2 sentences."""

GENERATE_PROFILE_PROMPT = """Based on the conversation below, generate structured profile data for a P2P agent network.

Return a JSON object with this exact structure:
{
  "agent_name": "A short professional name for the agent (based on user's name/identity)",
  "description": "1-2 sentence professional description of who this person is and what they do",
  "skills": [
    {"name": "Skill Name", "description": "Brief description of the skill", "tags": ["tag1", "tag2"]}
  ],
  "needs": [
    {"description": "What they're looking for, one item per entry"}
  ],
  "profile_md": "# Profile\\n\\nFormatted markdown profile content",
  "skills_md": "# Skills\\n\\nFormatted markdown skills content",
  "needs_md": "# Needs\\n\\nFormatted markdown needs content"
}

Rules:
- Extract 2-6 distinct skills
- Extract 1-4 needs
- Keep descriptions professional and concise
- Markdown files should be clean and well-formatted
- Tags should be lowercase, single words or hyphenated"""


@dataclass
class OnboardingSession:
    """Tracks state and conversation for one onboarding session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: OnboardingState = OnboardingState.GREETING
    conversation: list[dict] = field(default_factory=list)
    user_name: str = ""
    collected_skills: str = ""
    collected_needs: str = ""
    generated_data: dict = field(default_factory=dict)
    files_preview: dict = field(default_factory=dict)


class OnboardingInterviewer:
    """Manages the onboarding interview flow.

    Uses LLM for conversational responses and profile generation.
    Falls back to structured prompts when LLM is unavailable.
    """

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm
        self._sessions: dict[str, OnboardingSession] = {}

    def start_session(self) -> OnboardingSession:
        """Create a new onboarding session."""
        session = OnboardingSession()
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> OnboardingSession | None:
        """Get an existing session by ID."""
        return self._sessions.get(session_id)

    async def process_start(self) -> dict:
        """Start a new onboarding session and return the greeting."""
        session = self.start_session()

        greeting = await self._generate_response(
            session, GREETING_PROMPT, user_message=None
        )

        session.conversation.append({"role": "assistant", "content": greeting})

        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "response": greeting,
            "progress": _STATE_PROGRESS[session.state],
        }

    async def process_message(self, session_id: str, user_message: str) -> dict:
        """Process a user message and advance the interview.

        Returns: {state, response, progress, card_preview?, files_preview?}
        """
        session = self.get_session(session_id)
        if session is None:
            return {"error": "Session not found", "state": "error"}

        if session.state == OnboardingState.CONFIRMED:
            return {
                "state": session.state.value,
                "response": "Onboarding already completed!",
                "progress": 1.0,
            }

        # Record user message
        session.conversation.append({"role": "user", "content": user_message})

        # Handle edit from REVIEW state — re-collect and re-generate
        if session.state == OnboardingState.REVIEW:
            session.collected_needs = user_message.strip()
            session.state = OnboardingState.GENERATING
            gen_result = await self._generate_profile(session)
            session.state = OnboardingState.REVIEW
            return {
                "state": session.state.value,
                "response": gen_result["response"],
                "progress": _STATE_PROGRESS[session.state],
                "card_preview": gen_result.get("card_preview"),
                "files_preview": gen_result.get("files_preview"),
            }

        # Advance state based on current position
        current_state = session.state
        next_state = _NEXT_STATE.get(current_state, current_state)

        # Store collected data based on what was just asked
        if current_state == OnboardingState.GREETING:
            # User responded to greeting with name + skills intro
            session.user_name = user_message.strip()
            session.collected_skills = user_message.strip()
        elif current_state == OnboardingState.COLLECTING_NEEDS:
            session.collected_needs = user_message.strip()

        # Move to next state
        session.state = next_state

        # Handle generation state specially
        if next_state == OnboardingState.GENERATING:
            # Generate the profile
            gen_result = await self._generate_profile(session)
            # Auto-advance to review
            session.state = OnboardingState.REVIEW

            return {
                "state": session.state.value,
                "response": gen_result["response"],
                "progress": _STATE_PROGRESS[session.state],
                "card_preview": gen_result.get("card_preview"),
                "files_preview": gen_result.get("files_preview"),
            }

        # Generate conversational response
        prompt = self._get_prompt_for_state(next_state)
        response = await self._generate_response(session, prompt, user_message)
        session.conversation.append({"role": "assistant", "content": response})

        return {
            "state": session.state.value,
            "response": response,
            "progress": _STATE_PROGRESS[session.state],
        }

    async def confirm(self, session_id: str) -> dict:
        """Confirm the generated profile and return files to write.

        Returns: {state, files: {profile_md, skills_md, needs_md}, card_preview}
        """
        session = self.get_session(session_id)
        if session is None:
            return {"error": "Session not found"}

        if session.state != OnboardingState.REVIEW:
            return {"error": f"Cannot confirm in state {session.state.value}"}

        session.state = OnboardingState.CONFIRMED

        return {
            "state": session.state.value,
            "files": session.files_preview,
            "card_preview": session.generated_data,
            "progress": 1.0,
        }

    async def _generate_response(
        self,
        session: OnboardingSession,
        system_prompt: str,
        user_message: str | None,
    ) -> str:
        """Generate a conversational response via LLM or fallback."""
        if self.llm is None:
            return self._fallback_response(session)

        messages = [ChatMessage(role="system", content=system_prompt)]

        # Include conversation history for context
        for msg in session.conversation[-6:]:  # Last 6 messages for context
            messages.append(ChatMessage(role=msg["role"], content=msg["content"]))

        if user_message:
            messages.append(ChatMessage(role="user", content=user_message))

        try:
            response = self.llm.chat(
                messages=messages,
                temperature=0.7,
                max_tokens=300,
            )
            return response.strip()
        except Exception as e:
            log.warning("onboarding_llm_error", error=str(e))
            return self._fallback_response(session)

    async def _generate_profile(self, session: OnboardingSession) -> dict:
        """Generate profile files from collected information."""
        # Build conversation summary for LLM
        conv_text = "\n".join(
            f"{msg['role'].upper()}: {msg['content']}"
            for msg in session.conversation
        )

        if self.llm:
            try:
                raw = self.llm.chat(
                    messages=[
                        ChatMessage(role="system", content=GENERATE_PROFILE_PROMPT),
                        ChatMessage(role="user", content=conv_text),
                    ],
                    temperature=0.3,
                    max_tokens=1500,
                    json_mode=True,
                )
                data = json.loads(raw or "{}")
            except Exception as e:
                log.warning("onboarding_profile_gen_error", error=str(e))
                data = self._fallback_profile(session)
        else:
            data = self._fallback_profile(session)

        # Store generated data
        session.generated_data = {
            "agent_name": data.get("agent_name", session.user_name or "My Agent"),
            "description": data.get("description", ""),
            "skills": data.get("skills", []),
            "needs": data.get("needs", []),
        }

        session.files_preview = {
            "profile_md": data.get("profile_md", self._build_fallback_profile_md(session)),
            "skills_md": data.get("skills_md", self._build_fallback_skills_md(session)),
            "needs_md": data.get("needs_md", self._build_fallback_needs_md(session)),
        }

        # Build response text
        skills_summary = ", ".join(
            s["name"] if isinstance(s, dict) else str(s)
            for s in session.generated_data.get("skills", [])[:5]
        )
        response = (
            f"Here's what I've put together for you:\n\n"
            f"**Agent Name:** {session.generated_data['agent_name']}\n"
            f"**Description:** {session.generated_data['description']}\n"
            f"**Skills:** {skills_summary}\n\n"
            f"Does this look good? You can confirm to finalize your profile."
        )

        session.conversation.append({"role": "assistant", "content": response})

        return {
            "response": response,
            "card_preview": session.generated_data,
            "files_preview": session.files_preview,
        }

    def _get_prompt_for_state(self, state: OnboardingState) -> str:
        """Get the LLM system prompt for a given state."""
        prompts = {
            OnboardingState.GREETING: GREETING_PROMPT,
            OnboardingState.COLLECTING_NEEDS: COLLECTING_SKILLS_PROMPT,
        }
        return prompts.get(state, COLLECTING_SKILLS_PROMPT)

    def _fallback_response(self, session: OnboardingSession) -> str:
        """Generate response without LLM based on current state."""
        state = session.state
        if state == OnboardingState.GREETING:
            return (
                "Welcome to the DevPunks Agent Network! "
                "I'll help you set up your agent profile in 2 quick steps. "
                "Tell me about yourself — your name and what you do (skills, technologies, expertise)."
            )
        elif state == OnboardingState.COLLECTING_NEEDS:
            return (
                "Got it! Now, what are you looking for? "
                "What kind of collaborators or skills do you need?"
            )
        elif state == OnboardingState.REVIEW:
            return (
                "Your profile is ready for review. "
                "Confirm to finalize, or tell me what to change."
            )
        return "Let's continue setting up your profile."

    def _fallback_profile(self, session: OnboardingSession) -> dict:
        """Build profile data without LLM from collected text."""
        name = session.user_name or "Agent"
        skills_text = session.collected_skills or "General expertise"
        needs_text = session.collected_needs or "Looking for collaborators"

        # Parse skills from comma/newline separated text
        skill_items = [s.strip() for s in skills_text.replace("\n", ",").split(",") if s.strip()]
        skills = [
            {"name": item, "description": item, "tags": [item.lower().split()[0] if item.split() else "general"]}
            for item in skill_items[:6]
        ]

        # Parse needs
        need_items = [n.strip() for n in needs_text.replace("\n", ",").split(",") if n.strip()]
        needs = [{"description": item} for item in need_items[:4]]

        return {
            "agent_name": f"{name}'s Agent",
            "description": f"Agent representing {name}. Skills: {', '.join(s['name'] for s in skills[:3])}.",
            "skills": skills,
            "needs": needs,
            "profile_md": self._build_fallback_profile_md(session),
            "skills_md": self._build_fallback_skills_md(session),
            "needs_md": self._build_fallback_needs_md(session),
        }

    def _build_fallback_profile_md(self, session: OnboardingSession) -> str:
        name = session.user_name or "Agent Owner"
        return f"# Profile\n\nName: {name}\nRole: Professional\n"

    def _build_fallback_skills_md(self, session: OnboardingSession) -> str:
        skills_text = session.collected_skills or "General expertise"
        items = [s.strip() for s in skills_text.replace("\n", ",").split(",") if s.strip()]
        md = "# Skills\n\n## Expertise\n"
        for item in items[:6]:
            md += f"- {item}\n"
        return md

    def _build_fallback_needs_md(self, session: OnboardingSession) -> str:
        needs_text = session.collected_needs or "Looking for collaborators"
        items = [n.strip() for n in needs_text.replace("\n", ",").split(",") if n.strip()]
        md = "# Needs\n\n## Looking For\n"
        for item in items[:4]:
            md += f"- {item}\n"
        return md

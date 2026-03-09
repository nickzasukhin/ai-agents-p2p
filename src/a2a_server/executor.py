"""A2A Agent Executor — handles incoming A2A protocol messages including negotiations."""

import json
from typing_extensions import override
import structlog

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from src.negotiation.manager import NegotiationManager
from src.privacy.guard import PrivacyGuard

log = structlog.get_logger()


class SocialAgentExecutor(AgentExecutor):
    """Handles A2A message/send requests.

    Phase 1-2: Simple responder with agent info.
    Phase 3: Handles negotiation messages via NegotiationManager.
    Phase 9: Handles chat messages via ChatManager.
    """

    def __init__(
        self,
        agent_name: str,
        negotiation_manager: NegotiationManager | None = None,
        privacy_guard: PrivacyGuard | None = None,
        chat_manager=None,
    ):
        self.agent_name = agent_name
        self.negotiation_manager = negotiation_manager
        self.privacy = privacy_guard or PrivacyGuard()
        self.chat_manager = chat_manager

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Process an incoming A2A message."""
        # Extract the incoming message text
        # A2A SDK wraps parts in Part(root=TextPart(...))
        incoming_text = ""
        if context.message and context.message.parts:
            for part in context.message.parts:
                # Try direct .text first, then .root.text for wrapped parts
                if hasattr(part, "text"):
                    incoming_text += part.text
                elif hasattr(part, "root") and hasattr(part.root, "text"):
                    incoming_text += part.root.text

        log.info("a2a_message_received", agent=self.agent_name, text=incoming_text[:100])

        # Check for prompt injection
        safety = self.privacy.check_injection(incoming_text)
        if not safety["safe"]:
            log.warning("injection_blocked", warnings=safety["warnings"])
            await event_queue.enqueue_event(
                new_agent_text_message(
                    "Message rejected: suspicious content detected."
                )
            )
            return

        # Try to parse as chat or negotiation message
        if incoming_text.strip():
            try:
                parsed = json.loads(incoming_text)
                if isinstance(parsed, dict) and parsed.get("chat") and self.chat_manager:
                    await self._handle_chat(parsed)
                    await event_queue.enqueue_event(
                        new_agent_text_message("Chat message received.")
                    )
                    return
            except json.JSONDecodeError:
                pass

            if self.negotiation_manager:
                response = await self._handle_negotiation(incoming_text)
                await event_queue.enqueue_event(new_agent_text_message(response))
                return

        # Fallback: simple greeting
        response = (
            f"Hello from {self.agent_name}! "
            f"I received your message. "
            f"In future phases, I'll be able to negotiate collaborations. "
            f"For now, check my Agent Card for my capabilities."
        )

        await event_queue.enqueue_event(new_agent_text_message(response))

    async def _handle_negotiation(self, incoming_text: str) -> str:
        """Parse and handle negotiation messages."""
        # Try to parse as structured negotiation JSON
        neg_data = None
        try:
            neg_data = json.loads(incoming_text)
        except json.JSONDecodeError:
            pass

        if neg_data and isinstance(neg_data, dict) and "negotiation" in neg_data:
            # Structured negotiation message
            sender_url = neg_data.get("sender_url", "unknown")
            sender_name = neg_data.get("sender_name", "Unknown Agent")
            message = neg_data.get("message", "")
            neg_id = neg_data.get("negotiation_id")

            result = await self.negotiation_manager.handle_incoming_message(
                sender_url=sender_url,
                sender_name=sender_name,
                message=message,
                negotiation_id=neg_id,
            )

            # Return structured response
            return json.dumps({
                "negotiation": True,
                "negotiation_id": result.get("negotiation_id", ""),
                "action": result.get("action", ""),
                "message": result.get("response_text", ""),
                "state": result.get("new_state", ""),
                "sender_url": self.negotiation_manager.engine.our_url,
                "sender_name": self.agent_name,
            })
        else:
            # Unstructured message — treat as a free-text negotiation proposal
            result = await self.negotiation_manager.handle_incoming_message(
                sender_url="unknown",
                sender_name="Unknown Agent",
                message=incoming_text,
            )
            return result.get("response_text", "Message received.")

    async def _handle_chat(self, data: dict) -> None:
        """Route incoming chat message to ChatManager."""
        remote_neg_id = data.get("negotiation_id", "")
        sender_url = data.get("sender_url", "")
        sender_name = data.get("sender_name", "Unknown")
        message = data.get("message", "")

        # Map remote negotiation_id to our local one via peer URL
        local_neg_id = remote_neg_id
        negotiation_info = None
        if self.negotiation_manager:
            # First try by peer URL (handles different IDs on each side)
            neg = self.negotiation_manager.get_negotiation_for_peer(sender_url)
            if not neg:
                # Fallback: try the remote ID directly
                neg = self.negotiation_manager.get_negotiation(remote_neg_id)
            if neg:
                local_neg_id = neg.id
                negotiation_info = {
                    "collaboration_summary": neg.collaboration_summary,
                }

        await self.chat_manager.handle_incoming_message(
            negotiation_id=local_neg_id,
            sender_url=sender_url,
            sender_name=sender_name,
            message=message,
            negotiation_info=negotiation_info,
            message_type=data.get("message_type", "agent"),
        )

    @override
    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cancel an ongoing task."""
        log.info("a2a_task_cancelled", agent=self.agent_name)
        await event_queue.enqueue_event(
            new_agent_text_message("Task cancelled.")
        )

"""ChatManager — handles agent-to-agent chat after confirmed collaborations.

Supports two modes:
- auto: agent auto-starts chat and auto-replies via LLM after CONFIRMED
- manual: owner writes messages manually, no LLM auto-reply
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
import structlog

from src.llm.provider import LLMProvider, ChatMessage
from src.notification.events import EventBus, EventType
from src.privacy.guard import PrivacyGuard

log = structlog.get_logger()


class ChatManager:
    """Manages chat conversations between agents after confirmed negotiations."""

    def __init__(
        self,
        llm: LLMProvider,
        event_bus: EventBus,
        privacy_guard: PrivacyGuard,
        storage=None,
        our_url: str = "",
        our_name: str = "",
        chat_mode: str = "auto",
        max_rounds: int = 10,
    ):
        self.llm = llm
        self.event_bus = event_bus
        self.privacy = privacy_guard
        self.storage = storage
        self.our_url = our_url
        self.our_name = our_name
        self.chat_mode = chat_mode
        self.max_rounds = max_rounds

    async def start_chat(self, negotiation: dict) -> dict | None:
        """Start a chat for a confirmed negotiation (auto mode only).

        Args:
            negotiation: dict with id, their_url, their_name, our_name,
                         collaboration_summary, our_skills, their_skills.

        Returns:
            The sent message dict, or None if not in auto mode.
        """
        if self.chat_mode != "auto":
            return None

        neg_id = negotiation["id"]

        # Check if chat already started
        if self.storage:
            count = await self.storage.get_chat_message_count(neg_id)
            if count > 0:
                log.debug("chat_already_started", neg_id=neg_id)
                return None

        # Generate first message via LLM
        summary = negotiation.get("collaboration_summary", "a collaboration")
        their_name = negotiation.get("their_name", "partner")

        prompt = (
            f"You are {self.our_name}, an AI agent. You just confirmed a collaboration with {their_name}.\n"
            f"Collaboration details: {summary}\n\n"
            f"Write a brief opening message (2-3 sentences) to start planning "
            f"the collaboration. Be specific about next steps, ask a concrete question."
        )

        try:
            text = self.llm.chat([
                ChatMessage(role="system", content="You are a professional AI agent planning a collaboration. Be concise and action-oriented."),
                ChatMessage(role="user", content=prompt),
            ], temperature=0.7, max_tokens=200)
        except Exception as e:
            log.error("chat_llm_error", error=str(e), neg_id=neg_id)
            return None

        text = self.privacy.filter_output(text)

        # Save and send
        msg = await self._save_message(neg_id, self.our_url, self.our_name, text, "agent")

        self.event_bus.emit(EventType.CHAT_STARTED, {
            "negotiation_id": neg_id,
            "their_name": their_name,
        })

        # Send to peer via A2A
        their_url = negotiation.get("their_url", "")
        if their_url:
            await self._send_to_peer(their_url, neg_id, text)

        return msg

    async def handle_incoming_message(
        self,
        negotiation_id: str,
        sender_url: str,
        sender_name: str,
        message: str,
        negotiation_info: dict | None = None,
        message_type: str = "agent",
    ) -> dict | None:
        """Handle an incoming chat message from a peer.

        Args:
            negotiation_id: The negotiation this chat belongs to.
            sender_url: URL of the sending agent.
            sender_name: Name of the sending agent.
            message: The message text.
            negotiation_info: Optional context (collaboration_summary, etc.)
            message_type: "agent" or "owner" — owner messages bypass max rounds.

        Returns:
            Auto-reply message dict if auto mode, else None.
        """
        # Check for injection
        safety = self.privacy.check_injection(message)
        if not safety["safe"]:
            log.warning("chat_injection_blocked", warnings=safety["warnings"])
            return None

        # Save incoming message (preserve type — owner messages shown differently)
        await self._save_message(negotiation_id, sender_url, sender_name, message, message_type)

        self.event_bus.emit(EventType.CHAT_MESSAGE_RECEIVED, {
            "negotiation_id": negotiation_id,
            "sender_name": sender_name,
            "message": message[:200],
        })

        # Auto-reply if in auto mode and under max rounds
        if self.chat_mode != "auto":
            return None

        # Owner messages always get a reply (human joined the conversation)
        is_owner_message = message_type == "owner"

        if self.storage and not is_owner_message:
            count = await self.storage.get_chat_message_count(negotiation_id)
            # Count includes the message we just saved; each side contributes ~half
            our_count = count // 2
            if our_count >= self.max_rounds:
                log.info("chat_max_rounds", neg_id=negotiation_id, rounds=our_count)
                return None

        # Generate auto-reply
        reply_text = await self._generate_reply(negotiation_id, sender_name, negotiation_info, message_type)
        if not reply_text:
            return None

        reply_text = self.privacy.filter_output(reply_text)

        # Save our reply
        msg = await self._save_message(negotiation_id, self.our_url, self.our_name, reply_text, "agent")

        self.event_bus.emit(EventType.CHAT_MESSAGE_SENT, {
            "negotiation_id": negotiation_id,
            "message": reply_text[:200],
        })

        # Send reply to peer
        if sender_url:
            await self._send_to_peer(sender_url, negotiation_id, reply_text)

        return msg

    async def send_owner_message(self, negotiation_id: str, text: str, their_url: str) -> dict:
        """Send a message from the human owner (manual mode or 'Join' in auto mode).

        Args:
            negotiation_id: The negotiation this chat belongs to.
            text: The owner's message text.
            their_url: URL of the peer agent.

        Returns:
            The saved message dict.
        """
        text = self.privacy.filter_output(text)

        msg = await self._save_message(negotiation_id, self.our_url, self.our_name, text, "owner")

        self.event_bus.emit(EventType.CHAT_MESSAGE_SENT, {
            "negotiation_id": negotiation_id,
            "message": text[:200],
            "message_type": "owner",
        })

        # Send to peer via A2A (mark as owner message so peer always replies)
        if their_url:
            await self._send_to_peer(their_url, negotiation_id, text, message_type="owner")

        return msg

    async def get_messages(self, negotiation_id: str, limit: int = 100) -> list[dict]:
        """Get chat history for a negotiation."""
        if not self.storage:
            return []
        return await self.storage.get_chat_messages(negotiation_id, limit)

    async def get_chats(self) -> list[dict]:
        """List all negotiations that have chat messages.

        Returns list of dicts with negotiation_id, message_count, last_message.
        """
        if not self.storage:
            return []

        # Get all confirmed negotiations
        negotiations = await self.storage.get_all_negotiations()
        chats = []
        for neg in negotiations:
            if neg.get("state") != "confirmed":
                continue
            neg_id = neg["id"]
            count = await self.storage.get_chat_message_count(neg_id)
            if count == 0:
                # Include confirmed negotiations even without messages (for manual mode)
                chats.append({
                    "negotiation_id": neg_id,
                    "their_name": neg.get("their_name", ""),
                    "their_url": neg.get("their_url", ""),
                    "message_count": 0,
                    "last_message": None,
                    "collaboration_summary": neg.get("collaboration_summary", ""),
                })
                continue
            messages = await self.storage.get_chat_messages(neg_id, limit=1)
            last = messages[0] if messages else None
            chats.append({
                "negotiation_id": neg_id,
                "their_name": neg.get("their_name", ""),
                "their_url": neg.get("their_url", ""),
                "message_count": count,
                "last_message": last,
                "collaboration_summary": neg.get("collaboration_summary", ""),
            })
        return chats

    # --- Internal helpers ---

    async def _save_message(
        self, negotiation_id: str, sender_url: str, sender_name: str,
        text: str, message_type: str,
    ) -> dict:
        """Create and persist a chat message."""
        msg = {
            "id": str(uuid.uuid4()),
            "negotiation_id": negotiation_id,
            "sender_url": sender_url,
            "sender_name": sender_name,
            "message": text,
            "message_type": message_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if self.storage:
            await self.storage.save_chat_message(msg)
        return msg

    async def _generate_reply(
        self, negotiation_id: str, sender_name: str,
        negotiation_info: dict | None, message_type: str = "agent",
    ) -> str | None:
        """Generate an LLM reply based on conversation history."""
        is_owner_msg = message_type == "owner"

        # Load full history, then take the last N for context
        history = await self.get_messages(negotiation_id, limit=100)
        # For owner messages, keep only recent context to stay focused on their question
        if is_owner_msg and len(history) > 6:
            history = history[-6:]

        conversation = []
        for m in history:
            role = "assistant" if m["sender_url"] == self.our_url else "user"
            # Mark owner messages so LLM knows a human is talking
            prefix = ""
            if m.get("message_type") == "owner" and m["sender_url"] != self.our_url:
                prefix = "[Human owner speaking] "
            conversation.append(ChatMessage(role=role, content=prefix + m["message"]))

        summary = ""
        if negotiation_info:
            summary = negotiation_info.get("collaboration_summary", "")

        system_prompt = (
            f"You are {self.our_name}, an AI agent in a collaboration chat with {sender_name}.\n"
        )
        if summary:
            system_prompt += f"Collaboration context: {summary}\n"

        if is_owner_msg:
            system_prompt += (
                "IMPORTANT: The human owner of the other agent has joined the conversation. "
                "Their latest message is a direct question or request from a real person. "
                "Reply specifically to what they asked. Be helpful, concrete, and on-topic. "
                "Keep it concise (2-3 sentences)."
            )
        else:
            system_prompt += (
                "Continue the conversation naturally. Be concise (2-4 sentences). "
                "Discuss concrete next steps, timelines, or ask clarifying questions. "
                "If the conversation has covered enough, summarize agreed points and wrap up."
            )

        messages = [ChatMessage(role="system", content=system_prompt)] + conversation

        try:
            return self.llm.chat(messages, temperature=0.7, max_tokens=250)
        except Exception as e:
            log.error("chat_reply_error", error=str(e), neg_id=negotiation_id)
            return None

    async def _send_to_peer(self, peer_url: str, negotiation_id: str, text: str, message_type: str = "agent") -> bool:
        """Send a chat message to a peer agent via A2A JSON-RPC."""
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": f"chat-{negotiation_id}-{uuid.uuid4().hex[:8]}",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": json.dumps({
                        "chat": True,
                        "negotiation_id": negotiation_id,
                        "sender_url": self.our_url,
                        "sender_name": self.our_name,
                        "message": text,
                        "message_type": message_type,
                    })}],
                    "messageId": f"chat-{uuid.uuid4().hex[:8]}",
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    peer_url.rstrip("/") + "/",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    log.info("chat_sent", peer=peer_url[:40], neg_id=negotiation_id)
                    return True
                else:
                    log.warning("chat_send_error", status=resp.status_code, peer=peer_url[:40])
                    return False
        except Exception as e:
            log.error("chat_send_failed", error=str(e), peer=peer_url[:40])
            return False

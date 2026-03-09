"""Tests for LLM provider abstraction layer."""

import json
import pytest
from unittest.mock import MagicMock, patch

from src.llm.provider import LLMProvider, ChatMessage
from src.llm.openai_provider import OpenAIProvider
from src.llm.factory import LLMFactory


# ── ChatMessage ──────────────────────────────────────────────

class TestChatMessage:
    def test_create(self):
        msg = ChatMessage(role="system", content="hello")
        assert msg.role == "system"
        assert msg.content == "hello"

    def test_fields_are_required(self):
        with pytest.raises(TypeError):
            ChatMessage()


# ── LLMFactory ───────────────────────────────────────────────

class TestLLMFactory:
    def test_available_providers_includes_openai(self):
        providers = LLMFactory.available_providers()
        assert "openai" in providers

    @patch("src.llm.openai_provider.OpenAI")
    def test_create_openai(self, mock_openai_cls):
        llm = LLMFactory.create("openai", api_key="sk-test", model="gpt-4o-mini")
        assert isinstance(llm, OpenAIProvider)
        assert llm.name == "openai"
        assert llm.model == "gpt-4o-mini"

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            LLMFactory.create("nonexistent", api_key="key")

    @patch("src.llm.openai_provider.OpenAI")
    def test_create_uses_default_model(self, mock_openai_cls):
        llm = LLMFactory.create("openai", api_key="sk-test")
        assert llm.model == "gpt-4o-mini"


# ── OpenAIProvider ───────────────────────────────────────────

class TestOpenAIProvider:
    @patch("src.llm.openai_provider.OpenAI")
    def test_name(self, mock_cls):
        p = OpenAIProvider(api_key="sk-test")
        assert p.name == "openai"

    @patch("src.llm.openai_provider.OpenAI")
    def test_model_default(self, mock_cls):
        p = OpenAIProvider(api_key="sk-test")
        assert p.model == "gpt-4o-mini"

    @patch("src.llm.openai_provider.OpenAI")
    def test_model_custom(self, mock_cls):
        p = OpenAIProvider(api_key="sk-test", model="gpt-4")
        assert p.model == "gpt-4"

    @patch("src.llm.openai_provider.OpenAI")
    def test_chat_calls_sdk(self, mock_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="hello world"))]
        )
        mock_cls.return_value = mock_client

        p = OpenAIProvider(api_key="sk-test", model="gpt-4o-mini")
        result = p.chat(
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.5,
            max_tokens=100,
        )

        assert result == "hello world"
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 100
        assert "response_format" not in call_kwargs

    @patch("src.llm.openai_provider.OpenAI")
    def test_chat_json_mode(self, mock_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"ok": true}'))]
        )
        mock_cls.return_value = mock_client

        p = OpenAIProvider(api_key="sk-test")
        result = p.chat(
            messages=[ChatMessage(role="user", content="give json")],
            json_mode=True,
        )

        assert json.loads(result) == {"ok": True}
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["response_format"] == {"type": "json_object"}

    @patch("src.llm.openai_provider.OpenAI")
    def test_chat_messages_format(self, mock_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"))]
        )
        mock_cls.return_value = mock_client

        p = OpenAIProvider(api_key="sk-test")
        p.chat(messages=[
            ChatMessage(role="system", content="you are helpful"),
            ChatMessage(role="user", content="hello"),
        ])

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["messages"] == [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hello"},
        ]


# ── Consumer Integration (mocked LLM) ────────────────────────

class TestConsumerIntegration:
    def _mock_llm(self, response: str = "mocked") -> MagicMock:
        llm = MagicMock(spec=LLMProvider)
        llm.name = "mock"
        llm.model = "mock-v1"
        llm.chat.return_value = response
        return llm

    def test_builder_with_llm_provider(self):
        from src.profile.builder import build_agent_card_from_context
        from src.profile.mcp_reader import OwnerContext, OwnerCapability

        llm = self._mock_llm(json.dumps({
            "name": "Test Agent",
            "description": "A test",
            "skills": [{"id": "s0", "name": "Testing", "description": "test", "tags": ["qa"]}],
        }))

        ctx = OwnerContext(
            capabilities=[OwnerCapability(name="QA", description="Testing", category="skills")],
            raw_text="# Skills\n- QA\n",
        )
        card = build_agent_card_from_context(ctx, "Agent", "http://test/", llm=llm)
        assert card.name == "Test Agent"
        assert llm.chat.called

    def test_negotiation_engine_with_llm_provider(self):
        from src.negotiation.engine import NegotiationEngine
        from src.negotiation.states import Negotiation, NegotiationState

        llm = self._mock_llm("I propose we collaborate on X.")
        engine = NegotiationEngine(
            our_context_raw="I am a developer",
            our_name="Agent-A",
            our_url="http://a:9000",
            llm=llm,
        )

        neg = Negotiation(
            id="n-1",
            our_url="http://a:9000",
            their_url="http://b:9000",
            their_name="Agent-B",
            match_score=0.8,
            match_reasons=["complementary skills"],
        )
        proposal = engine.generate_proposal(neg)
        assert "collaborate" in proposal
        assert llm.chat.called

    def test_negotiation_engine_no_llm_uses_fallback(self):
        from src.negotiation.engine import NegotiationEngine
        from src.negotiation.states import Negotiation

        engine = NegotiationEngine(
            our_context_raw="I am a developer",
            our_name="Agent-A",
            our_url="http://a:9000",
            llm=None,
        )
        neg = Negotiation(
            id="n-1",
            our_url="http://a:9000",
            their_url="http://b:9000",
            their_name="Agent-B",
            match_score=0.8,
            match_reasons=["complementary skills"],
        )
        proposal = engine.generate_proposal(neg)
        assert len(proposal) > 0

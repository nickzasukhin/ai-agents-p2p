"""A2A Server builder — creates Starlette app with Agent Card endpoint."""

import structlog

from a2a.types import AgentCard
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from starlette.applications import Starlette

from src.a2a_server.executor import SocialAgentExecutor
from src.negotiation.manager import NegotiationManager
from src.privacy.guard import PrivacyGuard

log = structlog.get_logger()


def build_a2a_app(
    agent_card: AgentCard,
    negotiation_manager: NegotiationManager | None = None,
    privacy_guard: PrivacyGuard | None = None,
    chat_manager=None,
) -> Starlette:
    """Build a Starlette app that serves the A2A protocol.

    This includes:
    - /.well-known/agent-card.json — the agent's public profile
    - /message/send — A2A message endpoint (handles negotiations + chat)
    - /task/* — A2A task management endpoints
    """
    executor = SocialAgentExecutor(
        agent_name=agent_card.name,
        negotiation_manager=negotiation_manager,
        privacy_guard=privacy_guard,
        chat_manager=chat_manager,
    )

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )

    app_builder = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    log.info("a2a_app_built", agent=agent_card.name, url=agent_card.url,
             negotiation="enabled" if negotiation_manager else "disabled")
    return app_builder.build()

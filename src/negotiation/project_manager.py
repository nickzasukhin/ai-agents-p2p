"""Project Manager — orchestrates multi-agent collaboration projects.

Projects are an overlay on existing 1:1 negotiations. The coordinator agent
creates a project with roles, recruits agents via existing negotiation flow,
and tracks progress as negotiations complete.
"""

from __future__ import annotations

import json
import structlog
from src.negotiation.project import (
    Project, ProjectRole, ProjectState, PROJECT_TRANSITIONS,
)
from src.negotiation.manager import NegotiationManager
from src.negotiation.states import NegotiationState
from src.notification.events import EventBus, EventType
from src.llm.provider import LLMProvider, ChatMessage

log = structlog.get_logger()


class ProjectManager:
    """Manages multi-agent collaboration projects.

    Overlay on NegotiationManager — reads negotiation states via pull,
    does not modify the negotiation layer.
    """

    def __init__(
        self,
        negotiation_manager: NegotiationManager,
        event_bus: EventBus,
        our_url: str = "",
        our_name: str = "",
        storage=None,
        llm: LLMProvider | None = None,
        # Legacy params (ignored if llm is provided)
        openai_api_key: str = "",
        openai_model: str = "gpt-4o-mini",
    ):
        # Backward compat: create provider from raw key if no LLMProvider given
        if llm is None and openai_api_key:
            from src.llm.factory import LLMFactory
            llm = LLMFactory.create("openai", api_key=openai_api_key, model=openai_model)

        self.llm = llm
        self.negotiation_manager = negotiation_manager
        self.event_bus = event_bus
        self.our_url = our_url
        self.our_name = our_name
        self.storage = storage
        self._projects: dict[str, Project] = {}

    async def load_from_storage(self) -> int:
        """Load projects from SQLite on startup."""
        if not self.storage:
            return 0
        rows = await self.storage.get_all_projects()
        for row in rows:
            project = Project.from_dict(row)
            self._projects[project.id] = project
        log.info("projects_loaded_from_storage", count=len(rows))
        return len(rows)

    async def _persist(self, project: Project) -> None:
        """Persist project to SQLite."""
        if not self.storage:
            return
        d = project.to_dict()
        d["roles"] = [r.to_dict() for r in project.roles]
        await self.storage.save_project(d)

    def create_project(
        self,
        name: str,
        description: str,
        roles: list[dict],
    ) -> Project:
        """Create a new project with defined roles.

        Args:
            name: Project name (e.g., "AI Dashboard")
            description: What this project does
            roles: List of role dicts with role_name, description, and optional
                   agent_url/agent_name for pre-assigned agents.
        """
        project = Project(
            name=name,
            description=description,
            coordinator_url=self.our_url,
            coordinator_name=self.our_name,
            roles=[ProjectRole.from_dict(r) for r in roles],
        )
        self._projects[project.id] = project

        self.event_bus.emit(EventType.PROJECT_CREATED, {
            "project_id": project.id,
            "name": name,
            "roles_count": len(roles),
        })

        log.info("project_created", id=project.id, name=name, roles=len(roles))
        return project

    async def recruit(self, project_id: str) -> dict:
        """Start negotiations for open roles in a project.

        Matches open roles to confirmed/active negotiations,
        or initiates new negotiations for unmatched roles.
        """
        project = self._projects.get(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}

        if project.state == ProjectState.DRAFT:
            project.transition(ProjectState.RECRUITING)

        recruited = []
        for role in project.roles:
            if role.status != "open":
                continue
            # Check if there's a suggested agent and existing negotiation
            if role.agent_url:
                neg = self.negotiation_manager.get_negotiation_for_peer(role.agent_url)
                if neg:
                    role.negotiation_id = neg.id
                    role.agent_name = neg.their_name
                    role.status = "negotiating"
                    recruited.append({
                        "role": role.role_name,
                        "agent": role.agent_name,
                        "negotiation_id": neg.id,
                        "action": "linked_existing",
                    })

        project.updated_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()

        self.event_bus.emit(EventType.PROJECT_RECRUITING, {
            "project_id": project.id,
            "name": project.name,
            "recruited": len(recruited),
            "open_roles": len(project.open_roles),
        })

        await self._persist(project)
        log.info("project_recruiting", id=project.id, recruited=len(recruited))

        return {
            "project_id": project.id,
            "state": project.state.value,
            "recruited": recruited,
            "open_roles": len(project.open_roles),
        }

    async def sync(self, project_id: str) -> dict:
        """Sync project role statuses from NegotiationManager.

        Pulls current negotiation states and updates role statuses.
        May trigger project state transitions (PARTIAL, ACTIVE, STALLED).
        """
        project = self._projects.get(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}

        changes = []
        for role in project.roles:
            if not role.negotiation_id:
                continue

            neg = self.negotiation_manager.get_negotiation(role.negotiation_id)
            if not neg:
                continue

            old_status = role.status
            # Map negotiation state → role status
            if neg.state == NegotiationState.CONFIRMED:
                role.status = "confirmed"
                role.agent_name = neg.their_name
                role.agent_url = neg.their_url
            elif neg.state in {NegotiationState.REJECTED, NegotiationState.DECLINED, NegotiationState.TIMEOUT}:
                role.status = "rejected"
            elif neg.state in {NegotiationState.PROPOSED, NegotiationState.COUNTER, NegotiationState.EVALUATING, NegotiationState.ACCEPTED, NegotiationState.OWNER_REVIEW}:
                role.status = "negotiating"
            elif neg.state == NegotiationState.INIT:
                role.status = "negotiating"

            if old_status != role.status:
                changes.append({
                    "role": role.role_name,
                    "old_status": old_status,
                    "new_status": role.status,
                    "negotiation_state": neg.state.value,
                })

        # Determine project state based on role statuses
        old_state = project.state
        confirmed_count = len([r for r in project.roles if r.status == "confirmed"])
        rejected_count = len([r for r in project.roles if r.status == "rejected"])
        total_roles = len(project.roles)

        if rejected_count > 0 and project.state not in {ProjectState.DRAFT, ProjectState.COMPLETED}:
            if project.can_transition_to(ProjectState.STALLED):
                project.transition(ProjectState.STALLED)
                self.event_bus.emit(EventType.PROJECT_STALLED, {
                    "project_id": project.id,
                    "name": project.name,
                    "rejected_roles": rejected_count,
                })
        elif confirmed_count == total_roles and total_roles > 0:
            if project.can_transition_to(ProjectState.ACTIVE):
                project.transition(ProjectState.ACTIVE)
                self.event_bus.emit(EventType.PROJECT_ACTIVE, {
                    "project_id": project.id,
                    "name": project.name,
                    "agents": [r.agent_name for r in project.roles],
                })
        elif confirmed_count > 0 and confirmed_count < total_roles:
            if project.state == ProjectState.RECRUITING and project.can_transition_to(ProjectState.PARTIAL):
                project.transition(ProjectState.PARTIAL)

        if old_state != project.state:
            changes.append({
                "project_state_change": f"{old_state.value} -> {project.state.value}",
            })

        await self._persist(project)
        log.info(
            "project_synced", id=project.id,
            state=project.state.value,
            confirmed=confirmed_count,
            changes=len(changes),
        )

        return {
            "project_id": project.id,
            "state": project.state.value,
            "progress": round(project.progress, 2),
            "changes": changes,
            "confirmed": confirmed_count,
            "total": total_roles,
        }

    async def complete(self, project_id: str) -> dict:
        """Mark a project as completed."""
        project = self._projects.get(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}

        if not project.can_transition_to(ProjectState.COMPLETED):
            return {
                "error": f"Cannot complete project in state {project.state.value}. Must be ACTIVE.",
            }

        project.transition(ProjectState.COMPLETED)
        self.event_bus.emit(EventType.PROJECT_COMPLETED, {
            "project_id": project.id,
            "name": project.name,
            "agents": [r.agent_name for r in project.filled_roles],
        })
        await self._persist(project)
        log.info("project_completed", id=project.id, name=project.name)
        return {"status": "completed", "project_id": project.id}

    async def suggest_project(self, matches: list[dict]) -> dict:
        """Use LLM to suggest a project based on current matches.

        Args:
            matches: List of match dicts from the discovery engine.

        Returns:
            Suggested project dict with name, description, and roles.
        """
        if not matches:
            return {"error": "No matches available for project suggestion"}

        if not self.llm:
            return self._suggest_fallback(matches)

        try:
            match_info = "\n".join(
                f"- {m.get('agent_name', 'Unknown')} (score: {m.get('overall_score', 0):.2f}): "
                f"{m.get('description', '')[:200]}"
                for m in matches[:5]
            )

            raw = self.llm.chat(
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "You are a project manager suggesting collaboration projects. "
                            "Given a list of potential agent partners with their skills, "
                            "suggest a concrete project that leverages their combined expertise. "
                            "Return JSON with: name, description, roles (array of {role_name, description, suggested_agent})."
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=(
                            f"Our agent: {self.our_name}\n\n"
                            f"Available partners:\n{match_info}\n\n"
                            "Suggest a project we could collaborate on."
                        ),
                    ),
                ],
                temperature=0.7,
                json_mode=True,
            )

            suggestion = json.loads(raw)

            self.event_bus.emit(EventType.PROJECT_SUGGESTION, {
                "name": suggestion.get("name", ""),
                "roles_count": len(suggestion.get("roles", [])),
            })

            log.info("project_suggested", name=suggestion.get("name", ""))
            return suggestion

        except Exception as e:
            log.warning("project_suggest_llm_error", error=str(e))
            return self._suggest_fallback(matches)

    def _suggest_fallback(self, matches: list[dict]) -> dict:
        """Generate a basic project suggestion without LLM."""
        roles = []
        for m in matches[:4]:
            agent_name = m.get("agent_name", "Unknown")
            description_text = m.get("description", "")[:100]
            roles.append({
                "role_name": f"Contributor ({agent_name})",
                "description": f"Collaborate based on matched skills: {description_text}",
                "suggested_agent": agent_name,
                "suggested_agent_url": m.get("agent_url", ""),
            })

        return {
            "name": f"Collaboration Project ({len(roles)} agents)",
            "description": f"Multi-agent project combining {len(roles)} matched partners.",
            "roles": roles,
        }

    def get_project(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    def get_all_projects(self) -> list[Project]:
        return list(self._projects.values())

    def get_active_projects(self) -> list[Project]:
        return [p for p in self._projects.values() if p.state == ProjectState.ACTIVE]

    def get_status(self) -> dict:
        all_projects = self.get_all_projects()
        return {
            "total": len(all_projects),
            "draft": sum(1 for p in all_projects if p.state == ProjectState.DRAFT),
            "recruiting": sum(1 for p in all_projects if p.state == ProjectState.RECRUITING),
            "partial": sum(1 for p in all_projects if p.state == ProjectState.PARTIAL),
            "active": sum(1 for p in all_projects if p.state == ProjectState.ACTIVE),
            "completed": sum(1 for p in all_projects if p.state == ProjectState.COMPLETED),
            "stalled": sum(1 for p in all_projects if p.state == ProjectState.STALLED),
        }

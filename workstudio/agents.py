"""
Agents module for the work.studio SDK.

Routes (under ``/api/v1/workflow``):

- ``/catalog/ai-agents`` (catalog ``AIAgentUnifiedController``): list, ``/by-id/{id}``,
  ``/{globalUniqueId}``. Organization keys with ``catalog:read``; customer keys get 403. Served by
  the monolith.
- ``/ai-runtime/agent-conversation/sessions`` (ai-runtime ``AgentConversationController``): start
  (POST), ``/{id}/messages`` (POST), state (GET ``/{id}``), end (DELETE ``/{id}``). Keys need
  ``agent:execute`` (state: ``agent:read`` or ``agent:execute``). Prod routes
  ``/api/v1/workflow/ai-runtime/*`` to the ai-runtime service.
"""

import warnings
from typing import Any, Optional, Union
from uuid import UUID

from workstudio._http import AsyncHTTPClient, HTTPClient
from workstudio.exceptions import AgentTurnError, NotFoundError
from workstudio.models import (
    Agent,
    AgentSession,
    MessageResponse,
    MessageStatus,
    PageInfo,
    parse_page,
)

# API paths
API_PREFIX = "/api/v1/workflow"
CATALOG_PATH = f"{API_PREFIX}/catalog/ai-agents"
AI_RUNTIME_PATH = f"{API_PREFIX}/ai-runtime/agent-conversation"

#: How many agents a name lookup reads (the catalog search is a substring match).
_NAME_LOOKUP_PAGE_SIZE = 50


def _list_params(
    page: int, size: int, search: Optional[str], status: Optional[str], active: Optional[bool]
) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "size": size}
    if search:
        params["search"] = search
    if status:
        # The catalog has no status filter (it ignored this parameter); it has ``active``.
        warnings.warn(
            "agents.list(status=...) has no effect: the platform does not filter agents by status. "
            "Use active=True/False.",
            DeprecationWarning,
            stacklevel=3,
        )
    if active is not None:
        params["active"] = "true" if active else "false"
    return params


def _message_body(message: str) -> dict[str, Any]:
    # ai-runtime TestMessageRequest: message, context, activeSkillIds. There is no includeDebug: a
    # session reports tool and knowledge-base details on every message (debugMode defaults to true).
    return {"message": message}


def _turn_reply(body: dict[str, Any]) -> MessageResponse:
    """
    The reply to a sent message, or ``AgentTurnError`` when the turn failed.

    ai-runtime answers a failed turn with a 2xx and ``status: ERROR`` (with ``errorMessage`` and,
    when the failure has one, ``errorCode``), so a failure is read from the body, not the status.
    """
    reply = MessageResponse.model_validate(body)
    if reply.status == MessageStatus.ERROR:
        raise AgentTurnError(
            message=reply.error_message or "The agent's turn failed",
            error_code=reply.error_code or None,
            session_id=reply.session_id,
            response_body=body,
            response=reply,
        )
    return reply


class LiveSession:
    """
    A live conversation session with an agent.

    Use this to maintain context across multiple messages.

    Example:
        session = client.agents.create_session("sales-assistant")
        response = session.send_message("What are our top deals?")
        print(response.message)
        response = session.send_message("Tell me more about the first one")
        print(response.message)
        session.close()
    """

    def __init__(
        self,
        http: HTTPClient,
        session_id: UUID,
        agent_id: UUID,
        agent_name: Optional[str] = None,
    ):
        self._http = http
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self._closed = False

    def send_message(
        self,
        message: str,
        include_debug: bool = False,
    ) -> MessageResponse:
        """
        Send a message in this session.

        Args:
            message: The message to send
            include_debug: Kept for compatibility; the platform reports tool and knowledge-base
                details on every message, so it has no effect

        Returns:
            The agent's response with metrics

        Raises:
            AgentTurnError: The turn failed (the platform's reply said ``status: ERROR``); its
                ``error_code`` carries the platform's code when there is one
        """
        if self._closed:
            raise RuntimeError("Session is closed")

        response = self._http.post(
            f"{AI_RUNTIME_PATH}/sessions/{self.session_id}/messages",
            json=_message_body(message),
        )
        return _turn_reply(response)

    def get_state(self) -> AgentSession:
        """Get the current session state and metrics."""
        response = self._http.get(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}")
        return AgentSession.model_validate(response)

    def close(self) -> None:
        """End this session."""
        if not self._closed:
            try:
                self._http.delete(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}")
            except Exception:
                pass  # Best effort
            self._closed = True

    def __enter__(self) -> "LiveSession":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncLiveSession:
    """Async version of LiveSession."""

    def __init__(
        self,
        http: AsyncHTTPClient,
        session_id: UUID,
        agent_id: UUID,
        agent_name: Optional[str] = None,
    ):
        self._http = http
        self.session_id = session_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self._closed = False

    async def send_message(
        self,
        message: str,
        include_debug: bool = False,
    ) -> MessageResponse:
        """Send a message in this session. Raises ``AgentTurnError`` when the turn failed."""
        if self._closed:
            raise RuntimeError("Session is closed")

        response = await self._http.post(
            f"{AI_RUNTIME_PATH}/sessions/{self.session_id}/messages",
            json=_message_body(message),
        )
        return _turn_reply(response)

    async def get_state(self) -> AgentSession:
        """Get the current session state and metrics."""
        response = await self._http.get(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}")
        return AgentSession.model_validate(response)

    async def close(self) -> None:
        """End this session."""
        if not self._closed:
            try:
                await self._http.delete(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}")
            except Exception:
                pass
            self._closed = True

    async def __aenter__(self) -> "AsyncLiveSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()


class AgentsClient:
    """Synchronous client for agent operations."""

    def __init__(self, http: HTTPClient):
        self._http = http

    def list(
        self,
        page: int = 0,
        size: int = 20,
        search: Optional[str] = None,
        status: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> tuple[list[Agent], PageInfo]:
        """
        List all agents.

        Args:
            page: Page number (0-indexed)
            size: Number of items per page
            search: Optional search query
            status: Deprecated, has no effect (the platform has no agent status filter)
            active: Only active (True) or inactive (False) agents

        Returns:
            Tuple of (agents list, page info)

        Example:
            agents, _ = client.agents.list(active=True)
            for agent in agents:
                print(f"{agent.name}: {agent.description}")
        """
        params = _list_params(page, size, search, status, active)

        items, page_info = parse_page(self._http.get(CATALOG_PATH, params=params))
        return [Agent.model_validate(a) for a in items], page_info

    def get(self, agent_id: Union[UUID, str]) -> Agent:
        """
        Get an agent by ID.

        Args:
            agent_id: The agent id (``Agent.id``) or its global unique id

        Returns:
            The agent

        Raises:
            NotFoundError: If agent not found
        """
        # /{id} on the catalog is the GLOBAL id; Agent.id is the row id, read by /by-id/{id}.
        try:
            response = self._http.get(f"{CATALOG_PATH}/by-id/{agent_id}")
        except NotFoundError:
            response = self._http.get(f"{CATALOG_PATH}/{agent_id}")
        return Agent.model_validate(response)

    def get_by_name(self, name: str) -> Optional[Agent]:
        """
        Get an agent by name.

        Args:
            name: The agent name

        Returns:
            The agent, or None if not found
        """
        agents, _ = self.list(search=name, size=_NAME_LOOKUP_PAGE_SIZE)
        for agent in agents:
            if agent.name.lower() == name.lower():
                return agent
        return None

    def create_session(
        self,
        agent_id: Union[UUID, str],
    ) -> LiveSession:
        """
        Create a new conversation session with an agent.

        Args:
            agent_id: The agent UUID or name

        Returns:
            A LiveSession for sending messages

        Example:
            with client.agents.create_session("sales-assistant") as session:
                response = session.send_message("Hello!")
                print(response.message)
        """
        # Resolve name to ID if needed
        resolved_id: UUID
        agent_name: Optional[str] = None

        try:
            resolved_id = UUID(str(agent_id))
        except ValueError:
            # It's a name, look it up
            agent = self.get_by_name(str(agent_id))
            if not agent:
                raise NotFoundError(f"Agent not found: {agent_id}")
            resolved_id = agent.id
            agent_name = agent.name

        response = self._http.post(
            f"{AI_RUNTIME_PATH}/sessions",
            json={"agentId": str(resolved_id)},
        )

        session_id = UUID(response["sessionId"])

        return LiveSession(
            http=self._http,
            session_id=session_id,
            agent_id=resolved_id,
            agent_name=agent_name or response.get("agentName"),
        )

    def chat(
        self,
        agent_id: Union[UUID, str],
        message: str,
        include_debug: bool = False,
    ) -> MessageResponse:
        """
        Send a single message to an agent (one-shot, no session).

        This is a convenience method for simple queries. For multi-turn
        conversations, use create_session() instead.

        Args:
            agent_id: The agent UUID or name
            message: The message to send
            include_debug: Include debug information

        Returns:
            The agent's response

        Example:
            response = client.agents.chat(
                "sales-assistant",
                "What are our top 3 deals?"
            )
            print(response.message)
        """
        with self.create_session(agent_id) as session:
            return session.send_message(message, include_debug=include_debug)


class AsyncAgentsClient:
    """Asynchronous client for agent operations."""

    def __init__(self, http: AsyncHTTPClient):
        self._http = http

    async def list(
        self,
        page: int = 0,
        size: int = 20,
        search: Optional[str] = None,
        status: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> tuple[list[Agent], PageInfo]:
        """List all agents."""
        params = _list_params(page, size, search, status, active)

        items, page_info = parse_page(await self._http.get(CATALOG_PATH, params=params))
        return [Agent.model_validate(a) for a in items], page_info

    async def get(self, agent_id: Union[UUID, str]) -> Agent:
        """Get an agent by ID."""
        try:
            response = await self._http.get(f"{CATALOG_PATH}/by-id/{agent_id}")
        except NotFoundError:
            response = await self._http.get(f"{CATALOG_PATH}/{agent_id}")
        return Agent.model_validate(response)

    async def get_by_name(self, name: str) -> Optional[Agent]:
        """Get an agent by name."""
        agents, _ = await self.list(search=name, size=_NAME_LOOKUP_PAGE_SIZE)
        for agent in agents:
            if agent.name.lower() == name.lower():
                return agent
        return None

    async def create_session(
        self,
        agent_id: Union[UUID, str],
    ) -> AsyncLiveSession:
        """Create a new conversation session with an agent."""
        resolved_id: UUID
        agent_name: Optional[str] = None

        try:
            resolved_id = UUID(str(agent_id))
        except ValueError:
            agent = await self.get_by_name(str(agent_id))
            if not agent:
                raise NotFoundError(f"Agent not found: {agent_id}")
            resolved_id = agent.id
            agent_name = agent.name

        response = await self._http.post(
            f"{AI_RUNTIME_PATH}/sessions",
            json={"agentId": str(resolved_id)},
        )

        session_id = UUID(response["sessionId"])

        return AsyncLiveSession(
            http=self._http,
            session_id=session_id,
            agent_id=resolved_id,
            agent_name=agent_name or response.get("agentName"),
        )

    async def chat(
        self,
        agent_id: Union[UUID, str],
        message: str,
        include_debug: bool = False,
    ) -> MessageResponse:
        """Send a single message to an agent (one-shot, no session)."""
        async with await self.create_session(agent_id) as session:
            return await session.send_message(message, include_debug=include_debug)

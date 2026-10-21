"""
Agents module for the work.studio SDK.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from workstudio._http import AsyncHTTPClient, HTTPClient
from workstudio.models import (
    Agent,
    AgentSession,
    MessageResponse,
    PageInfo,
)

# API paths
API_PREFIX = "/api/v1/workflow"
CATALOG_PATH = f"{API_PREFIX}/catalog/ai-agents"
AI_RUNTIME_PATH = f"{API_PREFIX}/ai-runtime/agent-conversation"


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
            include_debug: Include debug information in response

        Returns:
            The agent's response with metrics
        """
        if self._closed:
            raise RuntimeError("Session is closed")

        response = self._http.post(
            f"{AI_RUNTIME_PATH}/sessions/{self.session_id}/messages",
            json={
                "message": message,
                "includeDebug": include_debug,
            },
        )
        return MessageResponse.model_validate(response)

    def get_state(self) -> AgentSession:
        """Get the current session state and metrics."""
        response = self._http.get(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}")
        return AgentSession.model_validate(response)

    def close(self) -> None:
        """End this session."""
        if not self._closed:
            try:
                self._http.post(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}/end")
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
        """Send a message in this session."""
        if self._closed:
            raise RuntimeError("Session is closed")

        response = await self._http.post(
            f"{AI_RUNTIME_PATH}/sessions/{self.session_id}/messages",
            json={
                "message": message,
                "includeDebug": include_debug,
            },
        )
        return MessageResponse.model_validate(response)

    async def get_state(self) -> AgentSession:
        """Get the current session state and metrics."""
        response = await self._http.get(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}")
        return AgentSession.model_validate(response)

    async def close(self) -> None:
        """End this session."""
        if not self._closed:
            try:
                await self._http.post(f"{AI_RUNTIME_PATH}/sessions/{self.session_id}/end")
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
    ) -> tuple[list[Agent], PageInfo]:
        """
        List all agents.

        Args:
            page: Page number (0-indexed)
            size: Number of items per page
            search: Optional search query
            status: Filter by status (DRAFT, PUBLISHED, ARCHIVED)

        Returns:
            Tuple of (agents list, page info)

        Example:
            agents, _ = client.agents.list(status="PUBLISHED")
            for agent in agents:
                print(f"{agent.name}: {agent.description}")
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search
        if status:
            params["status"] = status

        response = self._http.get(CATALOG_PATH, params=params)

        agents = [Agent.model_validate(a) for a in response.get("content", [])]
        page_info = PageInfo.model_validate(response.get("pageInfo", {}))

        return agents, page_info

    def get(self, agent_id: UUID | str) -> Agent:
        """
        Get an agent by ID.

        Args:
            agent_id: The agent UUID

        Returns:
            The agent

        Raises:
            NotFoundError: If agent not found
        """
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
        agents, _ = self.list(search=name, size=1)
        for agent in agents:
            if agent.name.lower() == name.lower():
                return agent
        return None

    def create_session(
        self,
        agent_id: UUID | str,
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
                from workstudio.exceptions import NotFoundError
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
        agent_id: UUID | str,
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
    ) -> tuple[list[Agent], PageInfo]:
        """List all agents."""
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search
        if status:
            params["status"] = status

        response = await self._http.get(CATALOG_PATH, params=params)

        agents = [Agent.model_validate(a) for a in response.get("content", [])]
        page_info = PageInfo.model_validate(response.get("pageInfo", {}))

        return agents, page_info

    async def get(self, agent_id: UUID | str) -> Agent:
        """Get an agent by ID."""
        response = await self._http.get(f"{CATALOG_PATH}/{agent_id}")
        return Agent.model_validate(response)

    async def get_by_name(self, name: str) -> Optional[Agent]:
        """Get an agent by name."""
        agents, _ = await self.list(search=name, size=1)
        for agent in agents:
            if agent.name.lower() == name.lower():
                return agent
        return None

    async def create_session(
        self,
        agent_id: UUID | str,
    ) -> AsyncLiveSession:
        """Create a new conversation session with an agent."""
        resolved_id: UUID
        agent_name: Optional[str] = None

        try:
            resolved_id = UUID(str(agent_id))
        except ValueError:
            agent = await self.get_by_name(str(agent_id))
            if not agent:
                from workstudio.exceptions import NotFoundError
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
        agent_id: UUID | str,
        message: str,
        include_debug: bool = False,
    ) -> MessageResponse:
        """Send a single message to an agent (one-shot, no session)."""
        async with await self.create_session(agent_id) as session:
            return await session.send_message(message, include_debug=include_debug)

"""
Main client for the work.studio SDK.
"""

import os
from typing import Any, Optional

import httpx

from workstudio._http import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, AsyncHTTPClient, HTTPClient
from workstudio.agents import AgentsClient, AsyncAgentsClient
from workstudio.workflows import AsyncWorkflowsClient, WorkflowsClient


class Client:
    """
    Synchronous client for the work.studio API.

    Example:
        from workstudio import Client

        # Using API key directly
        client = Client(api_key="svx_ck_prod_...")

        # Using environment variable (WORKSTUDIO_API_KEY)
        client = Client()

        # List workflows
        workflows, _ = client.workflows.list()

        # Run a workflow and wait for its result
        run = client.workflows.run("invoice-processor", {"file_url": "..."})
        print(run.output)

        # Chat with an agent
        response = client.agents.chat("sales-assistant", "What are our top deals?")

        # Multi-turn conversation
        with client.agents.create_session("sales-assistant") as session:
            r1 = session.send_message("What are our top deals?")
            r2 = session.send_message("Tell me more about the first one")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        scope_id: Optional[str] = None,
        *,
        scope_key: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        """
        Initialize the client.

        Args:
            api_key: Your work.studio API key (svx_ck_... or svx_tk_...).
                     If not provided, reads from WORKSTUDIO_API_KEY env var.
            base_url: API base URL. Defaults to https://api.work.studio.
                     Can also be set via WORKSTUDIO_BASE_URL env var.
            timeout: Request timeout in seconds (default: 30)
            scope_id: The customer a TENANT key acts for, e.g. ``"customer:acme"`` (sent as
                     ``X-SCOPE-KEY``). Not needed with a CUSTOMER key, which is bound to its
                     customer. Can also be set via WORKSTUDIO_SCOPE_ID env var.
            scope_key: Same as ``scope_id`` (the name the API uses).
            transport: An ``httpx`` transport - for tests (``httpx.MockTransport``) or proxies.

        Raises:
            ValueError: If no API key is provided or found in environment
        """
        # Resolve API key
        resolved_api_key = api_key or os.environ.get("WORKSTUDIO_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "API key required. Pass api_key argument or set WORKSTUDIO_API_KEY "
                "environment variable."
            )

        # Resolve base URL
        resolved_base_url = base_url or os.environ.get("WORKSTUDIO_BASE_URL", DEFAULT_BASE_URL)

        # Resolve scope
        resolved_scope = scope_key or scope_id or os.environ.get("WORKSTUDIO_SCOPE_ID")

        # Create HTTP client
        self._http = HTTPClient(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=timeout,
            scope_id=resolved_scope,
            transport=transport,
        )

        # Initialize API clients
        self._workflows = WorkflowsClient(self._http)
        self._agents = AgentsClient(self._http)

    @property
    def workflows(self) -> WorkflowsClient:
        """Access workflow operations."""
        return self._workflows

    @property
    def agents(self) -> AgentsClient:
        """Access agent operations."""
        return self._agents

    def close(self) -> None:
        """Close the client and release resources."""
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncClient:
    """
    Asynchronous client for the work.studio API.

    Example:
        from workstudio import AsyncClient
        import asyncio

        async def main():
            async with AsyncClient(api_key="svx_ck_prod_...") as client:
                # List workflows
                workflows, _ = await client.workflows.list()

                # Run a workflow and wait for its result
                run = await client.workflows.run("invoice-processor")

                # Chat with an agent
                response = await client.agents.chat("sales-assistant", "Hello!")

        asyncio.run(main())
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        scope_id: Optional[str] = None,
        *,
        scope_key: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        """
        Initialize the async client.

        Args:
            api_key: Your work.studio API key.
                     If not provided, reads from WORKSTUDIO_API_KEY env var.
            base_url: API base URL. Defaults to https://api.work.studio.
            timeout: Request timeout in seconds (default: 30)
            scope_id: The customer a TENANT key acts for (``X-SCOPE-KEY``).
            scope_key: Same as ``scope_id``.
            transport: An ``httpx`` async transport, for tests or proxies.
        """
        resolved_api_key = api_key or os.environ.get("WORKSTUDIO_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "API key required. Pass api_key argument or set WORKSTUDIO_API_KEY "
                "environment variable."
            )

        resolved_base_url = base_url or os.environ.get("WORKSTUDIO_BASE_URL", DEFAULT_BASE_URL)
        resolved_scope = scope_key or scope_id or os.environ.get("WORKSTUDIO_SCOPE_ID")

        self._http = AsyncHTTPClient(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=timeout,
            scope_id=resolved_scope,
            transport=transport,
        )

        self._workflows = AsyncWorkflowsClient(self._http)
        self._agents = AsyncAgentsClient(self._http)

    @property
    def workflows(self) -> AsyncWorkflowsClient:
        """Access workflow operations."""
        return self._workflows

    @property
    def agents(self) -> AsyncAgentsClient:
        """Access agent operations."""
        return self._agents

    async def close(self) -> None:
        """Close the client and release resources."""
        await self._http.close()

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

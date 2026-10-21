"""
workstudio - Python SDK for work.studio

The work.studio SDK provides a simple interface for interacting with
workflows, AI agents, and automation pipelines.

Basic usage:

    from workstudio import Client

    # Initialize with API key
    client = Client(api_key="svx_ck_prod_...")

    # List workflows
    workflows = client.workflows.list()

    # Run a workflow and wait for its result
    run = client.workflows.run("my-workflow", inputs={"key": "value"})
    print(run.status, run.output)

    # Or start it, and follow it yourself
    run = client.workflows.start("my-workflow", inputs={"key": "value"})
    run = client.workflows.wait(run.id)

    # Chat with an agent
    session = client.agents.create_session("sales-assistant")
    response = session.send_message("What are our top deals?")

For async usage:

    from workstudio import AsyncClient

    async def main():
        async with AsyncClient(api_key="...") as client:
            result = await client.workflows.run("my-workflow")

"""

from workstudio._version import __version__
from workstudio.client import AsyncClient, Client
from workstudio.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    RunFailedError,
    RunTimeoutError,
    ValidationError,
    WorkStudioError,
)
from workstudio.models import (
    Agent,
    AgentSession,
    KnowledgeBaseHit,
    MessageMetrics,
    MessageResponse,
    RunStatus,
    ToolExecution,
    Workflow,
    WorkflowRun,
)

__all__ = [
    # Clients
    "Client",
    "AsyncClient",
    # Models
    "Workflow",
    "WorkflowRun",
    "RunStatus",
    "Agent",
    "AgentSession",
    "MessageResponse",
    "MessageMetrics",
    "ToolExecution",
    "KnowledgeBaseHit",
    # Exceptions
    "WorkStudioError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "APIError",
    "RunFailedError",
    "RunTimeoutError",
    "__version__",
]

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

    # Run a workflow
    result = client.workflows.run("my-workflow", inputs={"key": "value"})

    # Chat with an agent
    session = client.agents.create_session("sales-assistant")
    response = session.send_message("What are our top deals?")

For async usage:

    from workstudio import AsyncClient

    async def main():
        async with AsyncClient(api_key="...") as client:
            result = await client.workflows.run("my-workflow")

"""

from workstudio.client import Client, AsyncClient
from workstudio.models import (
    Workflow,
    WorkflowRun,
    RunStatus,
    Agent,
    AgentSession,
    MessageResponse,
    MessageMetrics,
    ToolExecution,
    KnowledgeBaseHit,
)
from workstudio.exceptions import (
    WorkStudioError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    APIError,
)

__version__ = "0.1.0"
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
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "APIError",
]

"""
Example: Async usage with FastAPI.

This example shows how to use the async client in a FastAPI application.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from workstudio import AsyncClient, RunFailedError, RunTimeoutError
from workstudio.exceptions import NotFoundError, WorkStudioError


# Global client (initialized at startup)
client: Optional[AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup the work.studio client."""
    global client
    client = AsyncClient()  # Uses WORKSTUDIO_API_KEY env var
    yield
    if client:
        await client.close()


app = FastAPI(
    title="work.studio Integration Example",
    lifespan=lifespan,
)


# Request/Response models
class WorkflowRunRequest(BaseModel):
    workflow: str  # Name or ID
    inputs: dict[str, Any] = {}


class ChatRequest(BaseModel):
    agent: str  # Name or ID
    message: str


class ChatResponse(BaseModel):
    message: str
    tokens: int
    cost_usd: float


# Endpoints
@app.get("/workflows")
async def list_workflows():
    """List all available workflows."""
    workflows, page_info = await client.workflows.list()
    return {
        "workflows": [
            {"id": str(wf.id), "name": wf.name, "endpoint": wf.endpoint}
            for wf in workflows
        ],
        "total": page_info.total_elements,
    }


@app.post("/workflows/run")
async def run_workflow(request: WorkflowRunRequest):
    """Run a workflow and return results."""
    try:
        result = await client.workflows.run(
            request.workflow,
            inputs=request.inputs,
            timeout=60,
        )
        return {
            "run_id": str(result.id),
            "status": result.status_name,
            "output": result.output,
            "duration_ms": result.duration_ms,
        }
    except RunFailedError as e:
        raise HTTPException(status_code=502, detail=f"Run ended {e.run.status_name}: {e.run.error}")
    except RunTimeoutError as e:
        raise HTTPException(status_code=504, detail=f"Run {e.run.id} still {e.run.status_name}")
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow '{request.workflow}' not found")
    except WorkStudioError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agents")
async def list_agents():
    """List all published agents."""
    agents, _ = await client.agents.list(status="PUBLISHED")
    return {
        "agents": [
            {"id": str(a.id), "name": a.name, "description": a.description}
            for a in agents
        ]
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message to an agent."""
    try:
        response = await client.agents.chat(
            request.agent,
            request.message,
        )
        return ChatResponse(
            message=response.message or "",
            tokens=response.total_tokens,
            cost_usd=response.estimated_cost_usd,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{request.agent}' not found")
    except WorkStudioError as e:
        raise HTTPException(status_code=500, detail=str(e))


# Run with: uvicorn fastapi_integration:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

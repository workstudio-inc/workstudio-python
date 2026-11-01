# workstudio

Python SDK for [work.studio](https://work.studio) - AI-powered workflow automation platform.

## Installation

```bash
pip install workstudio
```

## Quick Start

```python
from workstudio import Client

# Initialize with API key
client = Client(api_key="svx_ck_prod_...")

# Or use environment variable
# export WORKSTUDIO_API_KEY=svx_ck_prod_...
client = Client()
```

## Workflows

### List workflows

Listing and reading workflow definitions needs an organization key (`svx_tk_...`) with
**View Automation** or **Run Automation**; a customer key (`svx_ck_...`) gets 403. With **Run
Automation** only, each workflow comes back as a summary (id, global id, name, endpoint, inputs).

```python
workflows, page_info = client.workflows.list()
for wf in workflows:
    print(f"{wf.name}: {wf.id}")

# With pagination
workflows, page_info = client.workflows.list(page=0, size=10)
print(f"Total: {page_info.total_elements}")
```

### Run a workflow

`run()` starts the workflow's published version with `POST /api/v1/workflow/execute/{endpoint}`
(or `/execute/id/{global-id}`) and waits for it with `POST /run/{id}/wait`. Any key with **Run
Automation** may run workflows, a customer key included (it always runs for its own customer).

```python
# By endpoint name
result = client.workflows.run(
    "invoice-processor",
    inputs={"file_url": "https://example.com/invoice.pdf"}
)

# By the workflow's global unique id (Designer shows it under API). With an organization key,
# the id from workflows.list() / workflows.get() works too.
result = client.workflows.run(
    "550e8400-e29b-41d4-a716-446655440000",
    inputs={"file_url": "https://example.com/invoice.pdf"}
)

# Check result
print(f"Status: {result.status} ({result.raw_status})")  # RunStatus.COMPLETED (FINISHED)
print(f"Outputs: {result.outputs}")
print(f"Full result: {result.final_output_url}")  # short-lived link, fetch without your key
```

`status` is a `RunStatus`. The platform's statuses map onto it: `FINISHED` is `COMPLETED`,
`WAITING_HUMAN` is `WAITING`, `QUEUED` and `PARSING` are `PENDING`, `TERMINATED` is `CANCELLED`;
`raw_status` keeps the platform's word. A run still going after `timeout_seconds` (default 300) is
returned as it stands.

### Async workflow execution

```python
# Start workflow without waiting
run = client.workflows.run("invoice-processor", sync=False)
print(f"Started run: {run.id}")

# Poll for status later
run = client.workflows.get_run(run.id)
print(f"Status: {run.status}")

# Correlate with your own id
run = client.workflows.run("invoice-processor", sync=False, external_id="po-1234")
run = client.workflows.get_run_by_external_id("po-1234")  # None if there is no such run

# Recent runs
runs, page_info = client.workflows.list_runs(size=10)
```

A key with only **Run Automation** reads the runs it started.

## Agents

Agents need an organization key: listing and reading them needs `catalog:read`, sessions need
`agent:execute`. A customer key cannot look agents up by name.

### List agents

```python
agents, _ = client.agents.list(active=True)
for agent in agents:
    print(f"{agent.name}: {agent.description}")
```

### Simple chat (one-shot)

```python
response = client.agents.chat(
    "sales-assistant",
    "What are our top 3 deals this quarter?"
)
print(response.message)
print(f"Tokens used: {response.total_tokens}")
print(f"Cost: ${response.estimated_cost_usd:.4f}")
```

### Multi-turn conversation

```python
# Create a session for multi-turn conversation
with client.agents.create_session("sales-assistant") as session:
    # First message
    r1 = session.send_message("What are our top deals?")
    print(f"Assistant: {r1.message}")
    
    # Follow-up (maintains context)
    r2 = session.send_message("Tell me more about the first one")
    print(f"Assistant: {r2.message}")
    
    # Check session metrics
    state = session.get_state()
    print(f"Total tokens: {state.total_tokens}")
```

## Async Usage

For async applications (FastAPI, etc.):

```python
from workstudio import AsyncClient
import asyncio

async def main():
    async with AsyncClient(api_key="svx_ck_prod_...") as client:
        # Workflows
        workflows, _ = await client.workflows.list()
        result = await client.workflows.run("invoice-processor")
        
        # Agents
        async with await client.agents.create_session("assistant") as session:
            response = await session.send_message("Hello!")
            print(response.message)

asyncio.run(main())
```

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `WORKSTUDIO_API_KEY` | Your API key (required if not passed to Client) |
| `WORKSTUDIO_BASE_URL` | API base URL (default: https://api.work.studio) |
| `WORKSTUDIO_SCOPE_ID` | Default scope for customer-scoped operations |

### Custom Configuration

```python
client = Client(
    api_key="svx_ck_prod_...",
    base_url="https://custom.api.endpoint",
    timeout=60.0,  # Request timeout in seconds
    scope_id="my-scope-id",  # For customer API keys
)
```

## Error Handling

```python
from workstudio import Client
from workstudio.exceptions import (
    AuthenticationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    APIError,
)

client = Client()

try:
    result = client.workflows.run("my-workflow")
except AuthenticationError:
    print("Invalid API key")
except NotFoundError:
    print("Workflow not found")
except ValidationError as e:
    print(f"Invalid input: {e.errors}")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after} seconds")
except APIError as e:
    print(f"API error: {e.message} (status: {e.status_code})")
```

A failed agent turn raises `AgentTurnError`. The platform answers it with a 2xx and
`status: ERROR` in the body, so the SDK reads the body: `error_code` is the platform's code
(`AGENT_TURNED_OFF`, `BUDGET_EXCEEDED`, ...) when the reply has one, and `response` is the parsed
reply.

```python
from workstudio import AgentTurnError

try:
    reply = session.send_message("What are our top deals?")
except AgentTurnError as e:
    print(f"Turn failed: {e.message} (code: {e.error_code})")
```

## API Key Types

| Type | Format | Use Case |
|------|--------|----------|
| Customer Key | `svx_ck_...` | Runs workflows for one customer; cannot read definitions or agents |
| Tenant Key | `svx_tk_...` | Backend services: runs, definitions, agents (per its permissions) |

Get your API key from the [Designer](https://designer.work.studio) → API Keys page.

## Development

```bash
# Clone and install dev dependencies
git clone https://github.com/workstudio-inc/workstudio-python
cd workstudio-python
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy workstudio

# Linting
ruff check workstudio
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Links

- [Documentation](https://docs.work.studio/sdk/python)
- [API Reference](https://docs.work.studio/api)
- [work.studio](https://work.studio)

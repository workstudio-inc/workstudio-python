# workstudio

Python SDK for [work.studio](https://work.studio) - AI-powered workflow automation platform.

## Installation

```bash
pip install workstudio
```

## Quick Start

```python
from workstudio import Client

# Initialize with an API key
client = Client(api_key="svx_ck_prod_...")

run = client.workflows.run("invoice-processor", {"file_url": "https://example.com/a.pdf"})
print(run.output)

# Or use environment variable
# export WORKSTUDIO_API_KEY=svx_ck_prod_...
client = Client()
```

## Running automations from code

### Run and wait for the result

```python
run = client.workflows.run(
    "550e8400-e29b-41d4-a716-446655440000",   # the workflow's global id (Designer -> API)
    inputs={"file_url": "https://example.com/invoice.pdf"},
)
print(run.status)   # RunStatus.FINISHED
print(run.output)   # the workflow's result, decoded
```

You can also name the workflow by its endpoint slug: `client.workflows.run("invoice-processor", ...)`.

`run()` starts the run, waits until it ends (long-polling, so it does not hammer the API), then
downloads and decodes the result. If the run ends `FAILED`, `CANCELLED` or `TERMINATED` it raises
`RunFailedError` (`err.run.error` says why); pass `raise_on_failure=False` to get the run back
instead. If it has not ended within `timeout` seconds (default 300) it raises `RunTimeoutError` -
the run keeps going, and `err.run` is its last state.

### Start now, follow later

```python
run = client.workflows.start("invoice-processor", {"file_url": "..."})
print(run.id)                      # store it; the run carries on without you

run = client.workflows.wait(run.id, timeout=600)
if run.succeeded:
    print(client.workflows.get_output(run))
```

`get_run(run_id)` reads a run's current state without waiting, and
`wait(run_id, return_on_waiting=True)` returns as soon as a run pauses (for an approval, say), so
you can act on `run.wait_info`.

### Run statuses

These are the platform's own values:

| Status | Meaning |
|--------|---------|
| `QUEUED`, `PARSING`, `PENDING`, `RUNNING` | in progress |
| `WAITING_HUMAN` | paused - an approval, an agent, a sub-workflow; `run.wait_info` says which |
| `FINISHED` | ended successfully (`run.succeeded`) |
| `FAILED`, `CANCELLED`, `TERMINATED` | ended without succeeding |

`run.is_terminal` is true for the last two rows. A status this SDK does not know yet is kept as a
plain string rather than rejected.

### The result

A run's result is not inline: the platform stores it and the run carries a short-lived link to it
(`run.final_output_url`, 30 minutes by default). `get_output(run)` downloads it - without your API
key, which never leaves the API host - decodes it (the stored JSON often holds a JSON document as a
string), and asks for a fresh link if the old one has expired.

### For one of your customers

A **customer key** (`svx_ck_...`) is bound to one customer: every run it starts is that customer's,
and it can read that customer's runs and no one else's. Its default permission, *Execute
Workflows*, is all start-then-poll needs.

A **tenant key** (`svx_tk_...`) names the customer per call:

```python
run = client.workflows.run("invoice-processor", inputs, scope_key="customer:acme")
```

or once for the client: `Client(scope_key="customer:acme")`.

### Other run operations

```python
client.workflows.cancel(run.id, reason="duplicate order")
runs, page = client.workflows.list_runs(status="FAILED", scope_key="customer:acme")
run = client.workflows.get_run_by_external_id("order-1234")   # start(..., external_id="order-1234")
```

### What a key may do

| Key holds | Start runs | Read runs |
|-----------|-----------|-----------|
| *Execute Workflows* (`workflow:execute`) | yes | the runs it started (a customer key: its customer's runs) |
| *Read Runs* (`run:read`) or *Read Workflows* (`workflow:read`) | no | every run in the tenant (a customer key: still only its customer's) |

`client.workflows.list()` / `get()` read workflow **definitions**; give the key *Read Workflows* for those.

## Workflow definitions

```python
workflows, page_info = client.workflows.list()
for wf in workflows:
    print(f"{wf.name}: {wf.id}")
```

## Agents

### List agents

```python
agents, _ = client.agents.list(status="PUBLISHED")
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
        run = await client.workflows.run("invoice-processor", {"file_url": "..."})
        print(run.output)
        
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
| `WORKSTUDIO_SCOPE_ID` | Customer a TENANT key acts for, e.g. `customer:acme` (sent as `X-SCOPE-KEY`) |

### Custom Configuration

```python
client = Client(
    api_key="svx_ck_prod_...",
    base_url="https://custom.api.endpoint",
    timeout=60.0,  # Request timeout in seconds
    scope_key="customer:acme",  # TENANT keys: the customer to act for
)
```

## Error Handling

```python
from workstudio import Client
from workstudio.exceptions import (
    AuthenticationError,     # 401: the key is missing, wrong or expired
    PermissionDeniedError,   # 403: the key is valid but may not do this (subclass of the above)
    NotFoundError,
    ValidationError,
    RateLimitError,
    RunFailedError,          # the run ended FAILED / CANCELLED / TERMINATED
    RunTimeoutError,         # the run had not ended in time; it carries on
    APIError,
)

client = Client()

try:
    run = client.workflows.run("my-workflow", {"x": 1}, timeout=120)
except RunFailedError as e:
    print(f"Run {e.run.id} ended {e.run.status_name}: {e.run.error}")
except RunTimeoutError as e:
    print(f"Still {e.run.status_name}; pick it up later with wait({e.run.id!r})")
except PermissionDeniedError as e:
    print(f"Not allowed: {e.message}")
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

## API Key Types

| Type | Format | Use Case |
|------|--------|----------|
| Customer Key | `svx_ck_...` | Handed to or used for one customer: runs as that customer, reads only that customer's runs |
| Tenant Key | `svx_tk_...` | Your backend: acts for any customer (`scope_key=`), with the permissions you give it |

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

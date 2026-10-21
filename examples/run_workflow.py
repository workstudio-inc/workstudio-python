"""
Example: run a workflow from code and use its result.

This example shows how to:
1. Run a workflow and wait for its result
2. Start a run now and follow it later
3. Handle a run that fails or takes too long
"""

from workstudio import Client, RunFailedError, RunTimeoutError
from workstudio.exceptions import NotFoundError, ValidationError

# You can pass api_key directly or set WORKSTUDIO_API_KEY.
client = Client(api_key="your-api-key-here")

# 1. Run and wait. The workflow is named by its endpoint slug here; its global id (a UUID) works too.
print("=== Running Invoice Processor ===")
try:
    run = client.workflows.run(
        "invoice-processor",
        inputs={"file_url": "https://example.com/invoice.pdf", "extract_line_items": True},
        timeout=120,
    )
    print(f"Run {run.id}: {run.status_name} in {run.duration_ms}ms")
    print(f"Result: {run.output}")
except RunFailedError as e:
    print(f"The run ended {e.run.status_name}: {e.run.error}")
except RunTimeoutError as e:
    print(f"Still {e.run.status_name} after {e.waited_seconds:.0f}s - it carries on")
except NotFoundError:
    print("Workflow 'invoice-processor' not found")
except ValidationError as e:
    print(f"Invalid inputs: {e.errors}")

# 2. Start now, follow later - e.g. from a job queue.
print("\n=== Start now, follow later ===")
run = client.workflows.start("long-running-job", inputs={"data": "example"}, external_id="job-42")
print(f"Started run {run.id} ({run.status_name})")

run = client.workflows.wait(run.id, timeout=600)
print(f"Final status: {run.status_name}")
if run.succeeded:
    print(f"Result: {client.workflows.get_output(run)}")

client.close()

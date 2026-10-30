"""
Example: Run a workflow and process the results.

This example shows how to:
1. Connect to work.studio
2. Run a workflow with inputs
3. Handle the results
"""

from workstudio import Client
from workstudio.exceptions import NotFoundError, ValidationError

# Initialize client
# You can pass api_key directly or set WORKSTUDIO_API_KEY env var
client = Client(api_key="your-api-key-here")

# Example 1: Simple workflow run
print("=== Running Invoice Processor ===")
try:
    result = client.workflows.run(
        "invoice-processor",  # workflow endpoint name
        inputs={
            "file_url": "https://example.com/invoice.pdf",
            "extract_line_items": True,
        }
    )
    
    print(f"Run ID: {result.id}")
    print(f"Status: {result.status}")
    print(f"Duration: {result.duration_ms}ms")
    
    if result.outputs:
        print(f"Extracted data: {result.outputs}")
        
except NotFoundError:
    print("Workflow 'invoice-processor' not found")
except ValidationError as e:
    print(f"Invalid inputs: {e.errors}")

# Example 2: List all workflows
print("\n=== Available Workflows ===")
workflows, page_info = client.workflows.list()
for wf in workflows:
    print(f"  - {wf.name} ({wf.endpoint})")
print(f"Total: {page_info.total_elements} workflows")

# Example 3: Run workflow asynchronously and poll
print("\n=== Async Workflow Run ===")
run = client.workflows.run(
    "long-running-job",
    inputs={"data": "example"},
    sync=False,  # Don't wait for completion
)
print(f"Started run: {run.id}")
print(f"Initial status: {run.status}")

# Poll for completion
import time
while not run.is_terminal:
    time.sleep(2)
    run = client.workflows.get_run(run.id)
    print(f"Status: {run.raw_status}")

print(f"Final status: {run.raw_status}")
# A polled run carries a link to its result rather than the result itself.
if run.final_output_url:
    print(f"Result: {run.final_output_url}")

client.close()

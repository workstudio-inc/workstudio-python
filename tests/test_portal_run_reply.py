"""workflows.run() reads the portal's run reply.

PUT /portal/{id}/run (and /run/async) answers {runStatus, executionResult}, not a run with id, workflowId and status at
the top, so WorkflowRun.model_validate raised a ValidationError on every successful run. The run service's own words
for a state (FINISHED, WAITING_HUMAN, ...) did not parse either.
"""

import json

import pytest

from workstudio.models import RunStatus, WorkflowRun

BASE = "http://ws.test"
WORKFLOW_ID = "01a16fed-7209-75b1-beb4-1d90a10df4be"
RUN_ID = "01a16fee-f9a9-762a-adc9-e6d520090242"


def portal_reply(status: str = "FINISHED", error=None) -> dict:
    """The shape portal returns (WorkflowRouterRunStatusWithResultDto), as seen from PUT /portal/{id}/run."""
    state = {
        "currentState": status,
        "workflowId": WORKFLOW_ID,
        "workflowName": "Order intake",
        "startTime": "2026-10-24T22:01:35.001Z",
        "endTime": "2026-10-24T22:01:35.036Z",
        "response": {"got": {"order": 13}},
        "runId": RUN_ID,
        "error": None,
    }
    return {
        "id": None,
        "tenantId": None,
        "runStatus": {"id": None, "routeRun": RUN_ID, "error": error, "value": json.dumps(state), "status": status},
        "executionResult": {
            "runId": RUN_ID,
            "workflowId": WORKFLOW_ID,
            "runtimeState": {},
            "finalOutputUrl": "https://files.test/final-output.json",
            "runtimeStateUrl": "https://files.test/runtime-state.json",
            "stepOutputUrls": {},
        },
    }


class TestParse:
    def test_portal_reply_becomes_a_run(self):
        run = WorkflowRun.from_api(portal_reply())
        assert str(run.id) == RUN_ID
        assert str(run.workflow_id) == WORKFLOW_ID
        assert run.workflow_name == "Order intake"
        assert run.status == RunStatus.COMPLETED
        assert run.outputs == {"got": {"order": 13}}
        assert run.final_output_url == "https://files.test/final-output.json"
        assert run.started_at is not None and run.completed_at is not None

    def test_a_failed_run_carries_its_error(self):
        run = WorkflowRun.from_api(portal_reply("FAILED", error="Step f: boom"))
        assert run.status == RunStatus.FAILED
        assert run.error == "Step f: boom"

    def test_a_still_running_reply_without_state(self):
        reply = {"runStatus": {"routeRun": RUN_ID, "status": "RUNNING"},
                 "executionResult": {"runId": RUN_ID, "workflowId": WORKFLOW_ID}}
        run = WorkflowRun.from_api(reply)
        assert run.status == RunStatus.RUNNING
        assert run.outputs is None

    @pytest.mark.parametrize("raw,expected", [
        ("FINISHED", RunStatus.COMPLETED),
        ("WAITING_HUMAN", RunStatus.WAITING),
        ("QUEUED", RunStatus.PENDING),
        ("TERMINATED", RunStatus.CANCELLED),
        ("COMPLETED", RunStatus.COMPLETED),
        ("finished", RunStatus.COMPLETED),
    ])
    def test_the_run_services_statuses(self, raw, expected):
        assert RunStatus(raw) == expected

    def test_a_run_service_run_still_parses(self):
        run = WorkflowRun.from_api({"id": RUN_ID, "workflowId": WORKFLOW_ID, "status": "FINISHED",
                                    "finalOutputUrl": "https://files.test/o.json"})
        assert run.status == RunStatus.COMPLETED
        assert run.final_output_url == "https://files.test/o.json"

"""Tests for running a workflow by id or by endpoint name (mocked HTTP; no real server)."""

import json
from uuid import uuid4

import pytest

from workstudio import AsyncClient, Client
from workstudio.exceptions import NotFoundError
from workstudio.models import RunStatus, WorkflowRun

BASE_URL = "http://sdk.test"
PORTAL = f"{BASE_URL}/api/v1/workflow/portal"


def _workflow(workflow_id, endpoint="invoice-processor"):
    return {"id": str(workflow_id), "name": "Invoice processor", "endpoint": endpoint}


def _run(workflow_id, status="COMPLETED"):
    return {
        "id": str(uuid4()),
        "workflowId": str(workflow_id),
        "status": status,
        "outputs": {"ok": True},
    }


@pytest.fixture
def client():
    c = Client(api_key="test-key", base_url=BASE_URL)
    yield c
    c.close()


class TestRunByName:
    def test_run_by_name_resolves_then_runs_by_id(self, client, httpx_mock):
        wf_id = uuid4()
        httpx_mock.add_response(
            method="GET", url=f"{PORTAL}/by-endpoint/invoice-processor", json=_workflow(wf_id)
        )
        httpx_mock.add_response(method="PUT", url=f"{PORTAL}/{wf_id}/run", json=_run(wf_id))

        run = client.workflows.run("invoice-processor", {"file_url": "s3://x"})

        assert isinstance(run, WorkflowRun)
        assert run.workflow_id == wf_id
        assert run.status == RunStatus.COMPLETED
        requests = httpx_mock.get_requests()
        assert [(r.method, str(r.url)) for r in requests] == [
            ("GET", f"{PORTAL}/by-endpoint/invoice-processor"),
            ("PUT", f"{PORTAL}/{wf_id}/run"),
        ]
        assert json.loads(requests[1].content) == {"file_url": "s3://x"}
        # The route that does not exist is never called.
        assert not any(str(r.url).endswith("/by-endpoint/invoice-processor/run") for r in requests)

    def test_run_by_unknown_name_raises_not_found(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{PORTAL}/by-endpoint/no-such-flow",
            status_code=404,
            json={"message": "Workflow not found"},
        )

        with pytest.raises(NotFoundError) as exc:
            client.workflows.run("no-such-flow")

        assert exc.value.status_code == 404
        assert "no-such-flow" in exc.value.message
        assert len(httpx_mock.get_requests()) == 1  # no run attempted

    def test_run_by_id_does_not_resolve(self, client, httpx_mock):
        wf_id = uuid4()
        httpx_mock.add_response(method="PUT", url=f"{PORTAL}/{wf_id}/run", json=_run(wf_id))

        run = client.workflows.run(wf_id)
        assert run.workflow_id == wf_id

        requests = httpx_mock.get_requests()
        assert [(r.method, str(r.url)) for r in requests] == [("PUT", f"{PORTAL}/{wf_id}/run")]
        assert json.loads(requests[0].content) == {}

    def test_run_by_id_string_does_not_resolve(self, client, httpx_mock):
        wf_id = uuid4()
        httpx_mock.add_response(method="PUT", url=f"{PORTAL}/{wf_id}/run", json=_run(wf_id))

        client.workflows.run(str(wf_id), {"a": 1})

        requests = httpx_mock.get_requests()
        assert [r.method for r in requests] == ["PUT"]
        assert json.loads(requests[0].content) == {"a": 1}

    def test_run_by_name_async_mode_returns_without_polling(self, client, httpx_mock):
        wf_id = uuid4()
        httpx_mock.add_response(
            method="GET", url=f"{PORTAL}/by-endpoint/invoice-processor", json=_workflow(wf_id)
        )
        httpx_mock.add_response(
            method="PUT", url=f"{PORTAL}/{wf_id}/run", json=_run(wf_id, status="RUNNING")
        )

        run = client.workflows.run("invoice-processor", sync=False)

        assert run.status == RunStatus.RUNNING
        assert len(httpx_mock.get_requests()) == 2


class TestAsyncRunByName:
    async def test_run_by_name_resolves_then_runs_by_id(self, httpx_mock):
        wf_id = uuid4()
        httpx_mock.add_response(
            method="GET", url=f"{PORTAL}/by-endpoint/invoice-processor", json=_workflow(wf_id)
        )
        httpx_mock.add_response(method="PUT", url=f"{PORTAL}/{wf_id}/run", json=_run(wf_id))

        async with AsyncClient(api_key="test-key", base_url=BASE_URL) as client:
            run = await client.workflows.run("invoice-processor", {"file_url": "s3://x"})

        assert run.workflow_id == wf_id
        requests = httpx_mock.get_requests()
        assert [(r.method, str(r.url)) for r in requests] == [
            ("GET", f"{PORTAL}/by-endpoint/invoice-processor"),
            ("PUT", f"{PORTAL}/{wf_id}/run"),
        ]
        assert json.loads(requests[1].content) == {"file_url": "s3://x"}

    async def test_run_by_unknown_name_raises_not_found(self, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{PORTAL}/by-endpoint/no-such-flow",
            status_code=404,
            json={"message": "Workflow not found"},
        )

        async with AsyncClient(api_key="test-key", base_url=BASE_URL) as client:
            with pytest.raises(NotFoundError) as exc:
                await client.workflows.run("no-such-flow")

        assert exc.value.status_code == 404
        assert "no-such-flow" in exc.value.message
        assert len(httpx_mock.get_requests()) == 1

    async def test_run_by_id_does_not_resolve(self, httpx_mock):
        wf_id = uuid4()
        httpx_mock.add_response(method="PUT", url=f"{PORTAL}/{wf_id}/run", json=_run(wf_id))

        async with AsyncClient(api_key="test-key", base_url=BASE_URL) as client:
            await client.workflows.run(wf_id)

        assert [r.method for r in httpx_mock.get_requests()] == ["PUT"]

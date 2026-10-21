"""
Running a workflow from code, against a mocked platform.

The responses below are the platform's real shapes: the ``/execute`` answer carries the run id in
``executionResult.runId``, ``/run/{id}`` answers with the run service's DTO (statuses ``FINISHED``,
``WAITING_HUMAN`` ...; timestamps with a ``+0000`` offset), ``/run/{id}/wait`` answers 408 while the
run is going, and a finished run's result sits behind a presigned ``finalOutputUrl`` on another
host, as JSON encoded twice.
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Callable
from uuid import uuid4

import httpx
import pytest

from workstudio import (
    AsyncClient,
    AuthenticationError,
    Client,
    PermissionDeniedError,
    RunFailedError,
    RunStatus,
    RunTimeoutError,
    WorkflowRun,
)
from workstudio._runs import decode_output
from workstudio.exceptions import APIError

BASE = "https://api.test"
S3 = "https://bucket.s3.test"
KEY = "svx_ck_test_abc"

WORKFLOW_ID = str(uuid4())
RUN_ID = str(uuid4())
OUTPUT_REF = f"s3://bucket/runs/{RUN_ID}/final-output.json"


def run_dto(status: str, **extra: Any) -> dict[str, Any]:
    """A run as GET /api/v1/workflow/run/{id} returns it."""
    body: dict[str, Any] = {
        "id": RUN_ID,
        "tenantId": str(uuid4()),
        "envId": str(uuid4()),
        "workflowId": str(uuid4()),
        "workflowGlobalUniqueId": WORKFLOW_ID,
        "workflowName": "Invoice processor",
        "inputData": '{"file_url":"https://example.com/a.pdf"}',
        "triggerType": "SYSTEM",
        "status": status,
        "startedAt": "2026-10-21T15:04:05.123+0000",
        "syncMode": False,
        "debugMode": False,
        "steps": [],
        "scopeKey": "customer:acme",
        "createdAt": "2026-10-21T15:04:05.001Z",
        "someFieldAddedLater": {"ignored": True},
    }
    body.update(extra)
    return body


def started(status: str = "QUEUED") -> dict[str, Any]:
    """The /execute answer for ?async=true."""
    return {
        "runStatus": {"routeRun": RUN_ID, "status": status},
        "executionResult": {"runId": RUN_ID, "workflowId": str(uuid4()), "debugMode": False},
    }


DOUBLE_ENCODED = json.dumps(json.dumps({"total": 42, "lines": [1, 2]}))


class FakePlatform:
    """Routes requests to handlers by (method, path) and records them."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, *responses: Any) -> None:
        queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            if callable(item):
                return item(request)
            status, body = item
            if isinstance(body, (dict, list)):
                return httpx.Response(status, json=body)
            return httpx.Response(status, content=(body or "").encode())

        self.routes[(method, path)] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, f"{request.url.scheme}://{request.url.host}{request.url.path}")
        if key in self.routes:
            return self.routes[key](request)
        return httpx.Response(404, json={"message": f"no route {key}"})

    def calls(self, method: str, path_suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path.endswith(path_suffix)]


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform()


@pytest.fixture
def client(platform: FakePlatform) -> Client:
    c = Client(api_key=KEY, base_url=BASE, transport=httpx.MockTransport(platform))
    yield c
    c.close()


EXEC_ID = f"{BASE}/api/v1/workflow/execute/id/{WORKFLOW_ID}"
RUN = f"{BASE}/api/v1/workflow/run/{RUN_ID}"


class TestStart:
    def test_by_global_id_uses_the_execute_route(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, started()))

        run = client.workflows.start(WORKFLOW_ID, {"file_url": "x"})

        assert str(run.id) == RUN_ID
        assert run.status is RunStatus.QUEUED
        request = platform.requests[0]
        assert request.url.params["async"] == "true"
        assert request.headers["X-API-Key"] == KEY
        assert json.loads(request.content) == {"file_url": "x"}

    def test_by_slug(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", f"{BASE}/api/v1/workflow/execute/invoice-processor", (200, started()))

        run = client.workflows.start("invoice-processor")

        assert str(run.id) == RUN_ID

    def test_scope_key_and_external_id(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, started()))

        client.workflows.start(WORKFLOW_ID, {"a": 1}, scope_key="customer:acme", external_id="ord-1")

        request = platform.requests[0]
        assert request.headers["X-SCOPE-KEY"] == "customer:acme"
        assert json.loads(request.content) == {"a": 1, "externalId": "ord-1"}

    def test_run_id_falls_back_to_route_run(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, {"runStatus": {"routeRun": RUN_ID, "status": "RUNNING"}}))

        assert str(client.workflows.start(WORKFLOW_ID).id) == RUN_ID

    def test_no_run_id_is_an_error(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, {"runStatus": {}}))

        with pytest.raises(APIError, match="no run id"):
            client.workflows.start(WORKFLOW_ID)


class TestRunAndWait:
    def test_runs_waits_and_fetches_the_double_encoded_output(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("POST", EXEC_ID, (200, started()))
        platform.on(
            "POST",
            f"{RUN}/wait",
            (408, run_dto("RUNNING")),
            (200, run_dto("FINISHED", finalOutputUrl=f"{S3}/out?sig=1", finalOutputRef=OUTPUT_REF)),
        )
        platform.on("GET", f"{S3}/out", (200, DOUBLE_ENCODED))

        run = client.workflows.run(WORKFLOW_ID, {"file_url": "x"}, timeout=60)

        assert run.status is RunStatus.FINISHED
        assert run.succeeded and run.is_terminal
        assert run.output == {"total": 42, "lines": [1, 2]}
        assert run.outputs == run.output  # 0.1 name
        assert len(platform.calls("POST", "/wait")) == 2
        download = platform.calls("GET", "/out")[0]
        assert "X-API-Key" not in download.headers, "the API key must never go to the storage host"

    def test_an_expired_output_link_is_refreshed(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, started()))
        platform.on(
            "POST",
            f"{RUN}/wait",
            (200, run_dto("FINISHED", finalOutputUrl=f"{S3}/old", finalOutputRef=OUTPUT_REF)),
        )
        platform.on("GET", f"{S3}/old", (403, "<Error><Code>AccessDenied</Code>Request has expired</Error>"))
        platform.on(
            "POST",
            f"{RUN}/refresh-presigned-urls",
            (200, {"runId": RUN_ID, "success": True, "presignedUrls": {OUTPUT_REF: f"{S3}/new"}}),
        )
        platform.on("GET", f"{S3}/new", (200, DOUBLE_ENCODED))

        run = client.workflows.run(WORKFLOW_ID)

        assert run.output == {"total": 42, "lines": [1, 2]}

    def test_an_inline_result_is_used_without_a_download(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("POST", EXEC_ID, (200, started()))
        platform.on("POST", f"{RUN}/wait", (200, run_dto("FINISHED", value='{"ok": true}')))

        run = client.workflows.run(WORKFLOW_ID)

        assert run.output == {"ok": True}
        assert not platform.calls("GET", "/out")

    def test_a_failed_run_raises_with_the_reason(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, started()))
        platform.on("POST", f"{RUN}/wait", (200, run_dto("FAILED", error="Step 'fetch' timed out")))

        with pytest.raises(RunFailedError) as caught:
            client.workflows.run(WORKFLOW_ID)

        assert caught.value.run.status is RunStatus.FAILED
        assert "Step 'fetch' timed out" in str(caught.value)

    def test_a_failed_run_can_be_returned_instead(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, started()))
        platform.on("POST", f"{RUN}/wait", (200, run_dto("CANCELLED")))

        run = client.workflows.run(WORKFLOW_ID, raise_on_failure=False)

        assert run.status is RunStatus.CANCELLED
        assert run.output is None

    def test_a_run_that_does_not_end_in_time_raises_with_its_state(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("POST", f"{RUN}/wait", (408, run_dto("WAITING_HUMAN")))
        platform.on("GET", RUN, (200, run_dto("WAITING_HUMAN", waitInfo={"waitType": "HUMAN"})))

        with pytest.raises(RunTimeoutError) as caught:
            client.workflows.wait(RUN_ID, timeout=0.2, poll_interval=0.01)

        assert caught.value.run.is_waiting
        assert caught.value.run.wait_info == {"waitType": "HUMAN"}

    def test_return_on_waiting_hands_back_a_paused_run(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("GET", RUN, (200, run_dto("RUNNING")), (200, run_dto("WAITING_HUMAN")))

        run = client.workflows.wait(RUN_ID, return_on_waiting=True, poll_interval=0)

        assert run.status is RunStatus.WAITING_HUMAN
        assert not platform.calls("POST", "/wait")

    def test_falls_back_to_polling_without_the_wait_endpoint(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("POST", f"{RUN}/wait", (405, {"message": "Method Not Allowed"}))
        platform.on("GET", RUN, (200, run_dto("RUNNING")), (200, run_dto("FINISHED")))

        run = client.workflows.wait(RUN_ID, poll_interval=0)

        assert run.status is RunStatus.FINISHED

    def test_long_poll_stays_inside_the_server_and_load_balancer_limits(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("POST", f"{RUN}/wait", (200, run_dto("FINISHED")))

        client.workflows.wait(RUN_ID, timeout=600)

        timeout_ms = int(platform.calls("POST", "/wait")[0].url.params["timeout"])
        assert 1000 <= timeout_ms <= 120_000

    def test_legacy_sync_false_still_returns_the_started_run(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("POST", EXEC_ID, (200, started("RUNNING")))

        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter("always")
            run = client.workflows.run(WORKFLOW_ID, sync=False)

        assert run.status is RunStatus.RUNNING
        assert any(issubclass(w.category, DeprecationWarning) for w in seen)


class TestReadingRuns:
    def test_get_run_parses_the_real_dto(self, client: Client, platform: FakePlatform) -> None:
        platform.on("GET", RUN, (200, run_dto("FINISHED", finishedAt="2026-10-21T15:04:07.623+0000")))

        run = client.workflows.get_run(RUN_ID)

        assert run.status is RunStatus.FINISHED
        assert run.status is RunStatus.COMPLETED  # 0.1 name, same member
        assert run.inputs == {"file_url": "https://example.com/a.pdf"}
        assert run.started_at is not None and run.started_at.utcoffset() is not None
        assert run.duration_ms == 2500
        assert run.scope_key == "customer:acme"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("QUEUED", RunStatus.QUEUED),
            ("WAITING_HUMAN", RunStatus.WAITING_HUMAN),
            ("PAUSED", RunStatus.WAITING_HUMAN),
            ("Finished", RunStatus.FINISHED),
            ("TERMINATED", RunStatus.TERMINATED),
        ],
    )
    def test_statuses(self, raw: str, expected: RunStatus) -> None:
        assert WorkflowRun.model_validate(run_dto(raw)).status is expected

    def test_an_unknown_status_is_kept_not_rejected(self) -> None:
        run = WorkflowRun.model_validate(run_dto("SOMETHING_NEW"))

        assert run.status == "SOMETHING_NEW"
        assert not run.is_terminal

    def test_list_runs_reads_data_and_pagination(self, client: Client, platform: FakePlatform) -> None:
        platform.on(
            "GET",
            f"{BASE}/api/v1/workflow/run",
            (200, {
                "data": [run_dto("FINISHED")],
                "pagination": {"page": 0, "size": 20, "totalElements": 1, "totalPages": 1},
            }),
        )

        runs, page = client.workflows.list_runs(status=RunStatus.FINISHED, scope_key="customer:acme")

        assert len(runs) == 1 and runs[0].status is RunStatus.FINISHED
        assert page.total_elements == 1
        params = platform.requests[0].url.params
        assert params["status"] == "FINISHED" and params["scopeKey"] == "customer:acme"

    def test_by_external_id_is_none_only_when_missing(self, client: Client, platform: FakePlatform) -> None:
        platform.on("GET", f"{BASE}/api/v1/workflow/run/by-external-id/nope", (404, {}))
        platform.on("GET", f"{BASE}/api/v1/workflow/run/by-external-id/boom", (500, {"message": "down"}))

        assert client.workflows.get_run_by_external_id("nope") is None
        with pytest.raises(APIError):
            client.workflows.get_run_by_external_id("boom")

    def test_external_id_is_url_encoded(self, client: Client, platform: FakePlatform) -> None:
        platform.on("GET", f"{BASE}/api/v1/workflow/run/by-external-id/order/1 2", (200, run_dto("RUNNING")))

        run = client.workflows.get_run_by_external_id("order/1 2")

        assert run is not None
        assert platform.requests[0].url.raw_path.endswith(b"/by-external-id/order%2F1%202")

    @pytest.mark.parametrize("bad", ["/relative/final-output.json", "ftp://bucket/x", "not a url"])
    def test_an_unusable_result_link_is_an_api_error(
        self, client: Client, platform: FakePlatform, bad: str
    ) -> None:
        run = WorkflowRun.model_validate(run_dto("FINISHED", finalOutputUrl=bad))

        with pytest.raises(APIError, match="not a usable URL"):
            client.workflows.get_output(run)

    def test_cancel(self, client: Client, platform: FakePlatform) -> None:
        platform.on("POST", f"{RUN}/cancel", (200, run_dto("CANCELLED")))

        run = client.workflows.cancel(RUN_ID, reason="duplicate")

        assert run.status is RunStatus.CANCELLED
        assert platform.requests[0].url.params["reason"] == "duplicate"


class TestErrors:
    def test_403_is_permission_denied_and_carries_the_server_message(
        self, client: Client, platform: FakePlatform
    ) -> None:
        platform.on("GET", RUN, (403, {"status": 403, "error": "Forbidden",
                                      "message": "This API key cannot read this run"}))

        with pytest.raises(PermissionDeniedError) as caught:
            client.workflows.get_run(RUN_ID)

        assert isinstance(caught.value, AuthenticationError)  # 0.1 code that caught this still does
        assert "cannot read this run" in str(caught.value)
        assert caught.value.status_code == 403

    def test_401(self, client: Client, platform: FakePlatform) -> None:
        platform.on("GET", RUN, (401, ""))

        with pytest.raises(AuthenticationError) as caught:
            client.workflows.get_run(RUN_ID)

        assert not isinstance(caught.value, PermissionDeniedError)


class TestDecodeOutput:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (DOUBLE_ENCODED, {"total": 42, "lines": [1, 2]}),
            (json.dumps({"a": 1}), {"a": 1}),
            (json.dumps(json.dumps(json.dumps([1]))), [1]),
            (json.dumps("plain text"), "plain text"),
            ("not json", "not json"),
            (b'"{\\"b\\": 2}"', {"b": 2}),
            (json.dumps("42"), "42"),
        ],
    )
    def test_decodes(self, raw: Any, expected: Any) -> None:
        assert decode_output(raw) == expected


class TestAsync:
    async def test_run_end_to_end(self, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, started()))
        platform.on(
            "POST",
            f"{RUN}/wait",
            (408, run_dto("RUNNING")),
            (200, run_dto("FINISHED", finalOutputUrl=f"{S3}/out", finalOutputRef=OUTPUT_REF)),
        )
        platform.on("GET", f"{S3}/out", (200, DOUBLE_ENCODED))

        async with AsyncClient(
            api_key=KEY, base_url=BASE, transport=httpx.MockTransport(platform)
        ) as client:
            run = await client.workflows.run(WORKFLOW_ID, {"x": 1})

        assert run.output == {"total": 42, "lines": [1, 2]}
        assert "X-API-Key" not in platform.calls("GET", "/out")[0].headers

    async def test_failed_run_raises(self, platform: FakePlatform) -> None:
        platform.on("POST", EXEC_ID, (200, started()))
        platform.on("POST", f"{RUN}/wait", (200, run_dto("TERMINATED")))

        async with AsyncClient(
            api_key=KEY, base_url=BASE, transport=httpx.MockTransport(platform)
        ) as client:
            with pytest.raises(RunFailedError):
                await client.workflows.run(WORKFLOW_ID)

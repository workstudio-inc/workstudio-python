"""
Workflows module for the work.studio SDK: start a workflow from code, follow it, read its result.

The platform's contract, which this module wraps:

1. ``POST /api/v1/workflow/execute/id/{globalUniqueId}?async=true`` (or ``/execute/{slug}``)
   with ``X-API-Key`` and the inputs as the JSON body. The run id comes back in
   ``executionResult.runId``.
2. ``POST /api/v1/workflow/run/{id}/wait?timeout=<ms>`` long-polls until the run ends (408 = still
   going), or ``GET /api/v1/workflow/run/{id}`` reads it. A key that can start runs can read the
   runs it started - a customer key its own customer's runs.
3. The result of a ``FINISHED`` run is behind ``finalOutputUrl``, a presigned link that expires; its
   body is JSON, often a JSON document encoded as a string inside it. ``refresh-presigned-urls``
   mints a fresh link.
"""

from __future__ import annotations

import asyncio
import time
import warnings
from typing import Any, List, Optional, Union
from uuid import UUID

from workstudio import _runs
from workstudio._http import AsyncHTTPClient, HTTPClient, parse_body, raise_for_status
from workstudio.exceptions import (
    APIError,
    NotFoundError,
    RunFailedError,
    RunTimeoutError,
)
from workstudio.models import PageInfo, RunStatus, Workflow, WorkflowRun

# Kept for code that imported them from here in 0.1.
API_PREFIX = _runs.API_PREFIX
PORTAL_PATH = _runs.PORTAL_PATH
RUN_PATH = _runs.RUN_PATH
EXECUTE_PATH = _runs.EXECUTE_PATH

DEFAULT_RUN_TIMEOUT = 300.0
DEFAULT_POLL_INTERVAL = 2.0

WorkflowRef = Union[UUID, str]


def _legacy_run_args(
    timeout: Optional[float], sync: Optional[bool], timeout_seconds: Optional[int]
) -> tuple[float, bool]:
    if sync is not None or timeout_seconds is not None:
        warnings.warn(
            "run(sync=..., timeout_seconds=...) is deprecated: use start() to not wait, and "
            "run(timeout=...) to bound the wait",
            DeprecationWarning,
            stacklevel=3,
        )
    effective = timeout if timeout is not None else (
        float(timeout_seconds) if timeout_seconds is not None else DEFAULT_RUN_TIMEOUT
    )
    return effective, sync is not False


class WorkflowsClient:
    """Synchronous client for workflow operations."""

    def __init__(self, http: HTTPClient):
        self._http = http

    # ------------------------------------------------------------------ definitions

    def list(
        self,
        page: int = 0,
        size: int = 20,
        search: Optional[str] = None,
    ) -> tuple[List[Workflow], PageInfo]:
        """
        List workflow definitions (needs a key allowed to read them, e.g. ``workflow:read``).

        Returns:
            Tuple of (workflows, page info)
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search
        items, page_info = _runs.parse_page(self._http.get(PORTAL_PATH, params=params))
        return [Workflow.model_validate(w) for w in items], page_info

    def get(self, workflow_id: WorkflowRef) -> Workflow:
        """Get a workflow definition by its id."""
        return Workflow.model_validate(self._http.get(f"{PORTAL_PATH}/{workflow_id}"))

    def get_by_endpoint(self, endpoint: str) -> Workflow:
        """Get a workflow definition by its endpoint slug."""
        return Workflow.model_validate(self._http.get(f"{PORTAL_PATH}/by-endpoint/{endpoint}"))

    # ------------------------------------------------------------------ runs

    def start(
        self,
        workflow: WorkflowRef,
        inputs: Optional[dict[str, Any]] = None,
        *,
        scope_key: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> WorkflowRun:
        """
        Start a run and return at once, without waiting for it.

        Args:
            workflow: The workflow's global unique id (UUID) or its endpoint slug.
            inputs: Input data for the workflow (the JSON body).
            scope_key: The customer to run for, e.g. ``"customer:acme"`` - for a TENANT key. A
                CUSTOMER key always runs as its own customer.
            external_id: Your correlation id; find the run later with ``get_run_by_external_id``.

        Returns:
            The run, usually ``QUEUED`` or ``RUNNING``. Follow it with :meth:`wait`.
        """
        body = self._http.post(
            _runs.execute_path(workflow),
            json=_runs.start_body(inputs, external_id),
            params={"async": "true"},
            headers=_runs.scope_headers(scope_key),
        )
        return _runs.run_from_start(body)

    def run(
        self,
        workflow: WorkflowRef,
        inputs: Optional[dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
        scope_key: Optional[str] = None,
        external_id: Optional[str] = None,
        raise_on_failure: bool = True,
        fetch_output: bool = True,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        sync: Optional[bool] = None,
        timeout_seconds: Optional[int] = None,
    ) -> WorkflowRun:
        """
        Run a workflow and wait for its result.

        Starts the run, waits until it ends, and puts the decoded result in ``run.output``.

        Args:
            workflow: The workflow's global unique id (UUID) or its endpoint slug.
            inputs: Input data for the workflow.
            timeout: Seconds to wait for the run to end (default 300). The run is not cancelled
                when this passes; :class:`RunTimeoutError` carries it so you can keep waiting.
            scope_key: The customer to run for (TENANT keys), e.g. ``"customer:acme"``.
            external_id: Your correlation id.
            raise_on_failure: Raise :class:`RunFailedError` when the run ends ``FAILED``,
                ``CANCELLED`` or ``TERMINATED`` (default). With False, return the run instead.
            fetch_output: Fetch and decode the result of a ``FINISHED`` run (default).
            poll_interval: Seconds between status checks when long-polling is unavailable.

        Raises:
            RunFailedError: The run ended without succeeding (and ``raise_on_failure``).
            RunTimeoutError: The run had not ended within ``timeout``.

        Example:
            run = client.workflows.run("invoice-processor", {"file_url": "..."})
            print(run.output)
        """
        effective_timeout, wait = _legacy_run_args(timeout, sync, timeout_seconds)
        started = self.start(workflow, inputs, scope_key=scope_key, external_id=external_id)
        if not wait:
            return started
        run = started if started.is_terminal else self.wait(
            started.id, timeout=effective_timeout, poll_interval=poll_interval
        )
        if not run.succeeded:
            if raise_on_failure and run.is_terminal:
                raise RunFailedError(run)
            return run
        if fetch_output:
            run.output = self.get_output(run)
        return run

    def get_run(self, run_id: WorkflowRef) -> WorkflowRun:
        """Get a run's current state."""
        return WorkflowRun.model_validate(self._http.get(f"{RUN_PATH}/{run_id}"))

    def wait(
        self,
        run_id: WorkflowRef,
        *,
        timeout: float = DEFAULT_RUN_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        return_on_waiting: bool = False,
    ) -> WorkflowRun:
        """
        Wait for a run to end and return it.

        Long-polls the platform (one request per ~110s rather than one per second). With
        ``return_on_waiting=True`` it polls instead, and returns as soon as the run is paused
        (``WAITING_HUMAN`` - e.g. for an approval), so you can act on ``run.wait_info``.

        Raises:
            RunTimeoutError: The run had not ended within ``timeout`` seconds.
        """
        deadline = time.monotonic() + timeout
        last: Optional[WorkflowRun] = None
        long_poll = not return_on_waiting
        while True:
            remaining = deadline - time.monotonic()
            if long_poll and remaining > 0:
                seconds = min(remaining, _runs.LONG_POLL_MAX_SECONDS)
                response = self._http.send(
                    "POST",
                    f"{RUN_PATH}/{run_id}/wait",
                    params={"timeout": max(int(seconds * 1000), 1000)},
                    timeout=seconds + 15.0,
                )
                if response.status_code in (405, 501):
                    long_poll = False  # an older platform without the wait endpoint: poll
                    continue
                if response.status_code not in (200, 408):
                    raise_for_status(response)
                body = parse_body(response)
                if not body:
                    long_poll = False  # nothing to read the state from: poll instead
                    continue
                last = WorkflowRun.model_validate(body)
                if last.is_terminal:
                    return last
                continue
            last = self.get_run(run_id)
            if last.is_terminal or (return_on_waiting and last.is_waiting):
                return last
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RunTimeoutError(last, timeout)
            time.sleep(min(poll_interval, remaining))

    def get_output(self, run: Union[WorkflowRun, WorkflowRef]) -> Any:
        """
        The decoded result of a finished run.

        Uses the result the platform returned inline when there is one, else downloads it from
        ``final_output_url`` - without your API key, which never leaves the API host - and mints a
        fresh link when that one has expired. ``None`` when the run produced no result.
        """
        if not isinstance(run, WorkflowRun):
            run = self.get_run(run)
        if run.value is not None:
            return _runs.decode_output(run.value)
        if not run.final_output_url and not run.final_output_ref:
            run = self.get_run(run.id)
        url = run.final_output_url
        if url:
            response = self._http.fetch_external(url)
            if response.status_code == 200:
                return _runs.decode_output(response.content)
            if response.status_code not in _runs.EXPIRED_URL_STATUSES:
                raise APIError(
                    f"Could not download the run's result (HTTP {response.status_code})",
                    status_code=response.status_code,
                )
        if not run.final_output_ref and not url:
            return None
        fresh = _runs.fresh_output_url(self.refresh_output_urls(run.id), run)
        if not fresh:
            if url:
                raise APIError("The run's result link expired and no fresh one could be made")
            return None
        response = self._http.fetch_external(fresh)
        if response.status_code != 200:
            raise APIError(
                f"Could not download the run's result (HTTP {response.status_code})",
                status_code=response.status_code,
            )
        return _runs.decode_output(response.content)

    def refresh_output_urls(self, run_id: WorkflowRef) -> dict[str, Any]:
        """Fresh presigned links to a run's stored artefacts: ``{"presignedUrls": {ref: url}}``."""
        result = self._http.post(f"{RUN_PATH}/{run_id}/refresh-presigned-urls")
        return result if isinstance(result, dict) else {}

    def cancel(self, run_id: WorkflowRef, reason: Optional[str] = None) -> WorkflowRun:
        """Cancel a run that has not ended (a no-op for one that has)."""
        params = {"reason": reason} if reason else None
        return WorkflowRun.model_validate(
            self._http.post(f"{RUN_PATH}/{run_id}/cancel", params=params)
        )

    def get_run_by_external_id(self, external_id: str) -> Optional[WorkflowRun]:
        """The run started with this ``external_id``, or None when there is none."""
        try:
            response = self._http.get(_runs.by_external_id_path(external_id))
        except NotFoundError:
            return None
        return WorkflowRun.model_validate(response) if response else None

    def list_runs(
        self,
        page: int = 0,
        size: int = 20,
        workflow_id: Optional[WorkflowRef] = None,
        *,
        status: Optional[Union[RunStatus, str]] = None,
        scope_key: Optional[str] = None,
    ) -> tuple[List[WorkflowRun], PageInfo]:
        """
        List runs, newest first - the ones this key may read (a customer key: its customer's).

        Args:
            workflow_id: Only runs of this workflow (its environment id).
            status: Only runs in this status.
            scope_key: Only runs started for this customer, e.g. ``"customer:acme"``.
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if workflow_id:
            params["workflowId"] = str(workflow_id)
        if status:
            params["status"] = status.value if isinstance(status, RunStatus) else str(status)
        if scope_key:
            params["scopeKey"] = scope_key
        items, page_info = _runs.parse_page(self._http.get(RUN_PATH, params=params))
        return [WorkflowRun.model_validate(r) for r in items], page_info


class AsyncWorkflowsClient:
    """Asynchronous client for workflow operations. Same methods as :class:`WorkflowsClient`."""

    def __init__(self, http: AsyncHTTPClient):
        self._http = http

    async def list(
        self,
        page: int = 0,
        size: int = 20,
        search: Optional[str] = None,
    ) -> tuple[List[Workflow], PageInfo]:
        """List workflow definitions."""
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search
        items, page_info = _runs.parse_page(await self._http.get(PORTAL_PATH, params=params))
        return [Workflow.model_validate(w) for w in items], page_info

    async def get(self, workflow_id: WorkflowRef) -> Workflow:
        """Get a workflow definition by its id."""
        return Workflow.model_validate(await self._http.get(f"{PORTAL_PATH}/{workflow_id}"))

    async def get_by_endpoint(self, endpoint: str) -> Workflow:
        """Get a workflow definition by its endpoint slug."""
        return Workflow.model_validate(
            await self._http.get(f"{PORTAL_PATH}/by-endpoint/{endpoint}")
        )

    async def start(
        self,
        workflow: WorkflowRef,
        inputs: Optional[dict[str, Any]] = None,
        *,
        scope_key: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> WorkflowRun:
        """Start a run and return at once - see :meth:`WorkflowsClient.start`."""
        body = await self._http.post(
            _runs.execute_path(workflow),
            json=_runs.start_body(inputs, external_id),
            params={"async": "true"},
            headers=_runs.scope_headers(scope_key),
        )
        return _runs.run_from_start(body)

    async def run(
        self,
        workflow: WorkflowRef,
        inputs: Optional[dict[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
        scope_key: Optional[str] = None,
        external_id: Optional[str] = None,
        raise_on_failure: bool = True,
        fetch_output: bool = True,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        sync: Optional[bool] = None,
        timeout_seconds: Optional[int] = None,
    ) -> WorkflowRun:
        """Run a workflow and wait for its result - see :meth:`WorkflowsClient.run`."""
        effective_timeout, wait = _legacy_run_args(timeout, sync, timeout_seconds)
        started = await self.start(workflow, inputs, scope_key=scope_key, external_id=external_id)
        if not wait:
            return started
        run = started if started.is_terminal else await self.wait(
            started.id, timeout=effective_timeout, poll_interval=poll_interval
        )
        if not run.succeeded:
            if raise_on_failure and run.is_terminal:
                raise RunFailedError(run)
            return run
        if fetch_output:
            run.output = await self.get_output(run)
        return run

    async def get_run(self, run_id: WorkflowRef) -> WorkflowRun:
        """Get a run's current state."""
        return WorkflowRun.model_validate(await self._http.get(f"{RUN_PATH}/{run_id}"))

    async def wait(
        self,
        run_id: WorkflowRef,
        *,
        timeout: float = DEFAULT_RUN_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        return_on_waiting: bool = False,
    ) -> WorkflowRun:
        """Wait for a run to end - see :meth:`WorkflowsClient.wait`."""
        deadline = time.monotonic() + timeout
        last: Optional[WorkflowRun] = None
        long_poll = not return_on_waiting
        while True:
            remaining = deadline - time.monotonic()
            if long_poll and remaining > 0:
                seconds = min(remaining, _runs.LONG_POLL_MAX_SECONDS)
                response = await self._http.send(
                    "POST",
                    f"{RUN_PATH}/{run_id}/wait",
                    params={"timeout": max(int(seconds * 1000), 1000)},
                    timeout=seconds + 15.0,
                )
                if response.status_code in (405, 501):
                    long_poll = False
                    continue
                if response.status_code not in (200, 408):
                    raise_for_status(response)
                body = parse_body(response)
                if not body:
                    long_poll = False  # nothing to read the state from: poll instead
                    continue
                last = WorkflowRun.model_validate(body)
                if last.is_terminal:
                    return last
                continue
            last = await self.get_run(run_id)
            if last.is_terminal or (return_on_waiting and last.is_waiting):
                return last
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RunTimeoutError(last, timeout)
            await asyncio.sleep(min(poll_interval, remaining))

    async def get_output(self, run: Union[WorkflowRun, WorkflowRef]) -> Any:
        """The decoded result of a finished run - see :meth:`WorkflowsClient.get_output`."""
        if not isinstance(run, WorkflowRun):
            run = await self.get_run(run)
        if run.value is not None:
            return _runs.decode_output(run.value)
        if not run.final_output_url and not run.final_output_ref:
            run = await self.get_run(run.id)
        url = run.final_output_url
        if url:
            response = await self._http.fetch_external(url)
            if response.status_code == 200:
                return _runs.decode_output(response.content)
            if response.status_code not in _runs.EXPIRED_URL_STATUSES:
                raise APIError(
                    f"Could not download the run's result (HTTP {response.status_code})",
                    status_code=response.status_code,
                )
        if not run.final_output_ref and not url:
            return None
        fresh = _runs.fresh_output_url(await self.refresh_output_urls(run.id), run)
        if not fresh:
            if url:
                raise APIError("The run's result link expired and no fresh one could be made")
            return None
        response = await self._http.fetch_external(fresh)
        if response.status_code != 200:
            raise APIError(
                f"Could not download the run's result (HTTP {response.status_code})",
                status_code=response.status_code,
            )
        return _runs.decode_output(response.content)

    async def refresh_output_urls(self, run_id: WorkflowRef) -> dict[str, Any]:
        """Fresh presigned links to a run's stored artefacts."""
        result = await self._http.post(f"{RUN_PATH}/{run_id}/refresh-presigned-urls")
        return result if isinstance(result, dict) else {}

    async def cancel(self, run_id: WorkflowRef, reason: Optional[str] = None) -> WorkflowRun:
        """Cancel a run that has not ended."""
        params = {"reason": reason} if reason else None
        return WorkflowRun.model_validate(
            await self._http.post(f"{RUN_PATH}/{run_id}/cancel", params=params)
        )

    async def get_run_by_external_id(self, external_id: str) -> Optional[WorkflowRun]:
        """The run started with this ``external_id``, or None when there is none."""
        try:
            response = await self._http.get(_runs.by_external_id_path(external_id))
        except NotFoundError:
            return None
        return WorkflowRun.model_validate(response) if response else None

    async def list_runs(
        self,
        page: int = 0,
        size: int = 20,
        workflow_id: Optional[WorkflowRef] = None,
        *,
        status: Optional[Union[RunStatus, str]] = None,
        scope_key: Optional[str] = None,
    ) -> tuple[List[WorkflowRun], PageInfo]:
        """List runs this key may read - see :meth:`WorkflowsClient.list_runs`."""
        params: dict[str, Any] = {"page": page, "size": size}
        if workflow_id:
            params["workflowId"] = str(workflow_id)
        if status:
            params["status"] = status.value if isinstance(status, RunStatus) else str(status)
        if scope_key:
            params["scopeKey"] = scope_key
        items, page_info = _runs.parse_page(await self._http.get(RUN_PATH, params=params))
        return [WorkflowRun.model_validate(r) for r in items], page_info

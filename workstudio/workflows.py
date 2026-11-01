"""
Workflows module for the work.studio SDK.

Routes (all under ``/api/v1/workflow``; prod serves them from the monolith behind
``https://api.work.studio``):

- ``POST /execute/{endpoint}`` and ``POST /execute/id/{globalUniqueId}`` start a run (trigger
  ``WorkflowExecutionController``). The body is the run's input; ``?async=true`` answers at once
  with ``{runStatus, executionResult}``. Any API key with ``workflow:execute`` may call them, a
  customer key included (it always runs for its own customer).
- ``POST /run/{id}/wait``, ``GET /run/{id}``, ``GET /run``, ``GET /run/by-external-id/{id}`` read
  runs (run ``WorkflowRunController``). A key with only ``workflow:execute`` reads the runs it
  started.
- ``GET /portal``, ``GET /portal/{id}``, ``GET /portal/by-endpoint/{endpoint}`` read definitions
  (portal ``WorkflowPortalController``): organization keys only, never customer keys.
"""

import asyncio
import time
from typing import Any, List, Optional, Union
from urllib.parse import quote
from uuid import UUID

from workstudio._http import AsyncHTTPClient, HTTPClient
from workstudio.exceptions import NotFoundError, WorkStudioError
from workstudio.models import (
    PageInfo,
    Workflow,
    WorkflowRun,
    parse_page,
)

# API paths (matching backend Constant.WF_SERVICE_MOUNT_POINT)
API_PREFIX = "/api/v1/workflow"
PORTAL_PATH = f"{API_PREFIX}/portal"
RUN_PATH = f"{API_PREFIX}/run"
EXECUTE_PATH = f"{API_PREFIX}/execute"

#: Start the run and answer at once; the SDK then follows it with /run/{id}/wait.
_ASYNC = {"async": "true"}

#: Longest single long-poll on ``/run/{id}/wait``. The server caps one wait at 120 s and the load
#: balancer closes a connection that is silent for 180 s; 110 s stays inside both.
LONG_POLL_MAX_SECONDS = 110.0

#: Extra seconds the HTTP read may take beyond the wait it asked the server for.
_WAIT_HTTP_MARGIN_SECONDS = 15.0

#: The largest page the platform answers (base-common ``SearchRequest.MAX_SIZE``); a bigger ``size``
#: is clamped to it without an error.
MAX_PAGE_SIZE = 100

#: Runaway guard for :meth:`WorkflowsClient.list_all`: 200 pages of 100.
_MAX_PAGES = 200


def _has_page_after(info: PageInfo, page: int) -> bool:
    """Whether the server says there is a page after ``page`` (0-based)."""
    return bool(info.has_next) or page + 1 < info.total_pages


def _keep_new(rows: List[Workflow], seen: set[str], out: List[Workflow]) -> None:
    """Append the rows not seen yet: a row returned on two pages (the list changed) is kept once."""
    for wf in rows:
        key = str(wf.id) if wf.id is not None else None
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(wf)


def _as_workflow_uuid(workflow_id: Union[UUID, str]) -> Optional[UUID]:
    """The workflow id as a UUID, or None when it is an endpoint name."""
    if isinstance(workflow_id, UUID):
        return workflow_id
    try:
        return UUID(str(workflow_id).strip())
    except ValueError:
        return None


def _segment(value: Any) -> str:
    """One URL path segment, encoded: an endpoint name or external id may hold ``/``, ``?``."""
    return quote(str(value).strip(), safe="")


def _execute_path(workflow_id: Union[UUID, str]) -> str:
    """
    The route that starts a workflow from code.

    A UUID is the workflow's global unique id (``/execute/id/{id}``); anything else is its endpoint
    name (``/execute/{endpoint}``).
    """
    workflow_uuid = _as_workflow_uuid(workflow_id)
    if workflow_uuid is not None:
        return f"{EXECUTE_PATH}/id/{workflow_uuid}"
    return f"{EXECUTE_PATH}/{_segment(workflow_id)}"


def _start_body(inputs: Optional[dict[str, Any]], external_id: Optional[str]) -> dict[str, Any]:
    """The run's input; ``externalId`` rides in it (the trigger service reads it from there)."""
    body = dict(inputs or {})
    if external_id is not None:
        body["externalId"] = external_id
    return body


def _wait_params(seconds: float) -> dict[str, Any]:
    return {"timeout": max(1, int(seconds * 1000))}


def _endpoint_not_found(endpoint: str, cause: NotFoundError) -> NotFoundError:
    return NotFoundError(
        message=f"No workflow with endpoint '{endpoint}' was found: {cause.message}",
        status_code=cause.status_code or 404,
        response_body=cause.response_body,
    )


class WorkflowsClient:
    """Synchronous client for workflow operations."""

    def __init__(self, http: HTTPClient):
        self._http = http

    def list(
        self,
        page: int = 0,
        size: int = 20,
        search: Optional[str] = None,
    ) -> tuple[list[Workflow], PageInfo]:
        """
        One page of workflows.

        Needs an organization key (``svx_tk_``); a customer key gets 403. One page is not the list:
        the platform answers 20 rows unless asked and never more than 100. For every workflow use
        :meth:`list_all`, or follow ``page_info.has_next``.

        Args:
            page: Page number (0-indexed)
            size: Number of items per page (at most 100)
            search: Optional search query

        Returns:
            Tuple of (workflows on this page, page info)

        Example:
            workflows, page_info = client.workflows.list(page=0, size=50)
            for wf in workflows:
                print(f"{wf.name}: {wf.id}")
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search

        items, page_info = parse_page(self._http.get(PORTAL_PATH, params=params))
        return [Workflow.model_validate(w) for w in items], page_info

    def list_all(self, search: Optional[str] = None) -> List[Workflow]:
        """
        Every workflow, across all pages.

        Reads pages of 100 until the server says there is no next page. A workflow returned on two
        pages (one was created while the pages were read) is kept once. A failed page raises; it is
        never passed off as the whole list.

        Example:
            for wf in client.workflows.list_all():
                print(f"{wf.name}: {wf.id}")
        """
        out: List[Workflow] = []
        seen: set[str] = set()
        for page in range(_MAX_PAGES):
            rows, info = self.list(page=page, size=MAX_PAGE_SIZE, search=search)
            _keep_new(rows, seen, out)
            if not _has_page_after(info, page):
                break
        return out

    def get(self, workflow_id: Union[UUID, str]) -> Workflow:
        """
        Get a workflow by ID.

        Args:
            workflow_id: The workflow UUID

        Returns:
            The workflow

        Raises:
            NotFoundError: If workflow not found
        """
        response = self._http.get(f"{PORTAL_PATH}/{_segment(workflow_id)}")
        return Workflow.model_validate(response)

    def get_by_endpoint(self, endpoint: str) -> Workflow:
        """
        Get a workflow by its endpoint name.

        Args:
            endpoint: The workflow endpoint (e.g., "invoice-processor")

        Returns:
            The workflow

        Raises:
            NotFoundError: If workflow not found
        """
        response = self._http.get(f"{PORTAL_PATH}/by-endpoint/{_segment(endpoint)}")
        return Workflow.model_validate(response)

    def run(
        self,
        workflow_id: Union[UUID, str],
        inputs: Optional[dict[str, Any]] = None,
        *,
        sync: bool = True,
        timeout_seconds: int = 300,
        external_id: Optional[str] = None,
    ) -> WorkflowRun:
        """
        Run a workflow.

        Starts the run with ``POST /execute/{endpoint}`` (or ``/execute/id/{globalUniqueId}`` for a
        UUID) and, with ``sync=True``, follows it with ``POST /run/{id}/wait`` until it ends or
        ``timeout_seconds`` pass. The workflow's published version runs.

        Args:
            workflow_id: The workflow's endpoint name, or its global unique id. A workflow's row
                id (``Workflow.id``) also works with an organization key: it is looked up and run
                by its global id.
            inputs: Input data for the workflow
            sync: If True, wait for completion (default: True)
            timeout_seconds: How long to wait in sync mode (default: 300). A run still going
                then is returned as it stands.
            external_id: Optional client-provided correlation ID (``get_run_by_external_id``)

        Returns:
            The workflow run (ended, if it did so within the timeout and sync=True)

        Example:
            # Simple run
            result = client.workflows.run("invoice-processor", {"file_url": "..."})

            # Async run (returns immediately)
            run = client.workflows.run("invoice-processor", sync=False)
            # Poll for status later
            run = client.workflows.get_run(run.id)
        """
        body = _start_body(inputs, external_id)
        run = WorkflowRun.from_api(self._start(workflow_id, body))

        if sync and not run.is_terminal:
            run = self._wait_for_completion(run.id, timeout_seconds)

        return run

    def _start(self, workflow_id: Union[UUID, str], body: dict[str, Any]) -> dict[str, Any]:
        workflow_uuid = _as_workflow_uuid(workflow_id)
        try:
            return self._http.post(_execute_path(workflow_id), json=body, params=_ASYNC)
        except NotFoundError as e:
            if workflow_uuid is None:
                raise _endpoint_not_found(str(workflow_id), e) from e
            # Perhaps a row id (Workflow.id) rather than the global id /execute/id/ takes.
            global_id = self._global_id_of(workflow_uuid)
            if global_id is None or global_id == workflow_uuid:
                raise
            return self._http.post(_execute_path(global_id), json=body, params=_ASYNC)

    def _global_id_of(self, workflow_uuid: UUID) -> Optional[UUID]:
        try:
            return self.get(workflow_uuid).global_unique_id
        except WorkStudioError:
            return None

    def get_run(self, run_id: Union[UUID, str]) -> WorkflowRun:
        """
        Get a workflow run by ID.

        Args:
            run_id: The run UUID

        Returns:
            The workflow run
        """
        response = self._http.get(f"{RUN_PATH}/{_segment(run_id)}")
        return WorkflowRun.from_api(response)

    def get_run_by_external_id(self, external_id: str) -> Optional[WorkflowRun]:
        """
        Get a workflow run by external correlation ID.

        Args:
            external_id: The client-provided external ID

        Returns:
            The workflow run, or None if there is no such run

        Raises:
            WorkStudioError: For any other failure (a refused key, a server error)
        """
        try:
            response = self._http.get(f"{RUN_PATH}/by-external-id/{_segment(external_id)}")
        except NotFoundError:
            return None
        return WorkflowRun.from_api(response)

    def list_runs(
        self,
        page: int = 0,
        size: int = 20,
        workflow_id: Optional[Union[UUID, str]] = None,
    ) -> tuple[List[WorkflowRun], PageInfo]:
        """
        List workflow runs.

        Args:
            page: Page number (0-indexed)
            size: Number of items per page
            workflow_id: Optional filter by workflow ID (the workflow's row id)

        Returns:
            Tuple of (runs list, page info)
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if workflow_id:
            params["workflowId"] = str(workflow_id)

        items, page_info = parse_page(self._http.get(RUN_PATH, params=params))
        return [WorkflowRun.from_api(r) for r in items], page_info

    def _wait_for_completion(
        self,
        run_id: UUID,
        timeout_seconds: int,
        poll_interval: float = 1.0,
    ) -> WorkflowRun:
        """Wait for a workflow run to end, long-polling ``/run/{id}/wait``."""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        run: Optional[WorkflowRun] = None

        while True:
            remaining = deadline - time.monotonic()
            if remaining < 1.0:
                # Return current state even if not complete
                return run if run is not None else self.get_run(run_id)

            wait_seconds = min(remaining, LONG_POLL_MAX_SECONDS)
            began = time.monotonic()
            # 200: the run ended. 408: still going, with the run as it stands.
            body = self._http.request(
                "POST",
                f"{RUN_PATH}/{_segment(run_id)}/wait",
                params=_wait_params(wait_seconds),
                ok_statuses=(408,),
                timeout=wait_seconds + _WAIT_HTTP_MARGIN_SECONDS,
            )
            run = WorkflowRun.from_api(body) if body else self.get_run(run_id)
            if run.is_terminal:
                return run
            if time.monotonic() - began < poll_interval:
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


class AsyncWorkflowsClient:
    """Asynchronous client for workflow operations."""

    def __init__(self, http: AsyncHTTPClient):
        self._http = http

    async def list(
        self,
        page: int = 0,
        size: int = 20,
        search: Optional[str] = None,
    ) -> tuple[list[Workflow], PageInfo]:
        """One page of workflows (organization keys only); see :meth:`WorkflowsClient.list`."""
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search

        items, page_info = parse_page(await self._http.get(PORTAL_PATH, params=params))
        return [Workflow.model_validate(w) for w in items], page_info

    async def list_all(self, search: Optional[str] = None) -> List[Workflow]:
        """Every workflow, across all pages (see :meth:`WorkflowsClient.list_all`)."""
        out: List[Workflow] = []
        seen: set[str] = set()
        for page in range(_MAX_PAGES):
            rows, info = await self.list(page=page, size=MAX_PAGE_SIZE, search=search)
            _keep_new(rows, seen, out)
            if not _has_page_after(info, page):
                break
        return out

    async def get(self, workflow_id: Union[UUID, str]) -> Workflow:
        """Get a workflow by ID."""
        response = await self._http.get(f"{PORTAL_PATH}/{_segment(workflow_id)}")
        return Workflow.model_validate(response)

    async def get_by_endpoint(self, endpoint: str) -> Workflow:
        """Get a workflow by its endpoint name."""
        response = await self._http.get(f"{PORTAL_PATH}/by-endpoint/{_segment(endpoint)}")
        return Workflow.model_validate(response)

    async def run(
        self,
        workflow_id: Union[UUID, str],
        inputs: Optional[dict[str, Any]] = None,
        *,
        sync: bool = True,
        timeout_seconds: int = 300,
        external_id: Optional[str] = None,
    ) -> WorkflowRun:
        """Run a workflow (see :meth:`WorkflowsClient.run`)."""
        body = _start_body(inputs, external_id)
        run = WorkflowRun.from_api(await self._start(workflow_id, body))

        if sync and not run.is_terminal:
            run = await self._wait_for_completion(run.id, timeout_seconds)

        return run

    async def _start(self, workflow_id: Union[UUID, str], body: dict[str, Any]) -> dict[str, Any]:
        workflow_uuid = _as_workflow_uuid(workflow_id)
        try:
            return await self._http.post(_execute_path(workflow_id), json=body, params=_ASYNC)
        except NotFoundError as e:
            if workflow_uuid is None:
                raise _endpoint_not_found(str(workflow_id), e) from e
            global_id = await self._global_id_of(workflow_uuid)
            if global_id is None or global_id == workflow_uuid:
                raise
            return await self._http.post(_execute_path(global_id), json=body, params=_ASYNC)

    async def _global_id_of(self, workflow_uuid: UUID) -> Optional[UUID]:
        try:
            return (await self.get(workflow_uuid)).global_unique_id
        except WorkStudioError:
            return None

    async def get_run(self, run_id: Union[UUID, str]) -> WorkflowRun:
        """Get a workflow run by ID."""
        response = await self._http.get(f"{RUN_PATH}/{_segment(run_id)}")
        return WorkflowRun.from_api(response)

    async def get_run_by_external_id(self, external_id: str) -> Optional[WorkflowRun]:
        """Get a workflow run by external correlation ID; None if there is no such run."""
        try:
            response = await self._http.get(f"{RUN_PATH}/by-external-id/{_segment(external_id)}")
        except NotFoundError:
            return None
        return WorkflowRun.from_api(response)

    async def list_runs(
        self,
        page: int = 0,
        size: int = 20,
        workflow_id: Optional[Union[UUID, str]] = None,
    ) -> tuple[List[WorkflowRun], PageInfo]:
        """List workflow runs."""
        params: dict[str, Any] = {"page": page, "size": size}
        if workflow_id:
            params["workflowId"] = str(workflow_id)

        items, page_info = parse_page(await self._http.get(RUN_PATH, params=params))
        return [WorkflowRun.from_api(r) for r in items], page_info

    async def _wait_for_completion(
        self,
        run_id: UUID,
        timeout_seconds: int,
        poll_interval: float = 1.0,
    ) -> WorkflowRun:
        """Wait for a workflow run to end, long-polling ``/run/{id}/wait``."""
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        run: Optional[WorkflowRun] = None

        while True:
            remaining = deadline - time.monotonic()
            if remaining < 1.0:
                return run if run is not None else await self.get_run(run_id)

            wait_seconds = min(remaining, LONG_POLL_MAX_SECONDS)
            began = time.monotonic()
            body = await self._http.request(
                "POST",
                f"{RUN_PATH}/{_segment(run_id)}/wait",
                params=_wait_params(wait_seconds),
                ok_statuses=(408,),
                timeout=wait_seconds + _WAIT_HTTP_MARGIN_SECONDS,
            )
            run = WorkflowRun.from_api(body) if body else await self.get_run(run_id)
            if run.is_terminal:
                return run
            if time.monotonic() - began < poll_interval:
                await asyncio.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

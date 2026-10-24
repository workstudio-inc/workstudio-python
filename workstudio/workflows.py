"""
Workflows module for the work.studio SDK.
"""

import time
from typing import Any, Optional
from uuid import UUID

from workstudio._http import HTTPClient, AsyncHTTPClient
from workstudio.models import (
    PageInfo,
    RunStatus,
    Workflow,
    WorkflowRun,
)


# API paths (matching backend Constant.WF_SERVICE_MOUNT_POINT)
API_PREFIX = "/api/v1/workflow"
PORTAL_PATH = f"{API_PREFIX}/portal"
RUN_PATH = f"{API_PREFIX}/run"


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
        List all workflows.

        Args:
            page: Page number (0-indexed)
            size: Number of items per page
            search: Optional search query

        Returns:
            Tuple of (workflows list, page info)

        Example:
            workflows, page_info = client.workflows.list()
            for wf in workflows:
                print(f"{wf.name}: {wf.id}")
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search

        response = self._http.get(PORTAL_PATH, params=params)

        workflows = [Workflow.model_validate(w) for w in response.get("content", [])]
        page_info = PageInfo.model_validate(response.get("pageInfo", {}))

        return workflows, page_info

    def get(self, workflow_id: UUID | str) -> Workflow:
        """
        Get a workflow by ID.

        Args:
            workflow_id: The workflow UUID

        Returns:
            The workflow

        Raises:
            NotFoundError: If workflow not found
        """
        response = self._http.get(f"{PORTAL_PATH}/{workflow_id}")
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
        response = self._http.get(f"{PORTAL_PATH}/by-endpoint/{endpoint}")
        return Workflow.model_validate(response)

    def run(
        self,
        workflow_id: UUID | str,
        inputs: Optional[dict[str, Any]] = None,
        *,
        sync: bool = True,
        timeout_seconds: int = 300,
        external_id: Optional[str] = None,
    ) -> WorkflowRun:
        """
        Run a workflow.

        Args:
            workflow_id: The workflow UUID or endpoint name
            inputs: Input data for the workflow
            sync: If True, wait for completion (default: True)
            timeout_seconds: Timeout for sync mode (default: 300)
            external_id: Optional client-provided correlation ID

        Returns:
            The workflow run (completed if sync=True)

        Example:
            # Simple run
            result = client.workflows.run("invoice-processor", {"file_url": "..."})

            # Async run (returns immediately)
            run = client.workflows.run("invoice-processor", sync=False)
            # Poll for status later
            run = client.workflows.get_run(run.id)
        """
        # An endpoint name is looked up first: the portal runs a workflow only by its id.
        try:
            UUID(str(workflow_id))
        except ValueError:
            workflow_id = self.get_by_endpoint(str(workflow_id)).id

        body = inputs or {}

        # PUT /run waits for the run; /run/async starts it and answers at once.
        path = f"{PORTAL_PATH}/{workflow_id}/run" if sync else f"{PORTAL_PATH}/{workflow_id}/run/async"
        response = self._http.put(path, json=body)

        run = WorkflowRun.from_api(response)

        if sync and run.status not in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT):
            run = self._wait_for_completion(run.id, timeout_seconds)

        return run

    def get_run(self, run_id: UUID | str) -> WorkflowRun:
        """
        Get a workflow run by ID.

        Args:
            run_id: The run UUID

        Returns:
            The workflow run
        """
        response = self._http.get(f"{RUN_PATH}/{run_id}")
        return WorkflowRun.from_api(response)

    def get_run_by_external_id(self, external_id: str) -> Optional[WorkflowRun]:
        """
        Get a workflow run by external correlation ID.

        Args:
            external_id: The client-provided external ID

        Returns:
            The workflow run, or None if not found
        """
        try:
            response = self._http.get(f"{RUN_PATH}/by-external-id/{external_id}")
            return WorkflowRun.from_api(response)
        except Exception:
            return None

    def list_runs(
        self,
        page: int = 0,
        size: int = 20,
        workflow_id: Optional[UUID | str] = None,
    ) -> tuple[list[WorkflowRun], PageInfo]:
        """
        List workflow runs.

        Args:
            page: Page number (0-indexed)
            size: Number of items per page
            workflow_id: Optional filter by workflow ID

        Returns:
            Tuple of (runs list, page info)
        """
        params: dict[str, Any] = {"page": page, "size": size}
        if workflow_id:
            params["workflowId"] = str(workflow_id)

        response = self._http.get(RUN_PATH, params=params)

        runs = [WorkflowRun.from_api(r) for r in response.get("content", [])]
        page_info = PageInfo.model_validate(response.get("pageInfo", {}))

        return runs, page_info

    def _wait_for_completion(
        self,
        run_id: UUID,
        timeout_seconds: int,
        poll_interval: float = 1.0,
    ) -> WorkflowRun:
        """Wait for a workflow run to complete."""
        start_time = time.time()
        terminal_states = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}

        while True:
            run = self.get_run(run_id)
            if run.status in terminal_states:
                return run

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                # Return current state even if not complete
                return run

            time.sleep(min(poll_interval, timeout_seconds - elapsed))


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
        """List all workflows."""
        params: dict[str, Any] = {"page": page, "size": size}
        if search:
            params["search"] = search

        response = await self._http.get(PORTAL_PATH, params=params)

        workflows = [Workflow.model_validate(w) for w in response.get("content", [])]
        page_info = PageInfo.model_validate(response.get("pageInfo", {}))

        return workflows, page_info

    async def get(self, workflow_id: UUID | str) -> Workflow:
        """Get a workflow by ID."""
        response = await self._http.get(f"{PORTAL_PATH}/{workflow_id}")
        return Workflow.model_validate(response)

    async def get_by_endpoint(self, endpoint: str) -> Workflow:
        """Get a workflow by its endpoint name."""
        response = await self._http.get(f"{PORTAL_PATH}/by-endpoint/{endpoint}")
        return Workflow.model_validate(response)

    async def run(
        self,
        workflow_id: UUID | str,
        inputs: Optional[dict[str, Any]] = None,
        *,
        sync: bool = True,
        timeout_seconds: int = 300,
        external_id: Optional[str] = None,
    ) -> WorkflowRun:
        """Run a workflow."""
        try:
            UUID(str(workflow_id))
        except ValueError:
            workflow_id = (await self.get_by_endpoint(str(workflow_id))).id

        body = inputs or {}
        path = f"{PORTAL_PATH}/{workflow_id}/run" if sync else f"{PORTAL_PATH}/{workflow_id}/run/async"
        response = await self._http.put(path, json=body)
        run = WorkflowRun.from_api(response)

        if sync and run.status not in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT):
            run = await self._wait_for_completion(run.id, timeout_seconds)

        return run

    async def get_run(self, run_id: UUID | str) -> WorkflowRun:
        """Get a workflow run by ID."""
        response = await self._http.get(f"{RUN_PATH}/{run_id}")
        return WorkflowRun.from_api(response)

    async def get_run_by_external_id(self, external_id: str) -> Optional[WorkflowRun]:
        """Get a workflow run by external correlation ID."""
        try:
            response = await self._http.get(f"{RUN_PATH}/by-external-id/{external_id}")
            return WorkflowRun.from_api(response)
        except Exception:
            return None

    async def list_runs(
        self,
        page: int = 0,
        size: int = 20,
        workflow_id: Optional[UUID | str] = None,
    ) -> tuple[list[WorkflowRun], PageInfo]:
        """List workflow runs."""
        params: dict[str, Any] = {"page": page, "size": size}
        if workflow_id:
            params["workflowId"] = str(workflow_id)

        response = await self._http.get(RUN_PATH, params=params)

        runs = [WorkflowRun.from_api(r) for r in response.get("content", [])]
        page_info = PageInfo.model_validate(response.get("pageInfo", {}))

        return runs, page_info

    async def _wait_for_completion(
        self,
        run_id: UUID,
        timeout_seconds: int,
        poll_interval: float = 1.0,
    ) -> WorkflowRun:
        """Wait for a workflow run to complete."""
        import asyncio

        start_time = time.time()
        terminal_states = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}

        while True:
            run = await self.get_run(run_id)
            if run.status in terminal_states:
                return run

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                return run

            await asyncio.sleep(min(poll_interval, timeout_seconds - elapsed))

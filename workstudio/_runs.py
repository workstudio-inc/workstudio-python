"""
Helpers shared by the sync and async workflow clients: routes, response shapes, output decoding.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Union
from urllib.parse import quote
from uuid import UUID

from workstudio.exceptions import APIError
from workstudio.models import PageInfo, WorkflowRun

API_PREFIX = "/api/v1/workflow"
PORTAL_PATH = f"{API_PREFIX}/portal"
RUN_PATH = f"{API_PREFIX}/run"
EXECUTE_PATH = f"{API_PREFIX}/execute"

#: Longest single long-poll on ``/run/{id}/wait``. The server caps a wait at 120s and the load
#: balancer closes a connection silent for 180s; 110s stays inside both.
LONG_POLL_MAX_SECONDS = 110.0

#: Statuses a presigned storage URL answers with once it has expired.
EXPIRED_URL_STATUSES = frozenset({400, 401, 403})


def execute_path(workflow: Union[UUID, str]) -> str:
    """
    The route that starts a workflow from code.

    A UUID is the workflow's **global unique id** (the one Designer shows under "API", the same in
    every environment) and goes to ``/execute/id/{id}``; anything else is the workflow's endpoint
    slug and goes to ``/execute/{slug}``.
    """
    text = str(workflow).strip()
    try:
        return f"{EXECUTE_PATH}/id/{UUID(text)}"
    except ValueError:
        return f"{EXECUTE_PATH}/{quote(text, safe='')}"


def by_external_id_path(external_id: str) -> str:
    """The lookup route, with the caller's id encoded - it may hold ``/``, spaces, ``?``."""
    return f"{RUN_PATH}/by-external-id/{quote(str(external_id), safe='')}"


def start_body(inputs: Optional[dict[str, Any]], external_id: Optional[str]) -> dict[str, Any]:
    """The request body: the inputs, plus ``externalId`` when given (read from there)."""
    body = dict(inputs or {})
    if external_id is not None:
        body["externalId"] = external_id
    return body


def scope_headers(scope_key: Optional[str]) -> Optional[dict[str, str]]:
    return {"X-SCOPE-KEY": scope_key} if scope_key else None


def run_from_start(body: Any) -> WorkflowRun:
    """
    Read the run out of an ``/execute`` answer.

    The run id is not top level: it is ``executionResult.runId`` (also ``runStatus.routeRun``).
    """
    if not isinstance(body, dict):
        raise APIError("Unexpected response starting a run", response_body=body)
    result = body.get("executionResult") or {}
    status = body.get("runStatus") or {}
    run_id = result.get("runId") or status.get("routeRun") or body.get("runId") or body.get("id")
    if not run_id:
        raise APIError("The platform accepted the run but returned no run id", response_body=body)
    return WorkflowRun.model_validate(
        {
            "id": run_id,
            "workflowId": result.get("workflowId"),
            "status": status.get("status") or "QUEUED",
            "error": status.get("error") or result.get("error"),
            "value": status.get("value"),
            "finalOutputUrl": result.get("finalOutputUrl"),
        }
    )


def parse_page(body: Any) -> tuple[list[Any], PageInfo]:
    """A list response: ``{"data": [...], "pagination": {...}}``."""
    if not isinstance(body, dict):
        return [], PageInfo()
    items = body.get("data")
    if items is None:
        items = body.get("content", [])
    pagination = body.get("pagination") or body.get("pageInfo") or {}
    return list(items or []), PageInfo.model_validate(pagination)


def decode_output(raw: Any, max_depth: int = 4) -> Any:
    """
    The workflow's result, decoded.

    The stored result is JSON whose value is often itself a JSON document encoded as a string -
    sometimes twice. Decode until the value is no longer a string holding JSON.
    """
    value: Any = raw
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    for _ in range(max_depth):
        if not isinstance(value, str):
            break
        text = value.strip()
        if not text or text[0] not in '{["':
            break
        try:
            value = json.loads(text)
        except ValueError:
            break
    return value


def fresh_output_url(refreshed: Any, run: WorkflowRun) -> Optional[str]:
    """Pick the result's link out of a ``refresh-presigned-urls`` answer."""
    if not isinstance(refreshed, dict):
        return None
    urls = refreshed.get("presignedUrls") or {}
    if not isinstance(urls, dict) or not urls:
        return None
    if run.final_output_ref and run.final_output_ref in urls:
        return str(urls[run.final_output_ref])
    for ref, url in urls.items():
        if "final-output" in str(ref):
            return str(url)
    return None

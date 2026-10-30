"""Contract tests: every public SDK call against the platform's real routes and reply shapes.

Each fixture below is built from the server DTO named in its docstring (repo and path at
origin/main, 2026-10-30). The HTTP layer is mocked with pytest-httpx; nothing here reaches a real
server.
"""

import json
import re
from uuid import uuid4

import httpx
import pytest

from workstudio import AsyncClient, Client
from workstudio.exceptions import AuthenticationError, NotFoundError
from workstudio.models import Agent, AgentSession, MessageStatus, RunStatus, Workflow

BASE = "http://ws.test"
API = f"{BASE}/api/v1/workflow"

TENANT_ID = "0199aa00-0000-7000-8000-000000000001"
ENV_ID = "0199aa00-0000-7000-8000-000000000002"
WORKFLOW_ID = "0199aa00-0000-7000-8000-0000000000a1"  # portal row id
GLOBAL_ID = "0199aa00-0000-7000-8000-0000000000b1"  # globalUniqueId
RUN_ID = "0199aa00-0000-7000-8000-0000000000c1"
AGENT_ID = "0199aa00-0000-7000-8000-0000000000d1"
AGENT_GLOBAL_ID = "0199aa00-0000-7000-8000-0000000000d2"
SESSION_ID = "0199aa00-0000-7000-8000-0000000000e1"


# ---------------------------------------------------------------------------------------------
# Fixtures derived from server DTOs
# ---------------------------------------------------------------------------------------------


def execute_async_reply(status: str = "QUEUED") -> dict:
    """
    ``POST /execute/{slug}?async=true`` and ``/execute/id/{gid}?async=true``.

    DTO: base-api-contracts src/main/java/com/svai/workflow/contract/common/dto/
    WorkflowRouterRunStatusWithResultDto.java {runStatus, executionResult} (+ BaseDto fields, null),
    runStatus = WorkflowRouterRunStatusDto.java (routeRun, vpcId, infraType, callbackUrl,
    additionalInfo, error, value, status), executionResult = WorkflowExecutionResult.java
    (@JsonInclude NON_NULL). Built by trigger src/main/java/com/svai/workflow/trigger/util/
    TriggerWorkflowUtil.java executeWorkflowAsync (routeRun + status of the created run; runId,
    workflowId (row id), tenantId, envId, debugMode).
    """
    nulls = {
        k: None
        for k in (
            "id",
            "tenantId",
            "envId",
            "createdAt",
            "updatedAt",
            "createdBy",
            "updatedBy",
            "contractVersion",
        )
    }
    return {
        **nulls,
        "runStatus": {
            **nulls,
            "routeRun": RUN_ID,
            "vpcId": None,
            "infraType": None,
            "callbackUrl": None,
            "additionalInfo": None,
            "error": None,
            "value": None,
            "status": status,
        },
        "executionResult": {
            "tenantId": TENANT_ID,
            "envId": ENV_ID,
            "runId": RUN_ID,
            "workflowId": WORKFLOW_ID,
            "runtimeState": {},
            "debugMode": False,
        },
    }


def lifecycle_state_json(response) -> str:
    """
    A run's inline ``value``: the engine's terminal state as JSON text.

    DTO: base-api-contracts .../contract/common/dto/WorkflowExecuteLifeCycleState (value,
    currentState, workflowId, currentStep, response, error, startTime, endTime, failed, canceled,
    stepFailed); set on the run by run src/main/java/com/svai/workflow/run/service/
    WorkflowWaitFacade.java (dto.setValue(event.getOutputJson())).
    """
    return json.dumps(
        {
            "value": None,
            "currentState": "FINISHED",
            "workflowId": WORKFLOW_ID,
            "currentStep": "end",
            "response": response,
            "error": None,
            "startTime": "2026-10-30T15:04:05.123Z",
            "endTime": "2026-10-30T15:04:06.623Z",
        }
    )


def run_dto(status: str = "FINISHED", value=None, external_id=None) -> dict:
    """
    ``GET /run/{id}``, ``POST /run/{id}/wait``, items of ``GET /run``.

    DTO: run src/main/java/com/svai/workflow/run/service/dto/WorkflowRunDto.java (extends
    base-multi-tenant BaseDTO: tenantId, envId, id, createdAt, updatedAt, createdBy, updatedBy). No
    NON_NULL, so absent values are nulls. startedAt / finishedAt use
    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSSZ") - an offset without a colon. status is
    WorkflowRun.Status (QUEUED, PARSING, PENDING, RUNNING, WAITING_HUMAN, FAILED, CANCELLED,
    TERMINATED, FINISHED). inputData is the input as JSON text; there is no "outputs" field.
    """
    ended = status in ("FINISHED", "FAILED", "CANCELLED", "TERMINATED")
    return {
        "tenantId": TENANT_ID,
        "envId": ENV_ID,
        "id": RUN_ID,
        "createdAt": "2026-10-30T15:04:05.001Z",
        "updatedAt": "2026-10-30T15:04:06.700Z",
        "createdBy": None,
        "updatedBy": None,
        "workflowId": WORKFLOW_ID,
        "workflowGlobalUniqueId": GLOBAL_ID,
        "workflowVersion": 3,
        "workflowName": "Order intake",
        "inputData": json.dumps(
            {"order": 13} if external_id is None else {"order": 13, "externalId": external_id}
        ),
        "triggerType": "SYSTEM",
        "triggerIdentifier": "trigger-service",
        "triggerMetadata": None,
        "externalId": external_id,
        "idempotencyKey": None,
        "dispatchRefused": None,
        "dispatchClaimedAt": None,
        "startedAt": "2026-10-30T15:04:05.123+0000",
        "finishedAt": "2026-10-30T15:04:06.623+0000" if ended else None,
        "error": "Step charge: card declined" if status == "FAILED" else None,
        "status": status,
        "value": value,
        "waitInfo": (
            {
                "waitType": "APPROVAL",
                "stepId": "approve",
                "stepName": "Approve",
                "stepType": "HUMAN",
                "label": "Approve order",
                "awaitingHumanAction": True,
            }
            if status == "WAITING_HUMAN"
            else None
        ),
        "syncMode": False,
        "debugMode": False,
        "steps": [],
        "checkpointRef": None,
        "finalOutputRef": "runs/x/final-output.json",
        "runtimeStateRef": None,
        "checkpointUrl": None,
        "finalOutputUrl": "https://files.test/final-output.json" if ended else None,
        "runtimeStateUrl": None,
        "stepOutputUrls": None,
        "scopeId": None,
        "scopeKey": "customer:acme",
        "executionIdentity": None,
        "startedByApiKeyId": "0199aa00-0000-7000-8000-0000000000f1",
        "privateToUserId": None,
        "parentRunId": None,
    }


def page(items, page_no=0, size=20, total=None) -> dict:
    """
    Every list route. DTO: base-common src/main/java/com/svai/basecommon/search/PageResponse.java
    {data, pagination{page, size, totalElements, totalPages, hasNext, hasPrevious}}.
    """
    total = len(items) if total is None else total
    return {
        "data": items,
        "pagination": {
            "page": page_no,
            "size": size,
            "totalElements": total,
            "totalPages": 1 if total else 0,
            "hasNext": False,
            "hasPrevious": False,
        },
    }


def workflow_dto() -> dict:
    """
    ``GET /portal/{id}``, ``/portal/by-endpoint/{e}``, list items, for a key with workflow:read.

    DTO: portal src/main/java/com/svai/wfpbe/service/dto/WorkflowDto.java (extends BaseDTO; name,
    endpoint, description, latestVersion, currentVersion (WorkflowVersionDto: id, definition,
    status, workflowVersion, triggers), globalUniqueId, ownerType, connectorKeys, category, tags,
    hasUnpublishedChanges, access, personalOwnerUserId, personalOwnerSource). No top-level status
    or version.
    """
    return {
        "tenantId": TENANT_ID,
        "envId": ENV_ID,
        "id": WORKFLOW_ID,
        "createdAt": "2026-10-01T09:00:00Z",
        "updatedAt": "2026-10-29T09:00:00Z",
        "createdBy": "owner@example.com",
        "updatedBy": None,
        "name": "Order intake",
        "endpoint": "order-intake",
        "description": "Takes orders",
        "latestVersion": 3,
        "currentVersion": {
            "id": str(uuid4()),
            "definition": "{}",
            "status": "PUBLISHED",
            "workflowVersion": 3,
            "triggers": [],
        },
        "globalUniqueId": GLOBAL_ID,
        "ownerType": "TENANT",
        "connectorKeys": ["stripe"],
        "category": None,
        "tags": None,
        "hasUnpublishedChanges": False,
        "access": {"canEdit": True},
        "personalOwnerUserId": None,
        "personalOwnerSource": None,
    }


def workflow_summary_dto() -> dict:
    """
    The same reads for a key with workflow:execute only.

    DTO: portal src/main/java/com/svai/wfpbe/service/dto/WorkflowSummaryDto.java (id,
    globalUniqueId, name, description, endpoint, latestVersion, status, inputs, createdAt,
    updatedAt); chosen by WorkflowPortalController.forCaller.
    """
    return {
        "id": WORKFLOW_ID,
        "globalUniqueId": GLOBAL_ID,
        "name": "Order intake",
        "description": "Takes orders",
        "endpoint": "order-intake",
        "latestVersion": 3,
        "status": "PUBLISHED",
        "inputs": {"order": {"type": "number"}},
        "createdAt": "2026-10-01T09:00:00Z",
        "updatedAt": "2026-10-29T09:00:00Z",
    }


def agent_dto() -> dict:
    """
    ``GET /catalog/ai-agents``, ``/by-id/{id}``, ``/{globalUniqueId}``.

    DTO: catalog src/main/java/com/svai/workflow/catalog/service/dto/AIAgentUnifiedDto.java
    (extends BaseDTO; name, description, provider, managementType, ownerType, agentStatus
    (base-common AgentStatus), modelId, systemPrompt, maxTokens, temperature, globalUniqueId,
    active, toolCount, knowledgeBaseCount, guardrailCount, guardrails, knowledgeBases ...). No
    displayName, status, instructions, modelProvider, toolsEnabled or knowledgeBaseEnabled.
    """
    return {
        "tenantId": TENANT_ID,
        "envId": ENV_ID,
        "id": AGENT_ID,
        "createdAt": "2026-09-01T09:00:00Z",
        "updatedAt": "2026-10-20T09:00:00Z",
        "createdBy": None,
        "updatedBy": None,
        "name": "sales-assistant",
        "description": "Answers deal questions",
        "provider": "AWS_BEDROCK",
        "managementType": "MANAGED",
        "ownerType": "TENANT",
        "externalAgentId": None,
        "agentStatus": "PREPARED",
        "defaultConnectionId": None,
        "llmProviderId": None,
        "llmProviderIssue": None,
        "modelId": "claude-sonnet-5-5",
        "systemPrompt": "You help the sales team.",
        "maxTokens": 4096,
        "temperature": None,
        "configuration": None,
        "globalUniqueId": AGENT_GLOBAL_ID,
        "active": True,
        "release": None,
        "releaseStatus": None,
        "maxIterations": 10,
        "guardrailCount": 0,
        "knowledgeBaseCount": 1,
        "toolCount": 2,
        "guardrails": [],
        "knowledgeBases": [],
        "warnings": None,
    }


def session_started() -> dict:
    """
    ``POST /ai-runtime/agent-conversation/sessions`` (201).

    DTO: ai-runtime src/main/java/com/svai/workflow/studio/runtime/dto/AgentTestDto.java
    TestSessionResponse (sessionId, agentId, agentName, status, createdAt, expiresAt, config,
    errorMessage, resumedFromSessionId, resumedTurnCount).
    """
    return {
        "sessionId": SESSION_ID,
        "agentId": AGENT_ID,
        "agentName": "sales-assistant",
        "status": "ACTIVE",
        "createdAt": "2026-10-30T15:00:00Z",
        "expiresAt": "2026-10-30T16:00:00Z",
        "config": {
            "modelProvider": "AWS_BEDROCK",
            "modelName": "claude-sonnet-5-5",
            "temperature": 0.7,
            "maxTokens": 4096,
            "knowledgeBases": [],
            "guardrails": [],
            "tools": [],
        },
        "errorMessage": None,
        "resumedFromSessionId": None,
        "resumedTurnCount": None,
    }


def message_reply(status: str = "SUCCESS") -> dict:
    """
    ``POST /ai-runtime/agent-conversation/sessions/{id}/messages``.

    DTO: AgentTestDto.TestMessageResponse (sessionId, messageId, userMessage, assistantResponse,
    timestamp, metrics (TestMetrics), knowledgeBaseHits, toolExecutions, guardrailTriggers,
    errorMessage, errorCode, status: MessageStatus SUCCESS | ERROR | BLOCKED_BY_GUARDRAIL |
    TIMEOUT).
    """
    blocked = status == "BLOCKED_BY_GUARDRAIL"
    return {
        "sessionId": SESSION_ID,
        "messageId": "msg-1",
        "userMessage": "Top deals?",
        "assistantResponse": None if blocked else "Acme, 40k.",
        "timestamp": "2026-10-30T15:00:05Z",
        "metrics": {
            "latencyMs": 900,
            "timeToFirstTokenMs": 200,
            "inputTokens": 100,
            "outputTokens": 20,
            "totalTokens": 120,
            "estimatedCostUsd": 0.0012,
            "agentIterations": 1,
            "modelUsed": "claude-sonnet-5-5",
            "providerUsed": "AWS_BEDROCK",
        },
        "knowledgeBaseHits": None
        if blocked
        else [
            {
                "knowledgeBaseId": "kb-1",
                "knowledgeBaseName": "Deals",
                "documentTitle": "Q4",
                "chunkPreview": "Acme...",
                "relevanceScore": 0.91,
                "searchLatencyMs": 40,
            }
        ],
        "toolExecutions": []
        if blocked
        else [
            {
                "toolName": "crm_search",
                "toolType": "CONNECTOR",
                "input": {"q": "deals"},
                "output": {"n": 3},
                "durationMs": 120,
                "success": True,
                "errorMessage": None,
            }
        ],
        "guardrailTriggers": [
            {
                "guardrailName": "pii",
                "guardrailType": "PII",
                "triggerReason": "card number",
                "action": "BLOCK",
                "blocked": True,
            }
        ]
        if blocked
        else [],
        "errorMessage": "Blocked by guardrail" if blocked else None,
        "errorCode": "GUARDRAIL_BLOCKED" if blocked else None,
        "status": status,
    }


def session_state() -> dict:
    """
    ``GET /ai-runtime/agent-conversation/sessions/{id}``.

    DTO: AgentTestDto.TestSessionStateResponse (sessionId, agentId, status, createdAt, metrics
    (SessionMetrics: messageCount, totalInputTokens, totalOutputTokens, totalTokens, totalLatencyMs,
    avgLatencyMs, guardrailTriggerCount, toolCallCount, knowledgeBaseHitCount,
    totalEstimatedCostUsd), recentMessages). No totalTurns/totalTokens/totalCostUsd at the top.
    """
    return {
        "sessionId": SESSION_ID,
        "agentId": AGENT_ID,
        "status": "ACTIVE",
        "createdAt": "2026-10-30T15:00:00Z",
        "metrics": {
            "messageCount": 2,
            "totalInputTokens": 200,
            "totalOutputTokens": 40,
            "totalTokens": 240,
            "totalLatencyMs": 1800,
            "avgLatencyMs": 900,
            "guardrailTriggerCount": 0,
            "toolCallCount": 1,
            "knowledgeBaseHitCount": 1,
            "totalEstimatedCostUsd": 0.0024,
        },
        "recentMessages": [],
    }


def key_refusal(code: str = "TENANT_API_KEY_ONLY") -> dict:
    """
    A 403 for an API key. Body: base-http src/main/java/com/svai/entrycp/http/apikey/
    ApiKeyPermissionInterceptor.java writeRefusal
    {error, code, message, detail[, missingPermission]}.
    """
    return {
        "error": "PERMISSION_DENIED",
        "code": code,
        "message": "Customer API keys cannot read automation definitions",
        "detail": None,
    }


@pytest.fixture
def client():
    c = Client(api_key="svx_ck_test", base_url=BASE)
    yield c
    c.close()


def _calls(httpx_mock):
    return [(r.method, str(r.url)) for r in httpx_mock.get_requests()]


# ---------------------------------------------------------------------------------------------
# workflows.run
# ---------------------------------------------------------------------------------------------


class TestRun:
    def test_by_endpoint_name_starts_on_execute_then_waits(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{API}/execute/order-intake?async=true", json=execute_async_reply()
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/run/{RUN_ID}/wait?timeout=110000",
            json=run_dto("FINISHED", value=lifecycle_state_json({"accepted": True})),
        )

        run = client.workflows.run("order-intake", {"order": 13})

        assert _calls(httpx_mock) == [
            ("POST", f"{API}/execute/order-intake?async=true"),
            ("POST", f"{API}/run/{RUN_ID}/wait?timeout=110000"),
        ]
        start = httpx_mock.get_requests()[0]
        assert json.loads(start.content) == {"order": 13}
        assert start.headers["X-API-Key"] == "svx_ck_test"
        assert str(run.id) == RUN_ID
        assert str(run.workflow_id) == WORKFLOW_ID
        assert run.status == RunStatus.COMPLETED
        assert run.raw_status == "FINISHED"
        assert run.outputs == {"accepted": True}
        assert run.inputs == {"order": 13}
        assert run.final_output_url == "https://files.test/final-output.json"
        assert run.duration_ms == 1500
        # No definition read: a customer key may not make one, and running needs none.
        assert not any("/portal" in url for _, url in _calls(httpx_mock))

    def test_by_global_id_uses_execute_id(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/execute/id/{GLOBAL_ID}?async=true",
            json=execute_async_reply(),
        )
        run = client.workflows.run(GLOBAL_ID, sync=False)
        assert run.status == RunStatus.PENDING  # QUEUED
        assert run.raw_status == "QUEUED"
        assert str(run.id) == RUN_ID
        assert len(httpx_mock.get_requests()) == 1

    def test_row_id_is_looked_up_and_run_by_global_id(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/execute/id/{WORKFLOW_ID}?async=true",
            status_code=404,
            json={"message": f"Workflow not found: {WORKFLOW_ID}"},
        )
        httpx_mock.add_response(
            method="GET", url=f"{API}/portal/{WORKFLOW_ID}", json=workflow_summary_dto()
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/execute/id/{GLOBAL_ID}?async=true",
            json=execute_async_reply(),
        )
        run = client.workflows.run(WORKFLOW_ID, sync=False)
        assert str(run.id) == RUN_ID
        assert [u for _, u in _calls(httpx_mock)][-1] == f"{API}/execute/id/{GLOBAL_ID}?async=true"

    def test_unknown_uuid_raises_the_execute_404(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/execute/id/{GLOBAL_ID}?async=true",
            status_code=404,
            json={"message": f"Workflow not found: {GLOBAL_ID}"},
        )
        # A customer key may not read the definition: the lookup is refused, the 404 stands.
        httpx_mock.add_response(
            method="GET", url=f"{API}/portal/{GLOBAL_ID}", status_code=403, json=key_refusal()
        )
        with pytest.raises(NotFoundError, match="Workflow not found"):
            client.workflows.run(GLOBAL_ID)

    def test_unknown_endpoint_name_raises_not_found(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/execute/nope?async=true",
            status_code=404,
            json={"message": "No binding found for slug: nope"},
        )
        with pytest.raises(NotFoundError, match="No workflow with endpoint 'nope'"):
            client.workflows.run("nope")

    def test_external_id_rides_in_the_input(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{API}/execute/order-intake?async=true", json=execute_async_reply()
        )
        client.workflows.run("order-intake", {"order": 13}, sync=False, external_id="po-77")
        assert json.loads(httpx_mock.get_requests()[0].content) == {
            "order": 13,
            "externalId": "po-77",
        }

    def test_endpoint_name_is_encoded(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{API}/execute/a%2Fb%20c?async=true", json=execute_async_reply()
        )
        client.workflows.run("a/b c", sync=False)
        assert (
            httpx_mock.get_requests()[0].url.raw_path
            == b"/api/v1/workflow/execute/a%2Fb%20c?async=true"
        )

    def test_wait_408_keeps_waiting_until_the_run_ends(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{API}/execute/order-intake?async=true", json=execute_async_reply()
        )
        # 408 = still going, with the run as it stands
        # (run WorkflowRunController.waitForCompletion).
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/run/{RUN_ID}/wait?timeout=110000",
            status_code=408,
            json=run_dto("RUNNING"),
        )
        httpx_mock.add_response(
            method="POST", url=f"{API}/run/{RUN_ID}/wait?timeout=110000", json=run_dto("FAILED")
        )
        run = client.workflows.run("order-intake")
        assert run.status == RunStatus.FAILED
        assert run.error == "Step charge: card declined"

    def test_a_paused_run_is_returned_when_the_timeout_runs_out(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/execute/order-intake?async=true",
            json=execute_async_reply("RUNNING"),
        )
        # The wait asks for what is left of the timeout (about 1500 ms).
        httpx_mock.add_response(
            method="POST",
            url=re.compile(rf"{re.escape(API)}/run/{RUN_ID}/wait\?timeout=1[45]\d\d"),
            status_code=408,
            json=run_dto("WAITING_HUMAN"),
        )
        run = client.workflows.run("order-intake", timeout_seconds=1.5)
        assert run.status == RunStatus.WAITING
        assert run.raw_status == "WAITING_HUMAN"
        assert run.wait_info["stepId"] == "approve"

    def test_terminated_is_terminal(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{API}/execute/order-intake?async=true", json=execute_async_reply()
        )
        httpx_mock.add_response(
            method="POST", url=f"{API}/run/{RUN_ID}/wait?timeout=110000", json=run_dto("TERMINATED")
        )
        run = client.workflows.run("order-intake")
        assert run.status == RunStatus.CANCELLED
        assert run.raw_status == "TERMINATED"
        assert run.is_terminal


# ---------------------------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------------------------


class TestRuns:
    def test_get_run(self, client, httpx_mock):
        httpx_mock.add_response(method="GET", url=f"{API}/run/{RUN_ID}", json=run_dto("FINISHED"))
        run = client.workflows.get_run(RUN_ID)
        assert run.status == RunStatus.COMPLETED
        assert run.started_at.utcoffset().total_seconds() == 0
        assert run.completed_at is not None
        assert run.outputs is None  # GET /run never carries the result inline
        assert run.final_output_url == "https://files.test/final-output.json"
        assert run.scope_key == "customer:acme"
        assert str(run.workflow_global_unique_id) == GLOBAL_ID

    def test_unknown_status_is_kept_as_text(self, client, httpx_mock):
        body = run_dto("RUNNING")
        body["status"] = "SOMETHING_NEW"
        httpx_mock.add_response(method="GET", url=f"{API}/run/{RUN_ID}", json=body)
        assert client.workflows.get_run(RUN_ID).status == "SOMETHING_NEW"

    def test_list_runs_reads_data_and_pagination(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{API}/run?page=0&size=20&workflowId={WORKFLOW_ID}",
            json=page([run_dto("FINISHED"), run_dto("RUNNING")], total=2),
        )
        runs, info = client.workflows.list_runs(workflow_id=WORKFLOW_ID)
        assert [r.status for r in runs] == [RunStatus.COMPLETED, RunStatus.RUNNING]
        assert info.total_elements == 2

    def test_get_run_by_external_id(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{API}/run/by-external-id/po%2F77",
            json=run_dto("FINISHED", external_id="po/77"),
        )
        run = client.workflows.get_run_by_external_id("po/77")
        assert run.external_id == "po/77"

    def test_get_run_by_external_id_none_only_for_404(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{API}/run/by-external-id/missing",
            status_code=404,
            json={"message": "Workflow run not found"},
        )
        assert client.workflows.get_run_by_external_id("missing") is None
        httpx_mock.add_response(
            method="GET",
            url=f"{API}/run/by-external-id/x",
            status_code=403,
            json=key_refusal("MISSING_PERMISSION"),
        )
        with pytest.raises(AuthenticationError):
            client.workflows.get_run_by_external_id("x")


# ---------------------------------------------------------------------------------------------
# workflow definitions
# ---------------------------------------------------------------------------------------------


class TestDefinitions:
    def test_list_reads_data_and_pagination(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{API}/portal?page=0&size=20&search=order",
            json=page([workflow_dto()], total=1),
        )
        workflows, info = client.workflows.list(search="order")
        assert len(workflows) == 1 and info.total_elements == 1
        wf = workflows[0]
        assert wf.version == 3 and wf.status == "PUBLISHED"
        assert str(wf.global_unique_id) == GLOBAL_ID

    def test_get_summary_for_run_only_key(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET", url=f"{API}/portal/{WORKFLOW_ID}", json=workflow_summary_dto()
        )
        wf = client.workflows.get(WORKFLOW_ID)
        assert isinstance(wf, Workflow)
        assert wf.inputs == {"order": {"type": "number"}}
        assert wf.version == 3

    def test_get_by_endpoint(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET", url=f"{API}/portal/by-endpoint/order-intake", json=workflow_dto()
        )
        assert client.workflows.get_by_endpoint("order-intake").endpoint == "order-intake"

    def test_customer_key_refusal_is_an_authentication_error_with_the_platform_message(
        self, client, httpx_mock
    ):
        httpx_mock.add_response(
            method="GET", url=f"{API}/portal?page=0&size=20", status_code=403, json=key_refusal()
        )
        with pytest.raises(
            AuthenticationError, match="Customer API keys cannot read automation definitions"
        ):
            client.workflows.list()


# ---------------------------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------------------------

RT = f"{API}/ai-runtime/agent-conversation"
CAT = f"{API}/catalog/ai-agents"


class TestAgents:
    def test_list(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET", url=f"{CAT}?page=0&size=20&active=true", json=page([agent_dto()])
        )
        agents, info = client.agents.list(active=True)
        assert info.total_elements == 1
        a = agents[0]
        assert isinstance(a, Agent)
        assert a.instructions == "You help the sales team."
        assert a.model_provider == "AWS_BEDROCK"
        assert a.tools_enabled and a.knowledge_base_enabled
        assert a.temperature == 0.7  # null on the platform: the SDK default
        assert str(a.global_unique_id) == AGENT_GLOBAL_ID and a.active is True

    def test_list_status_is_deprecated_and_not_sent(self, client, httpx_mock):
        httpx_mock.add_response(method="GET", url=f"{CAT}?page=0&size=20", json=page([]))
        with pytest.warns(DeprecationWarning):
            client.agents.list(status="PUBLISHED")

    def test_get_by_row_id(self, client, httpx_mock):
        httpx_mock.add_response(method="GET", url=f"{CAT}/by-id/{AGENT_ID}", json=agent_dto())
        assert str(client.agents.get(AGENT_ID).id) == AGENT_ID

    def test_get_by_global_id_falls_back(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{CAT}/by-id/{AGENT_GLOBAL_ID}",
            status_code=404,
            json={"message": "AI Agent not found"},
        )
        httpx_mock.add_response(method="GET", url=f"{CAT}/{AGENT_GLOBAL_ID}", json=agent_dto())
        assert str(client.agents.get(AGENT_GLOBAL_ID).id) == AGENT_ID

    def test_session_lifecycle(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url=f"{CAT}?page=0&size=50&search=sales-assistant",
            json=page([agent_dto()]),
        )
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions", status_code=201, json=session_started()
        )
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions/{SESSION_ID}/messages", json=message_reply()
        )
        httpx_mock.add_response(
            method="GET", url=f"{RT}/sessions/{SESSION_ID}", json=session_state()
        )
        httpx_mock.add_response(method="DELETE", url=f"{RT}/sessions/{SESSION_ID}", status_code=204)

        with client.agents.create_session("sales-assistant") as session:
            reply = session.send_message("Top deals?")
            state = session.get_state()

        reqs = httpx_mock.get_requests()
        assert json.loads(reqs[1].content) == {"agentId": AGENT_ID}
        assert json.loads(reqs[2].content) == {"message": "Top deals?"}
        assert (reqs[-1].method, str(reqs[-1].url)) == ("DELETE", f"{RT}/sessions/{SESSION_ID}")
        assert reply.status == MessageStatus.SUCCESS and reply.message == "Acme, 40k."
        assert reply.tools_used == ["crm_search"] and reply.knowledge_sources_used == ["Deals"]
        assert isinstance(state, AgentSession)
        assert (
            state.total_turns == 2 and state.total_tokens == 240 and state.total_cost_usd == 0.0024
        )

    def test_guardrail_block_parses(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions", status_code=201, json=session_started()
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{RT}/sessions/{SESSION_ID}/messages",
            json=message_reply("BLOCKED_BY_GUARDRAIL"),
        )
        httpx_mock.add_response(method="DELETE", url=f"{RT}/sessions/{SESSION_ID}", status_code=204)
        reply = client.agents.chat(AGENT_ID, "card 4111...")
        assert reply.status == MessageStatus.BLOCKED_BY_GUARDRAIL
        assert reply.guardrail_triggers[0]["blocked"] is True
        assert reply.knowledge_base_hits == [] and reply.error_code == "GUARDRAIL_BLOCKED"

    def test_expired_session_message_is_not_found_with_its_reason(self, client, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions", status_code=201, json=session_started()
        )
        body = message_reply("ERROR")
        body["errorMessage"] = "Session not found or expired"
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions/{SESSION_ID}/messages", status_code=404, json=body
        )
        httpx_mock.add_response(method="DELETE", url=f"{RT}/sessions/{SESSION_ID}", status_code=204)
        with pytest.raises(NotFoundError, match="Session not found or expired"):
            client.agents.chat(AGENT_ID, "hi")


# ---------------------------------------------------------------------------------------------
# async client
# ---------------------------------------------------------------------------------------------


class TestAsyncClient:
    @pytest.mark.asyncio
    async def test_run_and_lists(self, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{API}/execute/order-intake?async=true", json=execute_async_reply()
        )
        httpx_mock.add_response(
            method="POST",
            url=f"{API}/run/{RUN_ID}/wait?timeout=110000",
            json=run_dto("FINISHED", value=lifecycle_state_json("done")),
        )
        httpx_mock.add_response(
            method="GET", url=f"{API}/run?page=0&size=20", json=page([run_dto("FINISHED")])
        )
        httpx_mock.add_response(method="GET", url=f"{CAT}?page=0&size=20", json=page([agent_dto()]))
        async with AsyncClient(api_key="svx_tk_test", base_url=BASE) as client:
            run = await client.workflows.run("order-intake")
            runs, _ = await client.workflows.list_runs()
            agents, _ = await client.agents.list()
        assert run.status == RunStatus.COMPLETED and run.outputs == {"response": "done"}
        assert len(runs) == 1 and len(agents) == 1

    @pytest.mark.asyncio
    async def test_session_end_is_delete(self, httpx_mock):
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions", status_code=201, json=session_started()
        )
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions/{SESSION_ID}/messages", json=message_reply()
        )
        httpx_mock.add_response(method="DELETE", url=f"{RT}/sessions/{SESSION_ID}", status_code=204)
        async with AsyncClient(api_key="svx_tk_test", base_url=BASE) as client:
            reply = await client.agents.chat(AGENT_ID, "Top deals?")
        assert reply.message == "Acme, 40k."
        assert httpx_mock.get_requests()[-1].method == "DELETE"


def test_wait_uses_a_read_timeout_longer_than_the_wait(httpx_mock):
    """The long poll may hold for 110 s; the client default (30 s) must not cut it."""
    seen = {}

    def answer(request: httpx.Request):
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=run_dto("FINISHED"))

    httpx_mock.add_response(
        method="POST", url=f"{API}/execute/order-intake?async=true", json=execute_async_reply()
    )
    httpx_mock.add_callback(answer, method="POST", url=f"{API}/run/{RUN_ID}/wait?timeout=110000")
    with Client(api_key="svx_tk_test", base_url=BASE) as c:
        c.workflows.run("order-intake")
    assert seen["timeout"]["read"] >= 110

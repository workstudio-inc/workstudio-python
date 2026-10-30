"""
Data models for the work.studio SDK.

Each model reads the platform's own reply shape; the server DTO it mirrors is named in its
docstring.
"""

import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID

from pydantic import AliasChoices, BaseModel, BeforeValidator, Field, model_validator
from typing_extensions import Annotated


def _lenient_datetime(value: Any) -> Any:
    """
    Accept the timestamp shapes the platform sends.

    The run service writes ``startedAt`` / ``finishedAt`` as ``2026-10-30T12:00:00.000+0000``
    (``@JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSSZ")`` on run ``WorkflowRunDto``): no colon in
    the offset, which some pydantic 2.x releases refuse. Other fields are ISO-8601.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000.0 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    return value


Timestamp = Annotated[Optional[datetime], BeforeValidator(_lenient_datetime)]


def _decode_json(value: Any) -> Any:
    """A JSON document the platform sent as text, decoded; anything else as it is."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


# ============================================================
# Enums
# ============================================================


class RunStatus(str, Enum):
    """
    Status of a workflow run.

    The run service's own statuses (run ``WorkflowRun.Status``: QUEUED, PARSING, PENDING, RUNNING,
    WAITING_HUMAN, FAILED, CANCELLED, TERMINATED, FINISHED) parse onto these: FINISHED is
    ``COMPLETED``, WAITING_HUMAN is ``WAITING``, QUEUED and PARSING are ``PENDING``, TERMINATED is
    ``CANCELLED``. ``WorkflowRun.raw_status`` keeps the platform's word.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"

    @property
    def is_terminal(self) -> bool:
        """The run has ended and will not change again."""
        return self in TERMINAL_RUN_STATUSES

    @classmethod
    def _missing_(cls, value: object) -> Optional["RunStatus"]:
        """The run service's own words for these states (FINISHED, WAITING_HUMAN, QUEUED, ...)."""
        if not isinstance(value, str):
            return None
        return _RUN_STATUS_ALIASES.get(value.strip().upper())


# The statuses the run service reports, mapped onto the SDK's.
_RUN_STATUS_ALIASES = {
    "FINISHED": RunStatus.COMPLETED,
    "SUCCESS": RunStatus.COMPLETED,
    "SUCCEEDED": RunStatus.COMPLETED,
    "QUEUED": RunStatus.PENDING,
    "PARSING": RunStatus.PENDING,
    "CREATED": RunStatus.PENDING,
    "STARTED": RunStatus.RUNNING,
    "WAITING_HUMAN": RunStatus.WAITING,
    "WAITING_FOR_HUMAN": RunStatus.WAITING,
    "WAITING_CALLBACK": RunStatus.WAITING,
    "WAITING_FOR_CALLBACK": RunStatus.WAITING,
    "WAITING_FOR_AGENT": RunStatus.WAITING,
    "PAUSED": RunStatus.WAITING,
    "ERROR": RunStatus.FAILED,
    "TERMINATED": RunStatus.CANCELLED,
    "CANCELED": RunStatus.CANCELLED,
    "TIMEOUT": RunStatus.TIMED_OUT,
}
for _status in RunStatus:
    _RUN_STATUS_ALIASES.setdefault(_status.value, _status)

#: The statuses a run ends in (the run service's FINISHED, FAILED, CANCELLED, TERMINATED).
TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TIMED_OUT}
)


class AgentStatus(str, Enum):
    """
    Status of an agent (SDK 0.1 vocabulary).

    The platform has no such field: an agent has ``active`` and ``agentStatus`` (base-common
    ``AgentStatus``: CREATING, NOT_PREPARED, PREPARING, PREPARED, UPDATING, FAILED, DELETING,
    DELETED), which ``Agent.active`` and ``Agent.agent_status`` carry. Kept so code importing it
    keeps working.
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class MessageStatus(str, Enum):
    """Status of an agent message response (ai-runtime ``AgentTestDto.MessageStatus``)."""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    BLOCKED_BY_GUARDRAIL = "BLOCKED_BY_GUARDRAIL"
    TIMEOUT = "TIMEOUT"


# ============================================================
# Base Models
# ============================================================


class BaseResource(BaseModel):
    """Base model for all API resources."""

    id: UUID
    created_at: Timestamp = Field(default=None, alias="createdAt")
    updated_at: Timestamp = Field(default=None, alias="updatedAt")

    model_config = {"populate_by_name": True}


# ============================================================
# Workflow Models
# ============================================================


class Workflow(BaseResource):
    """
    A workflow definition, as ``GET /portal`` and ``GET /portal/{id}`` return it.

    A key holding ``workflow:read`` gets the whole definition (portal ``WorkflowDto``); a key that
    may only run workflows gets a summary (portal ``WorkflowSummaryDto``: id, globalUniqueId, name,
    description, endpoint, latestVersion, status, inputs). Both parse.
    """

    name: str
    description: Optional[str] = None
    endpoint: Optional[str] = None
    #: The latest version number (the platform's ``latestVersion``).
    version: int = 1
    #: The current version's status (DRAFT, PUBLISHED ...).
    status: Optional[str] = None

    #: The id the workflow keeps across environments; ``/execute/id/{id}`` runs it.
    global_unique_id: Optional[UUID] = Field(default=None, alias="globalUniqueId")
    latest_version: Optional[int] = Field(default=None, alias="latestVersion")
    #: Input name to its UI spec (summary reads only).
    inputs: Optional[dict[str, Any]] = None
    owner_type: Optional[str] = Field(default=None, alias="ownerType")

    # Scope binding (for customer API keys)
    scope_id: Optional[UUID] = Field(default=None, alias="scopeId")
    tenant_id: Optional[UUID] = Field(default=None, alias="tenantId")
    env_id: Optional[UUID] = Field(default=None, alias="envId")

    @model_validator(mode="before")
    @classmethod
    def _from_portal(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("version") is None and data.get("latestVersion") is not None:
            data["version"] = data["latestVersion"]
        if data.get("version") is None:
            data.pop("version", None)
        current = data.get("currentVersion")
        if data.get("status") is None and isinstance(current, dict) and current.get("status"):
            data["status"] = current["status"]
        return data


class WorkflowRun(BaseResource):
    """
    A workflow execution instance.

    Read from the run service's run (run ``WorkflowRunDto``: ``GET /run/{id}``,
    ``POST /run/{id}/wait``, ``GET /run``) or from a start reply (``{runStatus, executionResult}``,
    base-api-contracts ``WorkflowRouterRunStatusWithResultDto``); see :meth:`from_api`.

    ``status`` is a :class:`RunStatus` (an unknown status stays its string); ``raw_status`` is the
    platform's own word. ``outputs`` is filled when the platform hands the result back inline (a
    wait that saw the run end); otherwise the result is behind ``final_output_url``.
    """

    workflow_id: Optional[UUID] = Field(default=None, alias="workflowId")
    workflow_name: Optional[str] = Field(default=None, alias="workflowName")
    # left_to_right: a known word becomes a RunStatus; only an unknown one stays a string.
    status: Union[RunStatus, str] = Field(union_mode="left_to_right")
    #: The status exactly as the platform reported it (FINISHED, WAITING_HUMAN, TERMINATED ...).
    raw_status: Optional[str] = Field(default=None, alias="rawStatus")
    inputs: Optional[dict[str, Any]] = None
    outputs: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    #: The run's state/result as the platform sent it inline (JSON text), when it did.
    value: Optional[str] = None

    # Timing
    started_at: Timestamp = Field(default=None, alias="startedAt")
    completed_at: Timestamp = Field(
        default=None,
        validation_alias=AliasChoices("completedAt", "finishedAt", "completed_at"),
        serialization_alias="completedAt",
    )
    duration_ms: Optional[int] = Field(default=None, alias="durationMs")

    # External correlation
    external_id: Optional[str] = Field(default=None, alias="externalId")

    # Where the run's full output and state can be fetched (signed, short-lived URLs)
    final_output_url: Optional[str] = Field(default=None, alias="finalOutputUrl")
    runtime_state_url: Optional[str] = Field(default=None, alias="runtimeStateUrl")

    # More of the run service's run
    workflow_global_unique_id: Optional[UUID] = Field(default=None, alias="workflowGlobalUniqueId")
    workflow_version: Optional[int] = Field(default=None, alias="workflowVersion")
    #: Why a WAITING run is paused (``waitType``, ``stepId``, ``stepName`` ...).
    wait_info: Optional[dict[str, Any]] = Field(default=None, alias="waitInfo")
    scope_key: Optional[str] = Field(default=None, alias="scopeKey")
    trigger_type: Optional[str] = Field(default=None, alias="triggerType")
    parent_run_id: Optional[UUID] = Field(default=None, alias="parentRunId")

    @model_validator(mode="before")
    @classmethod
    def _from_run_service(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        status = data.get("status")
        if isinstance(status, str) and data.get("rawStatus") is None:
            data["rawStatus"] = status
        # inputData is the input as JSON text.
        if data.get("inputs") is None and data.get("inputData") is not None:
            decoded = _decode_json(data["inputData"])
            data["inputs"] = decoded if isinstance(decoded, dict) else {"input": decoded}
        if data.get("outputs") is None and data.get("value") is not None:
            data["outputs"] = _outputs_from_value(data["value"])
        if data.get("value") is not None and not isinstance(data["value"], str):
            data["value"] = json.dumps(data["value"])
        return data

    @model_validator(mode="after")
    def _duration(self) -> "WorkflowRun":
        if self.duration_ms is None and self.started_at and self.completed_at:
            self.duration_ms = int((self.completed_at - self.started_at).total_seconds() * 1000)
        return self

    @property
    def is_terminal(self) -> bool:
        """The run has ended (FINISHED, FAILED, CANCELLED or TERMINATED)."""
        return isinstance(self.status, RunStatus) and self.status.is_terminal

    @classmethod
    def from_api(cls, data: Any) -> "WorkflowRun":
        """
        A run from any of the API's run replies.

        ``POST /execute/...`` and the portal's ``PUT /portal/{id}/run`` answer
        ``{runStatus, executionResult}`` (``WorkflowRouterRunStatusWithResultDto``), with the run
        id, the status and the run's state inside them; the run service's own endpoints answer a
        run with ``id``, ``workflowId`` and ``status`` at the top. Both become a WorkflowRun.
        """
        if (
            isinstance(data, dict)
            and ("runStatus" in data or "executionResult" in data)
            and not data.get("workflowId")
        ):
            data = _run_status_with_result(data)
        return cls.model_validate(data)


def _run_status_with_result(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``{runStatus, executionResult}`` into a run's fields."""
    status = data.get("runStatus") or {}
    result = data.get("executionResult") or {}
    raw_value = status.get("value")
    state: Any = _decode_json(raw_value)
    if not isinstance(state, dict):
        state = {}

    error = status.get("error") or state.get("error") or result.get("error")
    if error is not None and not isinstance(error, str):
        error = json.dumps(error)

    return {
        "id": result.get("runId") or status.get("routeRun") or state.get("runId") or data.get("id"),
        "workflowId": result.get("workflowId") or state.get("workflowId"),
        "workflowName": state.get("workflowName"),
        "status": status.get("status") or state.get("currentState") or RunStatus.RUNNING.value,
        "outputs": _outputs_from_value(raw_value) if raw_value is not None else None,
        "value": raw_value if isinstance(raw_value, str) else None,
        "error": error,
        "startedAt": state.get("startTime"),
        "completedAt": state.get("endTime"),
        "finalOutputUrl": result.get("finalOutputUrl"),
        "runtimeStateUrl": result.get("runtimeStateUrl"),
    }


def _outputs_from_value(value: Any) -> Optional[dict[str, Any]]:
    """
    The result out of a run's inline ``value``.

    The value is the engine's lifecycle state as JSON text (base-api-contracts
    ``WorkflowExecuteLifeCycleState``: currentState, response, error, startTime, endTime ...); its
    ``response`` is the run's result. A value that is not such a state is taken as the result.
    """
    decoded = _decode_json(value)
    if decoded is None or decoded == "":
        return None
    if isinstance(decoded, dict) and ("currentState" in decoded or "response" in decoded):
        decoded = decoded.get("response")
        if decoded is None:
            return None
    return decoded if isinstance(decoded, dict) else {"response": decoded}


class WorkflowRunRequest(BaseModel):
    """
    Request to run a workflow.

    Not sent by the SDK and not a body the platform takes: ``workflows.run()`` posts the inputs
    themselves (with ``externalId`` among them) to ``/execute/...``. Kept for compatibility.
    """

    workflow_id: Optional[UUID] = Field(default=None, alias="workflowId")
    workflow_endpoint: Optional[str] = Field(default=None, alias="workflowEndpoint")
    inputs: dict[str, Any] = Field(default_factory=dict)
    sync_mode: bool = Field(default=False, alias="syncMode")
    timeout_seconds: int = Field(default=300, alias="timeoutSeconds")
    external_id: Optional[str] = Field(default=None, alias="externalId")

    model_config = {"populate_by_name": True}


# ============================================================
# Agent Models
# ============================================================


class Agent(BaseResource):
    """
    An AI agent definition, as catalog ``/ai-agents`` returns it (catalog ``AIAgentUnifiedDto``).

    ``id`` is the agent's row id; ``global_unique_id`` is the id it keeps across environments.
    """

    name: str
    display_name: Optional[str] = Field(default=None, alias="displayName")
    description: Optional[str] = None
    #: SDK 0.1 field with no platform counterpart; see ``active`` and ``agent_status``.
    status: AgentStatus = AgentStatus.DRAFT
    #: The agent's system prompt (the platform's ``systemPrompt``).
    instructions: Optional[str] = None

    # Model configuration
    model_id: Optional[str] = Field(default=None, alias="modelId")
    #: The provider (the platform's ``provider``, e.g. AWS_BEDROCK).
    model_provider: Optional[str] = Field(default=None, alias="modelProvider")
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = Field(default=None, alias="maxTokens")

    # Capabilities
    tools_enabled: bool = Field(default=False, alias="toolsEnabled")
    knowledge_base_enabled: bool = Field(default=False, alias="knowledgeBaseEnabled")

    # The platform's own fields
    global_unique_id: Optional[UUID] = Field(default=None, alias="globalUniqueId")
    active: Optional[bool] = None
    agent_status: Optional[str] = Field(default=None, alias="agentStatus")
    tool_count: int = Field(default=0, alias="toolCount")
    knowledge_base_count: int = Field(default=0, alias="knowledgeBaseCount")

    @model_validator(mode="before")
    @classmethod
    def _from_catalog(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("instructions") is None and data.get("systemPrompt") is not None:
            data["instructions"] = data["systemPrompt"]
        if data.get("modelProvider") is None and data.get("provider") is not None:
            data["modelProvider"] = str(data["provider"])
        if "toolsEnabled" not in data and data.get("toolCount") is not None:
            data["toolsEnabled"] = data["toolCount"] > 0
        if "knowledgeBaseEnabled" not in data and data.get("knowledgeBaseCount") is not None:
            data["knowledgeBaseEnabled"] = data["knowledgeBaseCount"] > 0
        for key in ("temperature", "toolCount", "knowledgeBaseCount"):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class AgentSession(BaseModel):
    """
    An active conversation session with an agent.

    ai-runtime ``AgentTestDto.TestSessionStateResponse``.
    """

    session_id: UUID = Field(alias="sessionId")
    agent_id: Optional[UUID] = Field(default=None, alias="agentId")
    agent_name: Optional[str] = Field(default=None, alias="agentName")
    status: Optional[str] = "ACTIVE"
    created_at: Timestamp = Field(default=None, alias="createdAt")

    # Cumulative metrics, from the state's ``metrics`` (``AgentTestDto.SessionMetrics``:
    # messageCount, totalTokens, totalEstimatedCostUsd ...)
    total_turns: int = Field(default=0, alias="totalTurns")
    total_tokens: int = Field(default=0, alias="totalTokens")
    total_cost_usd: float = Field(default=0.0, alias="totalCostUsd")
    metrics: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _from_session_state(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        metrics = data.get("metrics")
        if isinstance(metrics, dict):
            if "totalTurns" not in data and metrics.get("messageCount") is not None:
                data["totalTurns"] = metrics["messageCount"]
            if "totalTokens" not in data and metrics.get("totalTokens") is not None:
                data["totalTokens"] = metrics["totalTokens"]
            if "totalCostUsd" not in data and metrics.get("totalEstimatedCostUsd") is not None:
                data["totalCostUsd"] = metrics["totalEstimatedCostUsd"]
        if data.get("status") is None:
            data.pop("status", None)
        return data


class MessageMetrics(BaseModel):
    """Metrics from an agent message response (ai-runtime ``AgentTestDto.TestMetrics``)."""

    latency_ms: int = Field(default=0, alias="latencyMs")
    time_to_first_token_ms: int = Field(default=0, alias="timeToFirstTokenMs")
    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    total_tokens: int = Field(default=0, alias="totalTokens")
    estimated_cost_usd: Optional[float] = Field(default=None, alias="estimatedCostUsd")
    agent_iterations: int = Field(default=0, alias="agentIterations")
    model_used: Optional[str] = Field(default=None, alias="modelUsed")
    provider_used: Optional[str] = Field(default=None, alias="providerUsed")

    model_config = {"populate_by_name": True}


class ToolExecution(BaseModel):
    """Details of a tool execution during agent processing (``AgentTestDto.ToolExecution``)."""

    tool_name: str = Field(alias="toolName")
    tool_type: Optional[str] = Field(default=None, alias="toolType")
    input: Optional[dict[str, Any]] = None
    output: Optional[Any] = None
    duration_ms: int = Field(default=0, alias="durationMs")
    success: bool = True
    error_message: Optional[str] = Field(default=None, alias="errorMessage")

    model_config = {"populate_by_name": True}


class KnowledgeBaseHit(BaseModel):
    """Knowledge base search hit details (``AgentTestDto.KnowledgeBaseHit``)."""

    knowledge_base_id: str = Field(alias="knowledgeBaseId")
    knowledge_base_name: Optional[str] = Field(default=None, alias="knowledgeBaseName")
    document_title: Optional[str] = Field(default=None, alias="documentTitle")
    chunk_preview: Optional[str] = Field(default=None, alias="chunkPreview")
    relevance_score: float = Field(default=0.0, alias="relevanceScore")
    search_latency_ms: int = Field(default=0, alias="searchLatencyMs")

    model_config = {"populate_by_name": True}


_LIST_FIELDS = ("toolExecutions", "knowledgeBaseHits", "guardrailTriggers")


class MessageResponse(BaseModel):
    """Response from sending a message to an agent (``AgentTestDto.TestMessageResponse``)."""

    status: MessageStatus
    message: Optional[str] = Field(default=None, alias="assistantResponse")
    user_message: Optional[str] = Field(default=None, alias="userMessage")
    message_id: Optional[str] = Field(default=None, alias="messageId")
    session_id: Optional[UUID] = Field(default=None, alias="sessionId")
    error_message: Optional[str] = Field(default=None, alias="errorMessage")
    error_code: Optional[str] = Field(default=None, alias="errorCode")
    timestamp: Timestamp = None

    # Detailed metrics
    metrics: Optional[MessageMetrics] = None

    # Tool and knowledge base usage
    tool_executions: list[ToolExecution] = Field(default_factory=list, alias="toolExecutions")
    knowledge_base_hits: list[KnowledgeBaseHit] = Field(
        default_factory=list, alias="knowledgeBaseHits"
    )
    #: Guardrails that fired (guardrailName, guardrailType, triggerReason, action, blocked).
    guardrail_triggers: list[dict[str, Any]] = Field(
        default_factory=list, alias="guardrailTriggers"
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _null_lists_are_empty(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if not (v is None and k in _LIST_FIELDS)}
        return data

    # Convenience properties for common metrics
    @property
    def prompt_tokens(self) -> int:
        """Alias for input tokens (backward compat)."""
        return self.metrics.input_tokens if self.metrics else 0

    @property
    def completion_tokens(self) -> int:
        """Alias for output tokens (backward compat)."""
        return self.metrics.output_tokens if self.metrics else 0

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.metrics.total_tokens if self.metrics else 0

    @property
    def latency_ms(self) -> int:
        """Response latency in milliseconds."""
        return self.metrics.latency_ms if self.metrics else 0

    @property
    def estimated_cost_usd(self) -> float:
        """Estimated cost in USD."""
        if self.metrics and self.metrics.estimated_cost_usd is not None:
            return self.metrics.estimated_cost_usd
        return 0.0

    @property
    def tools_used(self) -> list[str]:
        """List of tool names that were executed."""
        return [t.tool_name for t in self.tool_executions]

    @property
    def knowledge_sources_used(self) -> list[str]:
        """List of knowledge base names that were queried."""
        return [k.knowledge_base_name for k in self.knowledge_base_hits if k.knowledge_base_name]


class StartSessionRequest(BaseModel):
    """Request to start an agent session (``AgentTestDto.StartTestSessionRequest``)."""

    agent_id: UUID = Field(alias="agentId")

    model_config = {"populate_by_name": True}


class SendMessageRequest(BaseModel):
    """
    Request to send a message in a session (``AgentTestDto.TestMessageRequest``: message, context,
    activeSkillIds). ``include_debug`` is not a field the platform reads; debug details come back
    on every message of a session (``debugMode`` defaults to true when it starts).
    """

    message: str
    include_debug: bool = Field(default=False, alias="includeDebug")

    model_config = {"populate_by_name": True}


# ============================================================
# Pagination Models
# ============================================================


class PageInfo(BaseModel):
    """Pagination information (base-common ``PageResponse.PaginationInfo``)."""

    page: int = 0
    size: int = 20
    total_elements: int = Field(default=0, alias="totalElements")
    total_pages: int = Field(default=0, alias="totalPages")
    has_next: bool = Field(default=False, alias="hasNext")
    has_previous: bool = Field(default=False, alias="hasPrevious")

    model_config = {"populate_by_name": True}


def parse_page(body: Any) -> tuple[list[Any], PageInfo]:
    """
    The items and page info of a list reply.

    Every list route answers base-common ``PageResponse``: ``{"data": [...], "pagination": {page,
    size, totalElements, totalPages, hasNext, hasPrevious}}``. SDK 0.1 read ``content`` /
    ``pageInfo``, which the platform does not send, so its lists came back empty.
    """
    if not isinstance(body, dict):
        return [], PageInfo()
    items = body.get("data")
    if items is None:
        items = body.get("content")
    pagination = body.get("pagination") or body.get("pageInfo") or {}
    return list(items or []), PageInfo.model_validate(pagination)


class Page(BaseModel):
    """A page of results."""

    content: list[Any] = Field(
        default_factory=list, validation_alias=AliasChoices("data", "content")
    )
    page_info: PageInfo = Field(
        default_factory=PageInfo, validation_alias=AliasChoices("pagination", "pageInfo")
    )

    model_config = {"populate_by_name": True}

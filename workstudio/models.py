"""
Data models for the work.studio SDK.
"""

import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field, field_validator
from typing_extensions import Annotated


def _lenient_datetime(value: Any) -> Any:
    """
    Accept the timestamp shapes the platform actually sends.

    Run timestamps are written as ``2026-10-21T15:04:05.123+0000`` (no colon in the offset), other
    fields as ISO-8601 with ``Z``, and a few as epoch milliseconds.
    """
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    return value


LenientDatetime = Annotated[Optional[datetime], BeforeValidator(_lenient_datetime)]


# ============================================================
# Enums
# ============================================================


class RunStatus(str, Enum):
    """
    Status of a workflow run, exactly as the run service reports it.

    In progress: ``QUEUED``, ``PARSING``, ``PENDING``, ``RUNNING``. Paused: ``WAITING_HUMAN`` -
    every kind of pause (an approval, an agent command, a sub-workflow) reads as this one value; the
    run's ``wait_info`` says which. Ended: ``FINISHED`` (succeeded), ``FAILED``, ``CANCELLED``,
    ``TERMINATED``.

    ``COMPLETED`` and ``WAITING`` are kept as aliases of ``FINISHED`` and ``WAITING_HUMAN`` so code
    written against 0.1 keeps comparing correctly.
    """

    QUEUED = "QUEUED"
    PARSING = "PARSING"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_HUMAN = "WAITING_HUMAN"
    FINISHED = "FINISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"

    # 0.1 names, as aliases (same members, not new values).
    COMPLETED = "FINISHED"
    WAITING = "WAITING_HUMAN"

    @property
    def is_terminal(self) -> bool:
        """The run has ended and will not change again."""
        return self in _TERMINAL_STATUSES

    @property
    def succeeded(self) -> bool:
        return self is RunStatus.FINISHED


_TERMINAL_STATUSES = frozenset(
    {RunStatus.FINISHED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.TERMINATED}
)

#: Spellings other layers use for the same states, folded the way the run service folds them.
_STATUS_SYNONYMS = {
    "COMPLETED": "FINISHED",
    "SUCCESS": "FINISHED",
    "SUCCEEDED": "FINISHED",
    "PAUSED": "WAITING_HUMAN",
    "WAITING": "WAITING_HUMAN",
    "CANCELED": "CANCELLED",
}


def parse_run_status(value: Any) -> Union[RunStatus, str, None]:
    """A status as a :class:`RunStatus`; an unknown value is kept as its string, never rejected."""
    if value is None or isinstance(value, RunStatus):
        return value
    text = str(value).strip().upper()
    if not text:
        return None
    text = _STATUS_SYNONYMS.get(text, text)
    try:
        return RunStatus(text)
    except ValueError:
        return text


class AgentStatus(str, Enum):
    """Status of an agent."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class MessageStatus(str, Enum):
    """Status of an agent message response."""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


# ============================================================
# Base Models
# ============================================================


class BaseResource(BaseModel):
    """Base model for all API resources."""

    id: UUID
    created_at: Optional[datetime] = Field(default=None, alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")

    model_config = {"populate_by_name": True}


# ============================================================
# Workflow Models
# ============================================================


class Workflow(BaseResource):
    """A workflow definition."""

    name: str
    description: Optional[str] = None
    endpoint: Optional[str] = None
    version: int = 1
    status: Optional[str] = None

    # Scope binding (for customer API keys)
    scope_id: Optional[UUID] = Field(default=None, alias="scopeId")
    tenant_id: Optional[UUID] = Field(default=None, alias="tenantId")
    env_id: Optional[UUID] = Field(default=None, alias="envId")


class WorkflowRun(BaseModel):
    """
    One execution of a workflow, as ``GET /api/v1/workflow/run/{id}`` returns it.

    The result is not inline on a finished run: it is stored, and ``final_output_url`` is a
    short-lived presigned link to it. ``client.workflows.get_output(run)`` fetches and decodes it
    (and refreshes an expired link); ``client.workflows.run(...)`` does that for you and puts the
    decoded result in ``output``.
    """

    id: UUID
    workflow_id: Optional[UUID] = Field(default=None, alias="workflowId")
    workflow_global_unique_id: Optional[UUID] = Field(default=None, alias="workflowGlobalUniqueId")
    workflow_version: Optional[int] = Field(default=None, alias="workflowVersion")
    workflow_name: Optional[str] = Field(default=None, alias="workflowName")

    status: Union[RunStatus, str, None] = None
    error: Optional[str] = None

    #: The input the run was started with, as the JSON text the platform stored.
    input_data: Optional[str] = Field(default=None, alias="inputData")

    #: The run's result when the platform returned it inline (the long-poll wait does, for a run
    #: it saw finish); usually absent - see ``final_output_url``.
    value: Optional[Any] = None
    #: Presigned link to the stored result. Expires (30 minutes by default).
    final_output_url: Optional[str] = Field(default=None, alias="finalOutputUrl")
    #: Storage reference of the result, used to mint a fresh link.
    final_output_ref: Optional[str] = Field(default=None, alias="finalOutputRef")

    #: Why a ``WAITING_HUMAN`` run is paused (``waitType``, ``stepId``, ``stepName``).
    wait_info: Optional[dict[str, Any]] = Field(default=None, alias="waitInfo")
    steps: list[dict[str, Any]] = Field(default_factory=list)

    external_id: Optional[str] = Field(default=None, alias="externalId")
    scope_key: Optional[str] = Field(default=None, alias="scopeKey")
    scope_id: Optional[UUID] = Field(default=None, alias="scopeId")
    parent_run_id: Optional[UUID] = Field(default=None, alias="parentRunId")

    started_at: LenientDatetime = Field(default=None, alias="startedAt")
    finished_at: LenientDatetime = Field(default=None, alias="finishedAt")
    created_at: LenientDatetime = Field(default=None, alias="createdAt")
    updated_at: LenientDatetime = Field(default=None, alias="updatedAt")

    #: The decoded result, filled in by the SDK (``run`` / ``get_output``); not sent by the API.
    output: Optional[Any] = Field(default=None, exclude=True)

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> Any:
        return parse_run_status(value)

    @field_validator("steps", mode="before")
    @classmethod
    def _steps(cls, value: Any) -> Any:
        return [] if value is None else value

    @property
    def status_name(self) -> str:
        """The status as plain text, known or not."""
        if isinstance(self.status, RunStatus):
            return self.status.value
        return str(self.status) if self.status is not None else "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        """The run has ended (``FINISHED``, ``FAILED``, ``CANCELLED`` or ``TERMINATED``)."""
        return isinstance(self.status, RunStatus) and self.status.is_terminal

    @property
    def succeeded(self) -> bool:
        return self.status is RunStatus.FINISHED

    @property
    def is_waiting(self) -> bool:
        """Paused - for a person's approval, an agent, a sub-workflow; see ``wait_info``."""
        return self.status is RunStatus.WAITING_HUMAN

    @property
    def inputs(self) -> Optional[Any]:
        """The input the run was started with, decoded."""
        if self.input_data is None:
            return None
        try:
            return json.loads(self.input_data)
        except (TypeError, ValueError):
            return self.input_data

    # 0.1 names -----------------------------------------------------------------------------

    @property
    def outputs(self) -> Optional[Any]:
        """Alias of ``output`` (0.1 name)."""
        return self.output

    @property
    def completed_at(self) -> Optional[datetime]:
        """Alias of ``finished_at`` (0.1 name)."""
        return self.finished_at

    @property
    def duration_ms(self) -> Optional[int]:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds() * 1000)
        return None


# ============================================================
# Agent Models
# ============================================================


class Agent(BaseResource):
    """An AI agent definition."""

    name: str
    display_name: Optional[str] = Field(default=None, alias="displayName")
    description: Optional[str] = None
    status: AgentStatus = AgentStatus.DRAFT
    instructions: Optional[str] = None

    # Model configuration
    model_id: Optional[str] = Field(default=None, alias="modelId")
    model_provider: Optional[str] = Field(default=None, alias="modelProvider")
    temperature: float = 0.7
    max_tokens: Optional[int] = Field(default=None, alias="maxTokens")

    # Capabilities
    tools_enabled: bool = Field(default=False, alias="toolsEnabled")
    knowledge_base_enabled: bool = Field(default=False, alias="knowledgeBaseEnabled")


class AgentSession(BaseModel):
    """An active conversation session with an agent."""

    session_id: UUID = Field(alias="sessionId")
    agent_id: UUID = Field(alias="agentId")
    agent_name: Optional[str] = Field(default=None, alias="agentName")
    status: str = "ACTIVE"
    created_at: datetime = Field(alias="createdAt")

    # Cumulative metrics
    total_turns: int = Field(default=0, alias="totalTurns")
    total_tokens: int = Field(default=0, alias="totalTokens")
    total_cost_usd: float = Field(default=0.0, alias="totalCostUsd")

    model_config = {"populate_by_name": True}


class MessageMetrics(BaseModel):
    """Metrics from an agent message response."""

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
    """Details of a tool execution during agent processing."""

    tool_name: str = Field(alias="toolName")
    tool_type: Optional[str] = Field(default=None, alias="toolType")
    input: Optional[dict[str, Any]] = None
    output: Optional[Any] = None
    duration_ms: int = Field(default=0, alias="durationMs")
    success: bool = True
    error_message: Optional[str] = Field(default=None, alias="errorMessage")

    model_config = {"populate_by_name": True}


class KnowledgeBaseHit(BaseModel):
    """Knowledge base search hit details."""

    knowledge_base_id: str = Field(alias="knowledgeBaseId")
    knowledge_base_name: Optional[str] = Field(default=None, alias="knowledgeBaseName")
    document_title: Optional[str] = Field(default=None, alias="documentTitle")
    chunk_preview: Optional[str] = Field(default=None, alias="chunkPreview")
    relevance_score: float = Field(default=0.0, alias="relevanceScore")
    search_latency_ms: int = Field(default=0, alias="searchLatencyMs")

    model_config = {"populate_by_name": True}


class MessageResponse(BaseModel):
    """Response from sending a message to an agent."""

    status: MessageStatus
    message: Optional[str] = Field(default=None, alias="assistantResponse")
    user_message: Optional[str] = Field(default=None, alias="userMessage")
    message_id: Optional[str] = Field(default=None, alias="messageId")
    session_id: Optional[UUID] = Field(default=None, alias="sessionId")
    error_message: Optional[str] = Field(default=None, alias="errorMessage")

    # Detailed metrics
    metrics: Optional[MessageMetrics] = None

    # Tool and knowledge base usage
    tool_executions: list[ToolExecution] = Field(default_factory=list, alias="toolExecutions")
    knowledge_base_hits: list[KnowledgeBaseHit] = Field(
        default_factory=list, alias="knowledgeBaseHits"
    )

    model_config = {"populate_by_name": True}

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
    """Request to start an agent session."""

    agent_id: UUID = Field(alias="agentId")

    model_config = {"populate_by_name": True}


class SendMessageRequest(BaseModel):
    """Request to send a message in a session."""

    message: str
    include_debug: bool = Field(default=False, alias="includeDebug")

    model_config = {"populate_by_name": True}


# ============================================================
# Pagination Models
# ============================================================


class PageInfo(BaseModel):
    """Pagination information (the ``pagination`` object of a list response)."""

    page: int = 0
    size: int = 20
    total_elements: int = Field(default=0, alias="totalElements")
    total_pages: int = Field(default=0, alias="totalPages")
    has_next: bool = Field(default=False, alias="hasNext")
    has_previous: bool = Field(default=False, alias="hasPrevious")

    model_config = {"populate_by_name": True}


class Page(BaseModel):
    """A page of results."""

    content: list[Any] = Field(default_factory=list)
    page_info: PageInfo = Field(alias="pageInfo")

    model_config = {"populate_by_name": True}

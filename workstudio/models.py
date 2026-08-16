"""
Data models for the work.studio SDK.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# Enums
# ============================================================


class RunStatus(str, Enum):
    """Status of a workflow run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


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


class WorkflowRun(BaseResource):
    """A workflow execution instance."""

    workflow_id: UUID = Field(alias="workflowId")
    workflow_name: Optional[str] = Field(default=None, alias="workflowName")
    status: RunStatus
    inputs: Optional[dict[str, Any]] = None
    outputs: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    # Timing
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    completed_at: Optional[datetime] = Field(default=None, alias="completedAt")
    duration_ms: Optional[int] = Field(default=None, alias="durationMs")

    # External correlation
    external_id: Optional[str] = Field(default=None, alias="externalId")


class WorkflowRunRequest(BaseModel):
    """Request to run a workflow."""

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
    knowledge_base_hits: list[KnowledgeBaseHit] = Field(default_factory=list, alias="knowledgeBaseHits")

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
        return self.metrics.estimated_cost_usd if self.metrics else 0.0

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
    """Pagination information."""

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

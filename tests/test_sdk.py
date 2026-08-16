"""Tests for the work.studio Python SDK."""

import pytest
from uuid import UUID, uuid4

from workstudio import Client, AsyncClient
from workstudio.models import (
    Workflow,
    WorkflowRun,
    Agent,
    RunStatus,
    MessageResponse,
    MessageStatus,
    MessageMetrics,
)
from workstudio.exceptions import AuthenticationError, NotFoundError, ValidationError


class TestClient:
    """Test Client initialization."""
    
    def test_init_with_api_key(self):
        """Client can be initialized with an API key."""
        client = Client(api_key="test-key", base_url="http://localhost:8080")
        assert client is not None
        client.close()
    
    def test_init_without_api_key_raises(self, monkeypatch):
        """Client raises if no API key provided."""
        monkeypatch.delenv("WORKSTUDIO_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key required"):
            Client()
    
    def test_init_from_env(self, monkeypatch):
        """Client can read API key from environment."""
        monkeypatch.setenv("WORKSTUDIO_API_KEY", "env-test-key")
        client = Client(base_url="http://localhost:8080")
        assert client is not None
        client.close()


class TestModels:
    """Test Pydantic model parsing."""
    
    def test_workflow_parse(self):
        """Workflow model parses correctly."""
        data = {
            "id": str(uuid4()),
            "name": "Test Workflow",
            "description": "A test workflow",
            "endpoint": "test-workflow",
            "version": 1,
            "createdAt": "2024-01-01T00:00:00Z",
        }
        wf = Workflow.model_validate(data)
        assert wf.name == "Test Workflow"
        assert wf.endpoint == "test-workflow"
    
    def test_workflow_run_parse(self):
        """WorkflowRun model parses correctly."""
        data = {
            "id": str(uuid4()),
            "workflowId": str(uuid4()),
            "status": "COMPLETED",
            "inputs": {"key": "value"},
            "outputs": {"result": 42},
            "createdAt": "2024-01-01T00:00:00Z",
        }
        run = WorkflowRun.model_validate(data)
        assert run.status == RunStatus.COMPLETED
        assert run.outputs == {"result": 42}
    
    def test_agent_parse(self):
        """Agent model parses correctly."""
        data = {
            "id": str(uuid4()),
            "name": "test-agent",
            "displayName": "Test Agent",
            "description": "A test agent",
            "status": "PUBLISHED",
            "modelId": "gpt-4",
            "temperature": 0.7,
        }
        agent = Agent.model_validate(data)
        assert agent.name == "test-agent"
        assert agent.display_name == "Test Agent"
        assert agent.model_id == "gpt-4"

    def test_message_response_parse(self):
        """MessageResponse parses API format correctly."""
        # This matches the TestMessageResponse structure from ai-runtime
        data = {
            "sessionId": str(uuid4()),
            "messageId": "msg-123",
            "userMessage": "Hello",
            "assistantResponse": "Hi there! How can I help?",
            "status": "SUCCESS",
            "metrics": {
                "latencyMs": 150,
                "inputTokens": 10,
                "outputTokens": 15,
                "totalTokens": 25,
                "estimatedCostUsd": 0.001,
                "modelUsed": "gpt-4",
            },
            "toolExecutions": [
                {
                    "toolName": "search",
                    "durationMs": 50,
                    "success": True,
                }
            ],
            "knowledgeBaseHits": [],
        }
        resp = MessageResponse.model_validate(data)
        assert resp.status == MessageStatus.SUCCESS
        assert resp.message == "Hi there! How can I help?"
        assert resp.user_message == "Hello"
        # Test convenience properties
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 15
        assert resp.total_tokens == 25
        assert resp.latency_ms == 150
        assert resp.tools_used == ["search"]

    def test_message_response_without_metrics(self):
        """MessageResponse handles missing metrics gracefully."""
        data = {
            "status": "SUCCESS",
            "assistantResponse": "Hello!",
        }
        resp = MessageResponse.model_validate(data)
        assert resp.message == "Hello!"
        assert resp.prompt_tokens == 0  # Defaults when no metrics
        assert resp.total_tokens == 0


class TestExceptions:
    """Test exception handling."""
    
    def test_authentication_error(self):
        """AuthenticationError includes status code."""
        err = AuthenticationError("Invalid key", status_code=401)
        assert err.status_code == 401
        assert "Invalid key" in str(err)
    
    def test_not_found_error(self):
        """NotFoundError includes message."""
        err = NotFoundError("Workflow not found")
        assert err.status_code == 404
        assert "Workflow not found" in str(err)
    
    def test_validation_error_with_errors(self):
        """ValidationError includes field errors."""
        err = ValidationError(
            message="Validation failed",
            errors=[{"field": "name", "message": "required"}],
        )
        assert err.status_code == 400
        assert len(err.errors) == 1
        assert err.errors[0]["field"] == "name"


# Integration tests (require running API)
@pytest.mark.integration
class TestIntegration:
    """Integration tests that require a running work.studio instance."""
    
    @pytest.fixture
    def client(self):
        """Create a client for testing."""
        import os
        if not os.environ.get("WORKSTUDIO_API_KEY"):
            pytest.skip("WORKSTUDIO_API_KEY not set")
        client = Client()
        yield client
        client.close()
    
    def test_list_workflows(self, client):
        """Can list workflows."""
        workflows, page_info = client.workflows.list()
        assert isinstance(workflows, list)
        assert page_info.total_elements >= 0
    
    def test_list_agents(self, client):
        """Can list agents."""
        agents, page_info = client.agents.list()
        assert isinstance(agents, list)
        assert page_info.total_elements >= 0

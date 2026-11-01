"""A failed agent turn raises; it is never returned as a reply.

ai-runtime answers ``POST /ai-runtime/agent-conversation/sessions/{id}/messages`` with 200 and
``status: ERROR`` for a failed turn (``AgentConversationController.sendMessage``), so code that
checked only for an exception took the failure for an answer. The fixtures are the contract tests'
own reply (``AgentTestDto.TestMessageResponse``); the HTTP layer is mocked with pytest-httpx.
"""

import json

import pytest

from tests.test_contract import AGENT_ID, BASE, RT, SESSION_ID, message_reply, session_started
from workstudio import AgentTurnError, AsyncClient, Client, WorkStudioError
from workstudio.models import MessageResponse, MessageStatus


def failed_turn(error_message="This assistant has been turned off.", error_code="AGENT_TURNED_OFF"):
    body = message_reply("ERROR")
    body.update(
        assistantResponse=None,
        knowledgeBaseHits=[],
        toolExecutions=[],
        errorMessage=error_message,
        errorCode=error_code,
    )
    return body


@pytest.fixture
def client():
    with Client(api_key="svx_tk_test", base_url=BASE) as c:
        yield c


def _session(httpx_mock, reply, status_code=200):
    httpx_mock.add_response(
        method="POST", url=f"{RT}/sessions", status_code=201, json=session_started()
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{RT}/sessions/{SESSION_ID}/messages",
        status_code=status_code,
        json=reply,
    )
    httpx_mock.add_response(method="DELETE", url=f"{RT}/sessions/{SESSION_ID}", status_code=204)


class TestSync:
    def test_status_error_raises_with_the_code(self, client, httpx_mock):
        _session(httpx_mock, failed_turn())

        with pytest.raises(AgentTurnError) as caught:
            client.agents.chat(AGENT_ID, "hi")

        err = caught.value
        assert err.error_code == "AGENT_TURNED_OFF"
        assert err.message == "This assistant has been turned off."
        assert str(err) == "[AGENT_TURNED_OFF] This assistant has been turned off."
        assert str(err.session_id) == SESSION_ID
        assert isinstance(err.response, MessageResponse)
        assert err.response.status == MessageStatus.ERROR
        assert err.response_body["errorCode"] == "AGENT_TURNED_OFF"
        assert isinstance(err, WorkStudioError)

    def test_without_a_code_it_still_raises_with_the_message(self, client, httpx_mock):
        _session(httpx_mock, failed_turn("Failed to process message: boom", error_code=None))

        with pytest.raises(AgentTurnError) as caught:
            client.agents.chat(AGENT_ID, "hi")

        assert caught.value.error_code is None
        assert str(caught.value) == "Failed to process message: boom"

    def test_without_any_words_it_says_the_turn_failed(self, client, httpx_mock):
        _session(httpx_mock, failed_turn(error_message=None, error_code=""))

        with pytest.raises(AgentTurnError) as caught:
            client.agents.chat(AGENT_ID, "hi")

        assert caught.value.error_code is None
        assert str(caught.value) == "The agent's turn failed"

    def test_the_session_is_still_ended(self, client, httpx_mock):
        _session(httpx_mock, failed_turn())

        with pytest.raises(AgentTurnError):
            client.agents.chat(AGENT_ID, "hi")

        last = httpx_mock.get_requests()[-1]
        assert (last.method, str(last.url)) == ("DELETE", f"{RT}/sessions/{SESSION_ID}")

    def test_a_live_session_raises_and_stays_usable(self, client, httpx_mock):
        _session(httpx_mock, failed_turn("Temporary issue", "LLM_TEMPORARY_ERROR"))
        httpx_mock.add_response(
            method="POST", url=f"{RT}/sessions/{SESSION_ID}/messages", json=message_reply()
        )

        with client.agents.create_session(AGENT_ID) as session:
            with pytest.raises(AgentTurnError, match="Temporary issue"):
                session.send_message("hi")
            reply = session.send_message("again")

        assert reply.status == MessageStatus.SUCCESS
        sent = [json.loads(r.content) for r in httpx_mock.get_requests() if r.content]
        assert {"message": "again"} in sent

    @pytest.mark.parametrize("status", ["SUCCESS", "BLOCKED_BY_GUARDRAIL"])
    def test_other_statuses_are_still_replies(self, client, httpx_mock, status):
        _session(httpx_mock, message_reply(status))

        reply = client.agents.chat(AGENT_ID, "hi")

        assert reply.status == MessageStatus(status)


class TestAsync:
    @pytest.mark.asyncio
    async def test_status_error_raises_with_the_code(self, httpx_mock):
        _session(httpx_mock, failed_turn("Usage limit reached", "BUDGET_EXCEEDED"))

        async with AsyncClient(api_key="svx_tk_test", base_url=BASE) as client:
            with pytest.raises(AgentTurnError) as caught:
                await client.agents.chat(AGENT_ID, "hi")

        assert caught.value.error_code == "BUDGET_EXCEEDED"
        assert caught.value.message == "Usage limit reached"
        assert httpx_mock.get_requests()[-1].method == "DELETE"

    @pytest.mark.asyncio
    async def test_success_is_a_reply(self, httpx_mock):
        _session(httpx_mock, message_reply())

        async with AsyncClient(api_key="svx_tk_test", base_url=BASE) as client:
            reply = await client.agents.chat(AGENT_ID, "hi")

        assert reply.message == "Acme, 40k."

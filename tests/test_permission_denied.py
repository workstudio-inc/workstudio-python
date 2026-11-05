"""
A 403 says which permission the key lacks. The three bodies below are the platform's, as answered
on a real stack (live monolith jar, real keys; internal-docs plans/key-permission-rollout-241.md):
- PermissionInterceptor: the name only in ``detail``; its ``message`` says just "Permission denied".
- ApiKeyPermissionInterceptor, a route naming a key permission: ``missingPermission``.
- ApiKeyPermissionInterceptor, a route a key may not use: no permission to add, only ``code``.
"""

import pytest

from workstudio import AsyncClient, AuthenticationError, Client

BASE = "https://api.example.test"
RUNS = f"{BASE}/api/v1/workflow/run?page=0&size=20"

NEEDS_IN_DETAIL = {
    "error": "PERMISSION_DENIED",
    "message": "Permission denied",
    "detail": "This API key lacks the required permission(s): [run:read]",
}
NEEDS_NAMED = {
    "error": "PERMISSION_DENIED",
    "code": "MISSING_PERMISSION",
    "message": "This API key lacks the required permission",
    "detail": "Missing required permission: run:read",
    "missingPermission": "run:read",
}
NOT_FOR_KEYS = {
    "error": "PERMISSION_DENIED",
    "code": "API_KEY_NOT_ALLOWED",
    "message": "This API key may not use this endpoint",
    "detail": "This endpoint is not available to API keys",
}


@pytest.fixture
def client():
    c = Client(api_key="svx_tk_test", base_url=BASE)
    yield c
    c.close()


@pytest.mark.parametrize("body", [NEEDS_IN_DETAIL, NEEDS_NAMED])
def test_a_refusal_names_the_permission_to_add(client, httpx_mock, body):
    httpx_mock.add_response(method="GET", url=RUNS, status_code=403, json=body)
    with pytest.raises(AuthenticationError) as e:
        client.workflows.list_runs()
    assert e.value.missing_permission == "run:read"
    assert "run:read" in str(e.value)
    assert e.value.status_code == 403


def test_the_permission_is_not_said_twice(client, httpx_mock):
    body = dict(NEEDS_NAMED, message="Missing required permission: run:read")
    httpx_mock.add_response(method="GET", url=RUNS, status_code=403, json=body)
    with pytest.raises(AuthenticationError) as e:
        client.workflows.list_runs()
    assert str(e.value) == "[403] Missing required permission: run:read"


def test_a_route_closed_to_keys_has_no_permission_to_add_and_gives_its_code(client, httpx_mock):
    httpx_mock.add_response(method="GET", url=RUNS, status_code=403, json=NOT_FOR_KEYS)
    with pytest.raises(AuthenticationError) as e:
        client.workflows.list_runs()
    assert e.value.missing_permission is None
    assert e.value.code == "API_KEY_NOT_ALLOWED"
    assert "may not use this endpoint" in str(e.value)


def test_a_refusal_with_no_json_body_still_reads(client, httpx_mock):
    httpx_mock.add_response(method="GET", url=RUNS, status_code=403, text="<html>Forbidden</html>")
    with pytest.raises(AuthenticationError) as e:
        client.workflows.list_runs()
    assert e.value.missing_permission is None
    assert "insufficient permissions" in str(e.value)


def test_a_401_is_not_a_permission_refusal(client, httpx_mock):
    httpx_mock.add_response(method="GET", url=RUNS, status_code=401, json={"message": "nope"})
    with pytest.raises(AuthenticationError) as e:
        client.workflows.list_runs()
    assert getattr(e.value, "missing_permission", None) is None
    assert type(e.value).__name__ == "AuthenticationError"


def test_it_is_catchable_by_name_and_as_an_authentication_error():
    import workstudio

    assert issubclass(workstudio.PermissionDeniedError, AuthenticationError)
    assert "PermissionDeniedError" in workstudio.__all__


@pytest.mark.asyncio
async def test_the_async_client_says_the_same(httpx_mock):
    httpx_mock.add_response(method="GET", url=RUNS, status_code=403, json=NEEDS_IN_DETAIL)
    async with AsyncClient(api_key="svx_tk_test", base_url=BASE) as c:
        with pytest.raises(AuthenticationError) as e:
            await c.workflows.list_runs()
    assert e.value.missing_permission == "run:read"
    assert "run:read" in str(e.value)

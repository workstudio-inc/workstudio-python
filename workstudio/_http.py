"""
Internal HTTP client for the work.studio SDK.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from workstudio._version import __version__
from workstudio.exceptions import (
    APIError,
    AuthenticationError,
    ConnectionError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    TimeoutError,
    ValidationError,
)

DEFAULT_BASE_URL = "https://api.work.studio"
DEFAULT_TIMEOUT = 30.0

#: Header naming the customer a TENANT key acts for. A CUSTOMER key is bound to its customer, so
#: for one this header may only repeat that customer (anything else is a 403).
SCOPE_HEADER = "X-SCOPE-KEY"


def _build_headers(api_key: str, scope_key: Optional[str]) -> dict[str, str]:
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"workstudio-python/{__version__}",
    }
    if scope_key:
        headers[SCOPE_HEADER] = scope_key
    return headers


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _message(body: Any, default: str) -> str:
    """The server's own explanation, wherever this endpoint put it."""
    if isinstance(body, dict):
        for key in ("message", "error_description", "errorMessage", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return default


def raise_for_status(response: httpx.Response) -> None:
    """Raise the SDK exception matching an error response; return quietly for a success."""
    status = response.status_code
    if status < 400:
        return
    body = _safe_json(response)

    if status == 401:
        raise AuthenticationError(
            message=_message(body, "Invalid or expired API key"),
            status_code=401,
            response_body=body,
        )
    if status == 403:
        raise PermissionDeniedError(
            message=_message(body, "Access denied - this API key is not allowed to do that"),
            status_code=403,
            response_body=body,
        )
    if status == 404:
        raise NotFoundError(
            message=_message(body, "Resource not found"),
            status_code=404,
            response_body=body,
        )
    if status == 400:
        errors = body.get("errors", []) if isinstance(body, dict) else []
        raise ValidationError(
            message=_message(body, "Validation error"),
            status_code=400,
            response_body=body,
            errors=errors if isinstance(errors, list) else [],
        )
    if status == 429:
        retry_after = response.headers.get("Retry-After")
        raise RateLimitError(
            message=_message(body, "Rate limit exceeded"),
            status_code=429,
            response_body=body,
            retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
        )
    raise APIError(
        message=_message(body, "Internal server error" if status >= 500 else f"HTTP {status}"),
        status_code=status,
        response_body=body,
    )


def parse_body(response: httpx.Response) -> Any:
    """A success body as JSON; ``{}`` for an empty one."""
    if response.status_code == 204 or not response.content:
        return {}
    body = _safe_json(response)
    return {} if body is None else body


class HTTPClient:
    """Synchronous HTTP client for API requests."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        scope_id: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.scope_id = scope_id
        self._transport = transport

        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=_build_headers(api_key, scope_id),
            transport=transport,
        )

    def send(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Any = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Make a request and return the raw response, without raising on an error status."""
        try:
            return self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out: {e}")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Failed to connect: {e}")

    def request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Any = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Make an HTTP request and return the JSON response."""
        response = self.send(
            method, path, params=params, json=json, headers=headers, timeout=timeout
        )
        raise_for_status(response)
        return parse_body(response)

    def fetch_external(self, url: str) -> httpx.Response:
        """
        GET a URL outside the API - a presigned storage URL - WITHOUT the API key.

        The key must never travel to another host; a presigned URL carries its own authority.
        """
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as plain:
                return plain.get(url)
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out: {e}")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Failed to connect: {e}")

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Make a GET request."""
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        """Make a POST request."""
        return self.request("POST", path, params=params, json=json, headers=headers)

    def put(self, path: str, json: Any = None, params: Optional[dict[str, Any]] = None) -> Any:
        """Make a PUT request."""
        return self.request("PUT", path, params=params, json=json)

    def delete(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Make a DELETE request."""
        return self.request("DELETE", path, params=params)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


class AsyncHTTPClient:
    """Asynchronous HTTP client for API requests."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        scope_id: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.scope_id = scope_id
        self._transport = transport

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=_build_headers(api_key, scope_id),
            transport=transport,
        )

    async def send(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Any = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Make a request and return the raw response, without raising on an error status."""
        try:
            return await self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out: {e}")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Failed to connect: {e}")

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Any = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Make an async HTTP request and return the JSON response."""
        response = await self.send(
            method, path, params=params, json=json, headers=headers, timeout=timeout
        )
        raise_for_status(response)
        return parse_body(response)

    async def fetch_external(self, url: str) -> httpx.Response:
        """GET a presigned storage URL WITHOUT the API key (see ``HTTPClient.fetch_external``)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as plain:
                return await plain.get(url)
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out: {e}")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Failed to connect: {e}")

    async def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Make an async GET request."""
        return await self.request("GET", path, params=params)

    async def post(
        self,
        path: str,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        """Make an async POST request."""
        return await self.request("POST", path, params=params, json=json, headers=headers)

    async def put(
        self, path: str, json: Any = None, params: Optional[dict[str, Any]] = None
    ) -> Any:
        """Make an async PUT request."""
        return await self.request("PUT", path, params=params, json=json)

    async def delete(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Make an async DELETE request."""
        return await self.request("DELETE", path, params=params)

    async def close(self) -> None:
        """Close the async HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncHTTPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

"""
Internal HTTP client for the work.studio SDK.
"""

import re
from typing import Any, Optional, TypeVar

import httpx

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

T = TypeVar("T")

DEFAULT_BASE_URL = "https://api.work.studio"
DEFAULT_TIMEOUT = 30.0



# PermissionInterceptor names what a key lacks only in its detail:
# "...required permission(s): [agent:read]".
_REQUIRED_IN_DETAIL = re.compile(r"permission\(s\):\s*\[([^\]]+)\]")


def _message(body: Any, default: str) -> str:
    """
    The explanation in an error reply.

    Platform errors carry it as ``message`` (and ``error``/``detail`` in some handlers); an agent
    message reply carries ``errorMessage``. A body that is not a JSON object has none.
    """
    if isinstance(body, dict):
        for key in ("message", "errorMessage", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return default


def _missing_permission(body: Any) -> Optional[str]:
    """What a 403 says the key lacks: ``missingPermission``, else the name in its detail."""
    if not isinstance(body, dict):
        return None
    named = body.get("missingPermission")
    if isinstance(named, str) and named.strip():
        return named.strip()
    detail = body.get("detail")
    if isinstance(detail, str):
        found = _REQUIRED_IN_DETAIL.search(detail)
        if found:
            return found.group(1).strip()
    return None


def _permission_denied(body: Any) -> PermissionDeniedError:
    """The error for a 403, saying which permission to add when the platform named one."""
    message = _message(body, "Access denied - insufficient permissions")
    missing = _missing_permission(body)
    if missing and missing not in message:
        message = f"{message}: this API key needs {missing}"
    code = body.get("code") if isinstance(body, dict) else None
    return PermissionDeniedError(
        message=message,
        status_code=403,
        response_body=body,
        missing_permission=missing,
        code=code if isinstance(code, str) else None,
    )


class HTTPClient:
    """Synchronous HTTP client for API requests."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        scope_id: Optional[str] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.scope_id = scope_id

        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        """Build default headers for requests."""
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "workstudio-python/0.2.0",
        }
        if self.scope_id:
            headers["X-SCOPE-KEY"] = self.scope_id
        return headers

    def request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        ok_statuses: tuple[int, ...] = (),
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """Make an HTTP request and return the JSON response."""
        try:
            response = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
            if response.status_code in ok_statuses:
                body = self._safe_json(response)
                return body if isinstance(body, dict) else {}
            return self._handle_response(response)
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out: {e}")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Failed to connect: {e}")

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle the HTTP response and raise appropriate exceptions."""
        if response.status_code == 401:
            raise AuthenticationError(
                message="Invalid or expired API key",
                status_code=401,
                response_body=self._safe_json(response),
            )

        if response.status_code == 403:
            raise _permission_denied(self._safe_json(response))

        if response.status_code == 404:
            body = self._safe_json(response)
            message = _message(body, "Resource not found")
            raise NotFoundError(
                message=message,
                status_code=404,
                response_body=body,
            )

        if response.status_code == 400:
            body = self._safe_json(response)
            message = _message(body, "Validation error")
            errors = body.get("errors", []) if isinstance(body, dict) else []
            raise ValidationError(
                message=message,
                status_code=400,
                response_body=body,
                errors=errors,
            )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                message="Rate limit exceeded",
                status_code=429,
                response_body=self._safe_json(response),
                retry_after=int(retry_after) if retry_after else None,
            )

        if response.status_code >= 500:
            body = self._safe_json(response)
            message = _message(body, "Internal server error")
            raise APIError(
                message=message,
                status_code=response.status_code,
                response_body=body,
            )

        if response.status_code >= 400:
            body = self._safe_json(response)
            message = _message(body, f"HTTP {response.status_code}")
            raise APIError(
                message=message,
                status_code=response.status_code,
                response_body=body,
            )

        # Success - return JSON body
        if response.status_code == 204:
            return {}
        return response.json()

    def _safe_json(self, response: httpx.Response) -> Any:
        """Safely parse JSON from response, returning None on failure."""
        try:
            return response.json()
        except Exception:
            return None

    def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make a GET request."""
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make a POST request."""
        return self.request("POST", path, params=params, json=json)

    def put(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make a PUT request."""
        return self.request("PUT", path, params=params, json=json)

    def delete(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
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
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.scope_id = scope_id

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._build_headers(),
        )

    def _build_headers(self) -> dict[str, str]:
        """Build default headers for requests."""
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "workstudio-python/0.2.0",
        }
        if self.scope_id:
            headers["X-SCOPE-KEY"] = self.scope_id
        return headers

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        ok_statuses: tuple[int, ...] = (),
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        """Make an async HTTP request and return the JSON response."""
        try:
            response = await self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                headers=headers,
                timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            )
            if response.status_code in ok_statuses:
                body = self._safe_json(response)
                return body if isinstance(body, dict) else {}
            return self._handle_response(response)
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timed out: {e}")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Failed to connect: {e}")

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle the HTTP response and raise appropriate exceptions."""
        # Same logic as sync client
        if response.status_code == 401:
            raise AuthenticationError(
                message="Invalid or expired API key",
                status_code=401,
                response_body=self._safe_json(response),
            )

        if response.status_code == 403:
            raise _permission_denied(self._safe_json(response))

        if response.status_code == 404:
            body = self._safe_json(response)
            message = _message(body, "Resource not found")
            raise NotFoundError(
                message=message,
                status_code=404,
                response_body=body,
            )

        if response.status_code == 400:
            body = self._safe_json(response)
            message = _message(body, "Validation error")
            errors = body.get("errors", []) if isinstance(body, dict) else []
            raise ValidationError(
                message=message,
                status_code=400,
                response_body=body,
                errors=errors,
            )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(
                message="Rate limit exceeded",
                status_code=429,
                response_body=self._safe_json(response),
                retry_after=int(retry_after) if retry_after else None,
            )

        if response.status_code >= 500:
            body = self._safe_json(response)
            message = _message(body, "Internal server error")
            raise APIError(
                message=message,
                status_code=response.status_code,
                response_body=body,
            )

        if response.status_code >= 400:
            body = self._safe_json(response)
            message = _message(body, f"HTTP {response.status_code}")
            raise APIError(
                message=message,
                status_code=response.status_code,
                response_body=body,
            )

        if response.status_code == 204:
            return {}
        return response.json()

    def _safe_json(self, response: httpx.Response) -> Any:
        """Safely parse JSON from response."""
        try:
            return response.json()
        except Exception:
            return None

    async def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an async GET request."""
        return await self.request("GET", path, params=params)

    async def post(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an async POST request."""
        return await self.request("POST", path, params=params, json=json)

    async def put(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an async PUT request."""
        return await self.request("PUT", path, params=params, json=json)

    async def delete(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an async DELETE request."""
        return await self.request("DELETE", path, params=params)

    async def close(self) -> None:
        """Close the async HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncHTTPClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

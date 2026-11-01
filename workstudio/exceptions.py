"""
Exceptions for the work.studio SDK.
"""

from typing import Any, Optional


class WorkStudioError(Exception):
    """Base exception for all work.studio SDK errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        if self.status_code:
            return f"[{self.status_code}] {self.message}"
        return self.message


class AuthenticationError(WorkStudioError):
    """Raised when API key is invalid or missing."""

    def __init__(
        self,
        message: str = "Invalid or missing API key",
        status_code: int = 401,
        response_body: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response_body)


class NotFoundError(WorkStudioError):
    """Raised when a requested resource is not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        status_code: int = 404,
        response_body: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response_body)


class ValidationError(WorkStudioError):
    """Raised when request validation fails."""

    def __init__(
        self,
        message: str = "Validation error",
        status_code: int = 400,
        response_body: Optional[Any] = None,
        errors: Optional[list[dict[str, Any]]] = None,
    ):
        super().__init__(message, status_code, response_body)
        self.errors = errors or []


class RateLimitError(WorkStudioError):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        status_code: int = 429,
        response_body: Optional[Any] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message, status_code, response_body)
        self.retry_after = retry_after


class APIError(WorkStudioError):
    """Raised for general API errors."""

    pass


class AgentTurnError(WorkStudioError):
    """
    Raised when an agent's turn failed.

    The platform answers a failed turn on ``POST .../sessions/{id}/messages`` with a 2xx and
    ``status: ERROR`` in the body, so the HTTP status alone says nothing went wrong. The SDK reads
    the body and raises this instead of returning the failure as if it were a reply.

    Attributes:
        error_code: The platform's stable code for the failure (``AGENT_TURNED_OFF``,
            ``BUDGET_EXCEEDED``, ...), or None when the reply carried none
        session_id: The conversation session the turn ran in
        response: The parsed reply (a ``MessageResponse``), metrics included
    """

    def __init__(
        self,
        message: str = "The agent's turn failed",
        error_code: Optional[str] = None,
        session_id: Optional[Any] = None,
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
        response: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response_body)
        self.error_code = error_code
        self.session_id = session_id
        self.response = response

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class TimeoutError(WorkStudioError):
    """Raised when a request times out."""

    def __init__(
        self,
        message: str = "Request timed out",
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response_body)


class ConnectionError(WorkStudioError):
    """Raised when connection to the API fails."""

    def __init__(
        self,
        message: str = "Failed to connect to work.studio API",
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response_body)

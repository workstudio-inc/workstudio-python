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


class PermissionDeniedError(AuthenticationError):
    """
    Raised on a 403: the key is valid, but it may not do this.

    ``missing_permission`` is what the platform says the key needs, such as ``agent:execute``. Add
    it to the key in the Designer, under API Keys. It is None when no permission would help: ``code``
    then says why, for example ``TENANT_API_KEY_ONLY`` for a customer key on an organization-key route.

    It is an AuthenticationError, so code that catches that keeps working.
    """

    def __init__(
        self,
        message: str = "Access denied - insufficient permissions",
        status_code: int = 403,
        response_body: Optional[Any] = None,
        missing_permission: Optional[str] = None,
        code: Optional[str] = None,
    ):
        super().__init__(message, status_code, response_body)
        self.missing_permission = missing_permission
        self.code = code


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

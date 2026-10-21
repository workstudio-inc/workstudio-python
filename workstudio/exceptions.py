"""
Exceptions for the work.studio SDK.
"""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from workstudio.models import WorkflowRun


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
    Raised on 403: the key is valid but may not do this.

    For example a CUSTOMER key reading another customer's run, or a key without the permission an
    endpoint asks for. A subclass of :class:`AuthenticationError`, so code written for 0.1 that
    caught that still catches this.
    """

    def __init__(
        self,
        message: str = "Access denied - this API key is not allowed to do that",
        status_code: int = 403,
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


class RunFailedError(WorkStudioError):
    """
    Raised by ``workflows.run(...)`` when the run ended without succeeding.

    ``run.status`` says how it ended (``FAILED``, ``CANCELLED`` or ``TERMINATED``) and
    ``run.error`` why, when the platform recorded a reason.
    """

    def __init__(self, run: "WorkflowRun"):
        reason = f": {run.error}" if run.error else ""
        super().__init__(f"Run {run.id} ended {run.status_name}{reason}")
        self.run = run


class RunTimeoutError(TimeoutError):
    """
    Raised when a run has not finished by the time the caller was prepared to wait.

    The run carries on regardless; ``run`` is its last known state (it may be ``RUNNING``, or
    ``WAITING_HUMAN`` when it is paused for an approval), and ``workflows.wait(run.id)`` picks it
    up again.
    """

    def __init__(self, run: "WorkflowRun", waited_seconds: float):
        super().__init__(
            f"Run {run.id} was still {run.status_name} after {waited_seconds:.0f}s"
        )
        self.run = run
        self.waited_seconds = waited_seconds

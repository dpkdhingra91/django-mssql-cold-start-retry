"""MSSQLRetryMiddleware — catches dead Azure SQL connections at the request boundary.

Under Daphne (ASGI), Django's `convert_exception_to_response` catches
OperationalError BEFORE middleware's `try/except` clause. So we use
`process_exception()`, which is called BEFORE the 500 conversion.

Strategy:
- `process_exception`: catches OperationalError, closes the dead connection,
  returns 503 (Service Unavailable) with `Retry-After: 1`.
- Client retries (browsers running `fetch-with-retry` do this automatically).
- Second request hits a fresh connection and succeeds.
"""

import logging

from django.db import OperationalError, connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class MSSQLRetryMiddleware:
    """Returns 503 + Retry-After when the DB connection is dead.

    Wire it up in settings.py:

        MIDDLEWARE = [
            ...
            "django_mssql_retry.MSSQLRetryMiddleware",
            ...
        ]

    Position is flexible — it only acts on `process_exception`, so as long
    as it sees OperationalError before Django's default 500 handler does,
    you're fine. Putting it near the top of the list is safest.
    """

    # pyodbc SQLSTATE codes that indicate a dead/broken connection.
    _RETRIABLE_STATES = {"08001", "08S01", "08007", "HYT00", "HY000"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Called when a view raises an exception, BEFORE Django's 500 handler."""
        if not isinstance(exception, OperationalError):
            return None
        if not self._is_connection_error(exception):
            return None

        logger.warning(
            "[mssql_retry] dead connection on %s %s — closing connection, returning 503: %s",
            request.method, request.path, exception,
        )

        # Force-close the dead connection so the next request gets a fresh one.
        try:
            connection.close()
        except Exception:
            pass

        return JsonResponse(
            {"error": "Database connection lost, please retry"},
            status=503,
            headers={"Retry-After": "1"},
        )

    @classmethod
    def _is_connection_error(cls, exc) -> bool:
        """Check if this OperationalError is a connection-level failure."""
        args = getattr(exc, "args", ())
        if not args:
            return False
        first = args[0]
        if isinstance(first, str) and first in cls._RETRIABLE_STATES:
            return True
        # Check nested __cause__ from pyodbc.
        cause = getattr(exc, "__cause__", None)
        if cause and hasattr(cause, "args") and cause.args:
            state = cause.args[0] if isinstance(cause.args[0], str) else ""
            return state in cls._RETRIABLE_STATES
        # Fallback: string-match known patterns.
        msg = str(exc)
        return "SQLDriverConnect" in msg or "TCP Provider" in msg

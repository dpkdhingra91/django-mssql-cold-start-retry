"""MSSQL cold-start retry decorator.

Azure SQL connections from Docker NAT occasionally return a TCP-dead connection
from Django's `CONN_MAX_AGE` pool. The first query times out at the ODBC
`LoginTimeout`; a second attempt with a freshly-opened TCP connection succeeds.

This decorator wraps a view method in one automatic retry that discards the
dead connection via `connection.close()` before re-running the wrapped callable.
"""

import logging
from functools import wraps

from django.db import OperationalError, connection

logger = logging.getLogger(__name__)


def mssql_cold_start_retry(max_retries: int = 1):
    """Retry a view on DB connection errors, closing the pool connection between attempts.

    Only retries on errors that look like cold-start timeouts (OperationalError
    or exceptions whose message contains SQLDriverConnect timeout codes).
    Other exceptions propagate immediately — we don't want to mask real bugs.

    Args:
        max_retries: how many extra attempts to make beyond the first call.
            Default 1 → up to 2 total attempts.

    Example:
        from django_mssql_retry import mssql_cold_start_retry

        class CriticalReadView(APIView):
            @mssql_cold_start_retry()
            def get(self, request):
                return Response(list(MyModel.objects.values()))
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return fn(*args, **kwargs)
                except OperationalError as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        logger.warning(
                            "[mssql_retry] OperationalError on %s attempt=%d — "
                            "closing pool conn, retrying: %s",
                            fn.__qualname__, attempt + 1, exc,
                        )
                        connection.close()
                        continue
                    raise
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc).lower()
                    cold_start_markers = ("08001", "sqldriverconnect", "login timeout")
                    if any(m in msg for m in cold_start_markers) and attempt < max_retries:
                        last_exc = exc
                        logger.warning(
                            "[mssql_retry] cold-start marker on %s attempt=%d — "
                            "closing pool conn, retrying: %s",
                            fn.__qualname__, attempt + 1, exc,
                        )
                        connection.close()
                        continue
                    raise
            if last_exc:
                raise last_exc
            return None

        return wrapper

    return decorator

"""django-mssql-cold-start-retry — survive Azure SQL cold-connection timeouts.

Two layers, use either or both:

- `@mssql_cold_start_retry()` — view decorator that catches dead-connection
  OperationalErrors and retries once after closing the pool connection.

- `MSSQLRetryMiddleware` — Django middleware that catches the same errors
  in `process_exception()`, returns 503 + `Retry-After`, lets the client
  retry on a fresh connection.

Pair with `CONN_MAX_AGE=600`, `connection_timeout=5`, and
`ConnectRetryCount=1` in your settings for tight cold-start recovery.
"""

from .decorator import mssql_cold_start_retry
from .middleware import MSSQLRetryMiddleware

__all__ = ["mssql_cold_start_retry", "MSSQLRetryMiddleware"]
__version__ = "0.1.0"

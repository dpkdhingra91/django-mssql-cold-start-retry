# django-mssql-cold-start-retry

Survive Azure SQL cold-connection timeouts in a Django app behind Docker NAT.

Two layers — use either or both:

1. **`@mssql_cold_start_retry()`** — view decorator. One automatic retry, closes the dead pool connection between attempts.
2. **`MSSQLRetryMiddleware`** — request middleware. Returns 503 + `Retry-After` so clients retry on a fresh connection.

## The bug

You run Django + pyodbc against Azure SQL. Connections are pooled with `CONN_MAX_AGE=600`. Sometimes — usually after a quiet period — a pooled connection has gone TCP-dead, but Django doesn't know. The next query waits ~30 seconds at the ODBC `LoginTimeout`, then errors out. The user sees a 500. They reload, hit a fresh connection, succeed.

Symptoms you'll see in the logs:
```
django.db.utils.OperationalError: ('08001', '[08001] [Microsoft][ODBC Driver 18 for SQL Server]
TCP Provider: Error code 0x274C')
```

## Install

```bash
pip install django-mssql-cold-start-retry
```

## Setup

Recommended: use **both** layers. The middleware handles broad coverage; the decorator gives you in-process retry for views where a 503 round-trip is unacceptable.

### Middleware (request-level recovery, returns 503)

```python
# settings.py
MIDDLEWARE = [
    "django_mssql_retry.MSSQLRetryMiddleware",
    # ... rest of your middleware ...
]
```

Pair with `Retry-After`-aware clients. The companion JS library [`fetch-with-retry`](https://github.com/dpkdhingra91/fetch-with-retry) retries 502/503/504 automatically.

### Decorator (in-process retry, transparent to client)

```python
from django_mssql_retry import mssql_cold_start_retry

class CriticalReadView(APIView):
    @mssql_cold_start_retry()
    def get(self, request):
        return Response(list(MyModel.objects.values()))
```

## Pair with these settings

```python
# settings.py
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            "extra_params": "Encrypt=yes;TrustServerCertificate=no;ConnectRetryCount=1;ConnectRetryInterval=1",
            "connection_timeout": 5,    # fail fast — 5s instead of 30
        },
        "CONN_MAX_AGE": 600,
        # ...
    }
}
```

`connection_timeout=5` means a dead connection fails in 5 seconds, not 30 — so the middleware/decorator can recover quickly. `ConnectRetryCount=1` tells the ODBC driver to do one fast reconnect itself before raising.

## Which layer when

- **Always middleware.** It's free coverage — runs only on exception, costs nothing on the happy path.
- **Decorator on top of middleware** when:
  - The view is the first DB hit in a user-facing flow (login, meeting verification, etc.) — 503 + retry costs a perceptible delay.
  - The client may not be retry-aware (third-party integrations).
- **Decorator only, skip middleware** when you'd rather see the OperationalError than auto-recover (most apps shouldn't choose this).

## What about `django-db-connection-pool` or PgBouncer?

Different problem domain — those help when your app is overwhelming the DB with connections. This library helps when an *idle* pooled connection has died unnoticed. They're complementary.

## License

MIT — see [LICENSE](LICENSE).

## Origin

Extracted from a production Django backend running against Azure SQL Basic tier, in a Docker container behind Azure NAT. The cold-connection bug was rare enough to be hard to reproduce locally but consistently caught one user per day. This pair of layers dropped the error rate to ~0.

---

*Extracted from the production stack behind [AI Interview Agents](https://www.aiinterviewagents.com) — an AI voice interview platform.*

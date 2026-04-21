"""Prometheus metrics middleware + /metrics endpoint."""

import time

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Request metrics ─────────────────────────────
REQUEST_COUNT = Counter(
    "stockagent_http_requests_total",
    "Total HTTP requests",
    ["method", "path_template", "status"],
)

REQUEST_DURATION = Histogram(
    "stockagent_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path_template"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ── Job metrics (updated by job_manager) ────────
JOB_ACTIVE = Gauge(
    "stockagent_jobs_active",
    "Number of currently running jobs",
    ["job_type"],
)

JOB_TOTAL = Counter(
    "stockagent_jobs_total",
    "Total jobs by type and status",
    ["job_type", "status"],
)

# ── Data freshness ──────────────────────────────
DATA_FRESHNESS = Gauge(
    "stockagent_data_latest_date_epoch",
    "Epoch timestamp of latest daily price data",
)

# ── Custom metrics ──────────────────────────────
BACKTEST_DURATION = Histogram(
    "stockagent_backtest_duration_seconds",
    "Backtest execution duration",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

ERROR_COUNT = Counter(
    "stockagent_errors_total",
    "Total errors by source",
    ["source"],
)


def _simplify_path(path: str) -> str:
    """Collapse numeric IDs to {id} to reduce cardinality."""
    parts = path.split("/")
    result = []
    for part in parts:
        if part.isdigit():
            result.append("{id}")
        else:
            result.append(part)
    return "/".join(result)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Track request count and duration as Prometheus metrics."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        path_template = _simplify_path(request.url.path)

        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        status = str(response.status_code)
        REQUEST_COUNT.labels(method=method, path_template=path_template, status=status).inc()
        REQUEST_DURATION.labels(method=method, path_template=path_template).observe(duration)

        return response


async def metrics_endpoint(request: Request) -> Response:
    """Serve Prometheus metrics at /metrics."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )

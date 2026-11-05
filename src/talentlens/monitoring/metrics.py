"""In-process metrics for the API.

A small hand-rendered Prometheus exposition avoids adding a metrics SDK and makes the
data easy to inspect in tests. Counters are per-path and are bounded by the route table.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

_lock = threading.Lock()
_requests: dict[tuple[str, str, int], int] = defaultdict(int)
_latency_sum: dict[str, float] = defaultdict(float)
_latency_count: dict[str, int] = defaultdict(int)
_started_at = time.time()


def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    with _lock:
        _requests[(method, path, status)] += 1
        _latency_sum[path] += duration_ms
        _latency_count[path] += 1


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "uptime_seconds": round(time.time() - _started_at, 3),
            "requests": {
                f"{method} {path} {status}": count
                for (method, path, status), count in sorted(_requests.items())
            },
            "latency": {
                path: {
                    "count": _latency_count[path],
                    "mean_ms": round(_latency_sum[path] / _latency_count[path], 3),
                }
                for path in sorted(_latency_count)
            },
        }


def reset() -> None:
    with _lock:
        _requests.clear()
        _latency_sum.clear()
        _latency_count.clear()


def render_prometheus() -> str:
    data = snapshot()
    lines = [
        "# HELP talentlens_uptime_seconds Process uptime.",
        "# TYPE talentlens_uptime_seconds gauge",
        f"talentlens_uptime_seconds {data['uptime_seconds']}",
        "# HELP talentlens_http_requests_total HTTP requests by method, path and status.",
        "# TYPE talentlens_http_requests_total counter",
    ]
    for key, count in data["requests"].items():
        method, path, status = key.rsplit(" ", 2)
        lines.append(
            f'talentlens_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
        )
    lines.extend(
        [
            "# HELP talentlens_http_request_duration_ms_sum Sum of request durations.",
            "# TYPE talentlens_http_request_duration_ms_sum counter",
            "# HELP talentlens_http_request_duration_ms_count Number of timed requests.",
            "# TYPE talentlens_http_request_duration_ms_count counter",
        ]
    )
    for path, values in data["latency"].items():
        count = values["count"]
        total = values["mean_ms"] * count
        lines.append(f'talentlens_http_request_duration_ms_sum{{path="{path}"}} {total:.3f}')
        lines.append(f'talentlens_http_request_duration_ms_count{{path="{path}"}} {count}')
    return "\n".join(lines) + "\n"

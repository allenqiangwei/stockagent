"""Network utilities — proxy management for data sources."""

import os
from contextlib import contextmanager

PROXY_ENV_VARS = [
    "HTTP_PROXY", "http_proxy",
    "HTTPS_PROXY", "https_proxy",
    "ALL_PROXY", "all_proxy",
]
NO_PROXY_VARS = ["NO_PROXY", "no_proxy"]


@contextmanager
def no_proxy():
    """Temporarily disable system proxy for direct access to domestic data APIs."""
    saved = {}
    for var in PROXY_ENV_VARS:
        if var in os.environ:
            saved[var] = os.environ.pop(var)

    saved_np = {}
    for var in NO_PROXY_VARS:
        if var in os.environ:
            saved_np[var] = os.environ[var]
        os.environ[var] = "*"

    try:
        yield
    finally:
        for var, val in saved.items():
            os.environ[var] = val
        for var in NO_PROXY_VARS:
            if var in saved_np:
                os.environ[var] = saved_np[var]
            elif var in os.environ and var not in saved_np:
                del os.environ[var]

import os
from pathlib import Path

from .app import create_app


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} must be set to a nonempty token")
    return value


app = create_app(
    Path(os.environ.get("PORTAL_DATA_DIR", "/data")),
    _required("PORTAL_API_TOKEN"),
    _required("PORTAL_RUNNER_TOKEN"),
)

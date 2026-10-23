from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class RunnerConfig:
    portal_url: str
    token: str
    runner_id: str
    work_dir: Path
    poll_seconds: float = 5.0
    heartbeat_seconds: float = 20.0
    request_timeout_seconds: float = 30.0
    job_timeout_seconds: float = 48 * 60 * 60
    shutdown_grace_seconds: float = 10.0
    max_dataset_bytes: int = 512 * 1024 * 1024
    max_artifact_bytes: int = 512 * 1024 * 1024
    max_zip_members: int = 100_000

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RunnerConfig:
        values = os.environ if env is None else env
        required = ["PORTAL_URL", "PORTAL_RUNNER_TOKEN", "RUNNER_ID", "RUNNER_WORK_DIR"]
        missing = [key for key in required if not values.get(key, "").strip()]
        if missing:
            raise ValueError(
                f"missing required environment variables: {', '.join(missing)}"
            )

        url = values["PORTAL_URL"].rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("PORTAL_URL must be an absolute http(s) URL")

        return cls(
            portal_url=url,
            token=values["PORTAL_RUNNER_TOKEN"],
            runner_id=values["RUNNER_ID"],
            work_dir=Path(values["RUNNER_WORK_DIR"]).expanduser().resolve(),
            poll_seconds=_positive_number(values, "RUNNER_POLL_SECONDS", 5),
            heartbeat_seconds=_positive_number(values, "RUNNER_HEARTBEAT_SECONDS", 20),
            request_timeout_seconds=_positive_number(
                values, "RUNNER_REQUEST_TIMEOUT_SECONDS", 30
            ),
            job_timeout_seconds=_positive_number(
                values, "RUNNER_JOB_TIMEOUT_SECONDS", 48 * 60 * 60
            ),
            shutdown_grace_seconds=_positive_number(
                values, "RUNNER_SHUTDOWN_GRACE_SECONDS", 10
            ),
            max_dataset_bytes=_positive_int(
                values, "RUNNER_MAX_DATASET_BYTES", 512 * 1024 * 1024
            ),
            max_artifact_bytes=_positive_int(
                values, "RUNNER_MAX_ARTIFACT_BYTES", 512 * 1024 * 1024
            ),
            max_zip_members=_positive_int(values, "RUNNER_MAX_ZIP_MEMBERS", 100_000),
        )


def _positive_number(values: dict[str, str], name: str, default: float) -> float:
    try:
        result = float(values.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if result <= 0:
        raise ValueError(f"{name} must be a positive number")
    return result


def _positive_int(values: dict[str, str], name: str, default: int) -> int:
    try:
        result = int(values.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result

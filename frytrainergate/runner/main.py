"""Long-running FryTrainerGate Runner daemon."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from frytrainergate import PROTOCOL_VERSION
from frytrainergate.shared.protocol import RunnerRegistration, RunnerStatus

from .capabilities import detect_capabilities, platform_name
from .client import RunnerClient
from .worker import TrainingWorker

logger = logging.getLogger("frytrainergate.runner")


class RunnerConfig:
    def __init__(self) -> None:
        self.url = os.environ.get("FRYTRAINERGATE_URL", "").strip()
        self.pairing_token = os.environ.get("FRYTRAINERGATE_PAIRING_TOKEN", "").strip()
        self.name = os.environ.get("FRYTRAINERGATE_RUNNER_NAME", "Runner")[:100]
        self.data_dir = Path(os.environ.get("FRYTRAINERGATE_RUNNER_DATA_DIR", "/data"))
        self.allow_insecure_http = os.environ.get(
            "FRYTRAINERGATE_ALLOW_INSECURE_HTTP", "false"
        ).lower() in {"1", "true", "yes", "on"}
        if not self.url:
            raise ValueError("FRYTRAINERGATE_URL is required")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.chmod(0o700)


class RunnerDaemon:
    def __init__(self, config: RunnerConfig) -> None:
        self.config = config
        self.client = RunnerClient(config.url, config.allow_insecure_http)
        self.capabilities = detect_capabilities(config.data_dir)
        self.current_job_id: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.worker = TrainingWorker(self.client, config.data_dir / "jobs")

    @property
    def credential_file(self) -> Path:
        return self.config.data_dir / "runner.json"

    def load_or_register(self) -> None:
        if self.credential_file.is_file():
            payload = json.loads(self.credential_file.read_text(encoding="utf-8"))
            self.client.set_credentials(
                str(payload["runner_id"]), str(payload["runner_secret"])
            )
            return
        if not self.config.pairing_token:
            raise ValueError(
                "Runner credentials are missing; provide FRYTRAINERGATE_PAIRING_TOKEN for first registration"
            )
        registration = RunnerRegistration(
            pairing_token=self.config.pairing_token,
            runner_version="1.0.0",
            protocol_version=PROTOCOL_VERSION,
            platform=platform_name(),
            hostname=os.environ.get("HOSTNAME", "runner")[:255],
            capabilities=self.capabilities,
        )
        credentials = self.client.register(registration)
        self.client.set_credentials(
            str(credentials["runner_id"]), str(credentials["runner_secret"])
        )
        self.credential_file.write_text(
            json.dumps(
                {
                    "runner_id": credentials["runner_id"],
                    "runner_secret": credentials["runner_secret"],
                    "credential_version": credentials["credential_version"],
                    "protocol_version": credentials["protocol_version"],
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        self.credential_file.chmod(0o600)
        logger.info("Runner registered successfully as %s", credentials["runner_id"])

    def heartbeat_loop(self) -> None:
        while not self._stop.wait(15):
            with self._lock:
                job_id = self.current_job_id
            try:
                self.client.heartbeat(
                    RunnerStatus.BUSY.value if job_id else RunnerStatus.ONLINE.value,
                    job_id,
                    self.capabilities,
                )
            except Exception as error:  # noqa: BLE001
                logger.warning("Heartbeat failed: %s", type(error).__name__)

    def run(self) -> None:
        self.load_or_register()
        self.client.heartbeat(RunnerStatus.ONLINE.value, None, self.capabilities)
        heartbeat = threading.Thread(
            target=self.heartbeat_loop, name="heartbeat", daemon=True
        )
        heartbeat.start()
        try:
            while not self._stop.is_set():
                with self._lock:
                    busy = self.current_job_id is not None
                if busy:
                    time.sleep(1)
                    continue
                try:
                    job = self.client.next_job()
                    if job is None:
                        time.sleep(5)
                        continue
                    with self._lock:
                        self.current_job_id = str(job["id"])
                    self.worker.execute(job)
                except Exception as error:  # noqa: BLE001
                    logger.warning(
                        "Runner polling loop recovered from %s", type(error).__name__
                    )
                    time.sleep(5)
                finally:
                    with self._lock:
                        self.current_job_id = None
        finally:
            self._stop.set()
            heartbeat.join(timeout=5)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("FRYTRAINERGATE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    RunnerDaemon(RunnerConfig()).run()


if __name__ == "__main__":
    main()

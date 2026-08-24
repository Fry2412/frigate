"""Typed registry for Runner training backends.

Backends return a command assembled from trusted implementation code. A job
payload can select a registered backend name, but it can never provide a shell
command or executable path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol


class TrainingBackend(Protocol):
    name: str

    def command(
        self, dataset_dir: Path, spec_path: Path, output_path: Path
    ) -> list[str]: ...


class DevelopmentTestBackend:
    name = "development_test"

    def command(
        self, dataset_dir: Path, spec_path: Path, output_path: Path
    ) -> list[str]:
        return [
            sys.executable,
            "-m",
            "frytrainergate.runner.test_backend",
            "--dataset",
            str(dataset_dir),
            "--spec",
            str(spec_path),
            "--output",
            str(output_path),
        ]


BACKENDS: dict[str, TrainingBackend] = {
    DevelopmentTestBackend.name: DevelopmentTestBackend(),
}


def get_backend(name: str) -> TrainingBackend:
    backend = BACKENDS.get(name)
    if backend is None:
        raise ValueError("training backend is not supported by this Runner")
    return backend

"""Safe local capability detection for the Runner."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

from frytrainergate.shared.protocol import CapabilityInfo


def _nvidia_info() -> tuple[str | None, int | None, bool]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None, None, False
    first = completed.stdout.strip().splitlines()
    if not first:
        return None, None, False
    name, _, memory = first[0].partition(",")
    try:
        vram = int(memory.strip())
    except ValueError:
        vram = None
    return name.strip() or None, vram, True


def detect_capabilities(data_dir: Path) -> CapabilityInfo:
    gpu_name, vram_mb, cuda = _nvidia_info()
    disk_free_mb = shutil.disk_usage(data_dir).free // (1024 * 1024)
    pytorch = False
    try:
        import torch  # type: ignore[import-not-found]

        pytorch = True
        cuda = bool(cuda and torch.cuda.is_available())
    except (ImportError, OSError, RuntimeError):
        pass
    return CapabilityInfo(
        cuda=cuda,
        gpu_name=gpu_name,
        vram_mb=vram_mb,
        cpu_cores=os.cpu_count() or 1,
        system_ram_mb=None,
        disk_free_mb=disk_free_mb,
        pytorch=pytorch,
        onnx_export=False,
        training_backends=["development_test"],
        model_architectures=["development_test"],
    )


def platform_name() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"

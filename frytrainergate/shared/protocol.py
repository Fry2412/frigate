"""Versioned FryTrainerGate controller/runner protocol models.

The models deliberately describe structured job data.  A job never contains a
shell command or an executable path supplied by the controller.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from frytrainergate import PROTOCOL_VERSION


class RunnerStatus(str, Enum):
    ONLINE = "ONLINE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"
    DISABLED = "DISABLED"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    WAITING_FOR_RUNNER = "WAITING_FOR_RUNNER"
    ASSIGNED = "ASSIGNED"
    PREPARING = "PREPARING"
    DOWNLOADING_DATASET = "DOWNLOADING_DATASET"
    TRAINING = "TRAINING"
    VALIDATING = "VALIDATING"
    EXPORTING = "EXPORTING"
    UPLOADING = "UPLOADING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    RUNNER_LOST = "RUNNER_LOST"


class CapabilityInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cuda: bool = False
    gpu_name: str | None = None
    vram_mb: int | None = Field(default=None, ge=0, le=2_000_000)
    cpu_cores: int = Field(default=1, ge=1, le=4096)
    system_ram_mb: int | None = Field(default=None, ge=0, le=4_000_000)
    disk_free_mb: int | None = Field(default=None, ge=0, le=10_000_000_000)
    pytorch: bool = False
    onnx_export: bool = False
    training_backends: list[str] = Field(
        default_factory=lambda: ["development_test"], max_length=32
    )
    model_architectures: list[str] = Field(default_factory=list, max_length=64)


class RunnerRegistration(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pairing_token: str = Field(min_length=20, max_length=512)
    runner_version: str = Field(default="unknown", min_length=1, max_length=64)
    protocol_version: str = Field(default=PROTOCOL_VERSION, max_length=32)
    platform: str = Field(default="unknown", max_length=128)
    hostname: str = Field(default="unknown", max_length=255)
    capabilities: CapabilityInfo = Field(default_factory=CapabilityInfo)


class RunnerSessionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    runner_id: str = Field(min_length=1, max_length=64)
    runner_secret: str = Field(min_length=32, max_length=512)
    protocol_version: str = Field(default=PROTOCOL_VERSION, max_length=32)


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    runner_version: str = Field(default="unknown", max_length=64)
    protocol_version: str = Field(default=PROTOCOL_VERSION, max_length=32)
    status: RunnerStatus = RunnerStatus.ONLINE
    current_job_id: str | None = Field(default=None, max_length=64)
    capabilities: CapabilityInfo | None = None


class JobRequirements(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requires_cuda: bool = False
    minimum_vram_mb: int = Field(default=0, ge=0, le=2_000_000)
    minimum_disk_mb: int = Field(default=0, ge=0, le=10_000_000_000)
    training_backend: str = Field(
        default="development_test", min_length=1, max_length=64
    )


class TrainingJobSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_model: str | None = Field(default=None, max_length=255)
    student_architecture: str | None = Field(default=None, max_length=128)
    teacher_models: list[dict[str, Any]] = Field(default_factory=list, max_length=16)
    epochs: int = Field(default=1, ge=1, le=100_000)
    batch_size: int = Field(default=1, ge=1, le=4096)
    image_size: int = Field(default=640, ge=32, le=8192)
    learning_rate: float = Field(default=0.001, gt=0, lt=100)
    augmentation: dict[str, Any] = Field(default_factory=dict)
    export_targets: list[str] = Field(default_factory=list, max_length=16)


class ProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state: JobState
    progress: float = Field(ge=0, le=100)
    current_epoch: int | None = Field(default=None, ge=0)
    total_epochs: int | None = Field(default=None, ge=0)
    status_message: str | None = Field(default=None, max_length=500)


class JobCompletion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metrics: dict[str, Any] = Field(default_factory=dict)


class JobFailure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reason: str = Field(min_length=1, max_length=2000)


class PairingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    lifetime_seconds: int = Field(default=600, ge=60, le=3600)


class RunnerRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class JobCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    dataset_id: str = Field(min_length=1, max_length=64)
    runner_id: str | None = Field(default=None, max_length=64)
    backend: str = Field(default="development_test", min_length=1, max_length=64)
    config: TrainingJobSpec = Field(default_factory=TrainingJobSpec)
    requirements: JobRequirements = Field(default_factory=JobRequirements)

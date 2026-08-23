from enum import Enum
from typing import Optional, Union

from pydantic import Field, field_validator, model_validator

from ..base import FrigateBaseModel
from ..env import EnvString
from .objects import DEFAULT_TRACKED_OBJECTS

__all__ = [
    "AutoZoomConfig",
    "AutoZoomFramingConfig",
    "AutoZoomReturnConfig",
    "AutoZoomTrackingConfig",
    "AutoZoomZoomConfig",
    "OnvifConfig",
    "PtzAutotrackConfig",
    "ZoomingModeEnum",
]


class ZoomingModeEnum(str, Enum):
    disabled = "disabled"
    absolute = "absolute"
    relative = "relative"


class AutoZoomModeEnum(str, Enum):
    auto = "auto"
    absolute = "absolute"
    relative = "relative"


class AutoZoomFramingConfig(FrigateBaseModel):
    preset: str = Field(
        default="balanced",
        title="Framing",
        description="Wide, balanced, tight, or custom framing.",
    )
    target_margin: float = Field(
        default=0.17,
        title="Target margin",
        description="Safe inset from every image edge while zooming in.",
        gt=0,
        lt=0.5,
    )
    emergency_margin: float = Field(
        default=0.05,
        title="Emergency margin",
        description="Inset that triggers an immediate zoom-out.",
        ge=0,
        lt=0.5,
    )

    @model_validator(mode="before")
    @classmethod
    def apply_preset_margin(cls, values):
        if not isinstance(values, dict) or "target_margin" in values:
            return values
        margins = {"wide": 0.25, "balanced": 0.17, "tight": 0.10}
        if values.get("preset") in margins:
            return {**values, "target_margin": margins[values["preset"]]}
        return values


class AutoZoomZoomConfig(FrigateBaseModel):
    min: float = Field(
        default=0.0,
        title="Minimum zoom",
        description="Minimum normalized zoom level.",
        ge=0,
        le=1,
    )
    max: float = Field(
        default=0.8,
        title="Maximum zoom",
        description="Maximum normalized zoom level.",
        gt=0,
        le=1,
    )
    zoom_in_step: float = Field(
        default=0.05,
        title="Zoom-in step",
        description="Conservative normalized zoom increment.",
        gt=0,
        le=1,
    )
    zoom_out_step: float = Field(
        default=0.12,
        title="Zoom-out step",
        description="Normalized zoom decrement when framing is unsafe.",
        gt=0,
        le=1,
    )
    emergency_zoom_out_step: float = Field(
        default=0.25,
        title="Emergency zoom-out step",
        description="Normalized zoom decrement used near an image edge.",
        gt=0,
        le=1,
    )


class AutoZoomTrackingConfig(FrigateBaseModel):
    activation_delay: float = Field(
        default=0.4,
        title="Activation delay",
        description="Seconds an eligible object must remain stable before Auto Zoom starts.",
        ge=0,
    )
    prediction_horizon: float = Field(
        default=0.75,
        title="Prediction horizon",
        description="Seconds of object motion considered before moving zoom.",
        ge=0,
        le=5,
    )
    reacquire_timeout: float = Field(
        default=1.5,
        title="Reacquire timeout",
        description="Seconds to wait for the locked target after a temporary loss.",
        ge=0,
    )
    settle_time: float = Field(
        default=0.35,
        title="Settle time",
        description="Seconds to wait after a normal zoom command before another zoom-in.",
        ge=0,
    )
    manual_override_timeout: float = Field(
        default=30,
        title="Manual override timeout",
        description="Seconds Auto Zoom remains paused after a manual PTZ command.",
        ge=0,
    )


class AutoZoomReturnConfig(FrigateBaseModel):
    mode: str = Field(
        default="previous",
        title="Return mode",
        description="Restore the zoom level that was active before tracking.",
    )
    timeout: float = Field(
        default=5,
        title="Return timeout",
        description="Seconds to wait after tracking ends before restoring previous zoom.",
        ge=0,
    )


class AutoZoomConfig(FrigateBaseModel):
    enabled: bool = Field(
        default=False,
        title="Enable Auto Zoom",
        description="Automatically zoom in on detected objects while preserving safe framing.",
    )
    mode: AutoZoomModeEnum = Field(
        default=AutoZoomModeEnum.auto,
        title="Zoom mode",
        description="Auto prefers absolute ONVIF zoom, then relative zoom.",
    )
    track: list[str] = Field(
        default=DEFAULT_TRACKED_OBJECTS,
        title="Objects",
        description="Object labels that may start Auto Zoom.",
    )
    required_zones: list[str] = Field(
        default_factory=list,
        title="Trigger zones",
        description="Objects must enter one of these zones before Auto Zoom starts.",
    )
    framing: AutoZoomFramingConfig = Field(
        default_factory=AutoZoomFramingConfig, title="Framing"
    )
    zoom: AutoZoomZoomConfig = Field(default_factory=AutoZoomZoomConfig, title="Zoom")
    tracking: AutoZoomTrackingConfig = Field(
        default_factory=AutoZoomTrackingConfig, title="Tracking"
    )
    return_: AutoZoomReturnConfig = Field(
        default_factory=AutoZoomReturnConfig, alias="return", title="Return"
    )

    @model_validator(mode="after")
    def validate_autozoom(self):
        if self.framing.target_margin <= self.framing.emergency_margin:
            raise ValueError(
                "autozoom.framing.target_margin must be greater than emergency_margin"
            )
        if self.zoom.min >= self.zoom.max:
            raise ValueError("autozoom.zoom.min must be less than max")
        if self.zoom.zoom_out_step < self.zoom.zoom_in_step:
            raise ValueError(
                "autozoom.zoom.zoom_out_step must be at least zoom_in_step"
            )
        if self.zoom.emergency_zoom_out_step < self.zoom.zoom_out_step:
            raise ValueError(
                "autozoom.zoom.emergency_zoom_out_step must be at least zoom_out_step"
            )
        if self.return_.mode != "previous":
            raise ValueError("autozoom.return.mode currently only supports 'previous'")
        return self


class PtzAutotrackConfig(FrigateBaseModel):
    enabled: bool = Field(
        default=False,
        title="Enable Autotracking",
        description="Enable or disable automatic PTZ camera tracking of detected objects.",
    )
    calibrate_on_startup: bool = Field(
        default=False,
        title="Calibrate on start",
        description="Measure PTZ motor speeds on startup to improve tracking accuracy. Frigate will update config with movement_weights after calibration.",
    )
    zooming: ZoomingModeEnum = Field(
        default=ZoomingModeEnum.disabled,
        title="Zoom mode",
        description="Control zoom behavior: disabled (pan/tilt only), absolute (most compatible), or relative (concurrent pan/tilt/zoom).",
    )
    zoom_factor: float = Field(
        default=0.3,
        title="Zoom factor",
        description="Control zoom level on tracked objects. Lower values keep more scene in view; higher values zoom in closer but may lose tracking. Values between 0.1 and 0.75.",
        ge=0.1,
        le=0.75,
    )
    track: list[str] = Field(
        default=DEFAULT_TRACKED_OBJECTS,
        title="Tracked objects",
        description="List of object types that should trigger autotracking.",
    )
    required_zones: list[str] = Field(
        default_factory=list,
        title="Required zones",
        description="Objects must enter one of these zones before autotracking begins.",
    )
    return_preset: str = Field(
        default="home",
        title="Return preset",
        description="ONVIF preset name configured in camera firmware to return to after tracking ends.",
    )
    timeout: int = Field(
        default=10,
        title="Return timeout",
        description="Wait this many seconds after losing tracking before returning camera to preset position.",
    )
    movement_weights: Optional[Union[str, list[str]]] = Field(
        default_factory=list,
        title="Movement weights",
        description="Calibration values automatically generated by camera calibration. Do not modify manually.",
    )
    enabled_in_config: Optional[bool] = Field(
        default=None,
        title="Original autotrack state",
        description="Internal field to track whether autotracking was enabled in configuration.",
    )

    @field_validator("movement_weights", mode="before")
    @classmethod
    def validate_weights(cls, v):
        if v is None:
            return None

        if isinstance(v, str):
            weights = list(map(str, map(float, v.split(","))))
        elif isinstance(v, list):
            weights = [str(float(val)) for val in v]
        else:
            raise ValueError("Invalid type for movement_weights")

        if len(weights) != 6:
            raise ValueError(
                "movement_weights must have exactly 6 floats, remove this line from your config and run autotracking calibration"
            )

        return weights


class OnvifConfig(FrigateBaseModel):
    host: EnvString = Field(
        default="",
        title="ONVIF host",
        description="Host (and optional scheme) for the ONVIF service for this camera.",
    )
    port: int = Field(
        default=8000,
        title="ONVIF port",
        description="Port number for the ONVIF service.",
    )
    user: Optional[EnvString] = Field(
        default=None,
        title="ONVIF username",
        description="Username for ONVIF authentication; some devices require admin user for ONVIF.",
    )
    password: Optional[EnvString] = Field(
        default=None,
        title="ONVIF password",
        description="Password for ONVIF authentication.",
    )
    tls_insecure: bool = Field(
        default=False,
        title="Disable TLS verify",
        description="Skip TLS verification and disable digest auth for ONVIF (unsafe; use in safe networks only).",
    )
    profile: Optional[str] = Field(
        default=None,
        title="ONVIF profile",
        description="Specific ONVIF media profile to use for PTZ control, matched by token or name. If not set, the first profile with valid PTZ configuration is selected automatically.",
    )
    autotracking: PtzAutotrackConfig = Field(
        default_factory=PtzAutotrackConfig,
        title="Autotracking",
        description="Automatically track moving objects and keep them centered in the frame using PTZ camera movements.",
    )
    autozoom: AutoZoomConfig = Field(
        default_factory=AutoZoomConfig,
        title="Object Auto Zoom",
        description="Zoom-only automatic object framing for fixed-view ONVIF cameras.",
    )
    ignore_time_mismatch: bool = Field(
        default=False,
        title="Ignore time mismatch",
        description="Ignore time synchronization differences between camera and Frigate server for ONVIF communication.",
    )

    @model_validator(mode="after")
    def validate_controller_ownership(self):
        if self.autotracking.enabled and self.autozoom.enabled:
            raise ValueError(
                "PTZ autotracking and Auto Zoom cannot be enabled on the same camera"
            )
        return self

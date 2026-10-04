"""Assisted person/animal journeys; event links never assert global identity."""

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

from frigate.record.multicam import MultiCamPlan, Shot

FOLLOW_LABELS = {
    "person",
    "cat",
    "dog",
    "bird",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "deer",
    "fox",
    "rabbit",
    "raccoon",
    "squirrel",
    "goat",
    "chicken",
}


class JourneyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    cameras: list[str] = Field(min_length=1, max_length=4)
    after: float = Field(ge=0)
    before: float = Field(ge=0)
    seed_id: str | None = Field(default=None, max_length=30)
    selected_event_ids: list[str] = Field(default_factory=list, max_length=64)
    mode: str = Field(default="follow", pattern="^(follow|grid)$")
    min_shot: float = Field(default=3, ge=1, le=10)
    pre_capture: float = Field(default=2, ge=0, le=10)
    post_capture: float = Field(default=2, ge=0, le=10)
    # Optional directional camera topology, supplied for this investigation.
    transitions: dict[str, list[str]] = Field(default_factory=dict)
    clock_offsets: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_window(self):
        if not 0 < self.before - self.after <= 3600:
            raise ValueError("Journey search must span at most 60 minutes")
        cameras = set(self.cameras)
        if len(cameras) != len(self.cameras):
            raise ValueError("Duplicate source camera")
        if any(
            camera not in cameras
            or len(targets) > 4
            or not set(targets).issubset(cameras)
            for camera, targets in self.transitions.items()
        ):
            raise ValueError("Transitions must use selected source cameras")
        if any(
            camera not in cameras or not math.isfinite(offset) or abs(offset) > 30
            for camera, offset in self.clock_offsets.items()
        ):
            raise ValueError("Invalid camera clock offset")
        return self


def build_journey_plan(events: list[dict], body: JourneyRequest) -> MultiCamPlan:
    """Use only manually confirmed observations, with deterministic hysteresis.

    During overlaps follow the most recently entered view. A minimum shot
    length suppresses brief competing observations while the current camera
    still observes the target. Lost intervals become explicit empty shots.
    """
    if not events or body.seed_id not in {event["id"] for event in events}:
        raise ValueError("Select the seed event and confirm its observations")
    labels = {event["label"] for event in events}
    if len(labels) != 1 or not labels.issubset(FOLLOW_LABELS):
        raise ValueError("A journey must link one person or animal label")
    observations = [
        {
            **event,
            "start": max(body.after, event["start_time"] - body.pre_capture),
            "end": min(
                body.before, (event["end_time"] or body.before) + body.post_capture
            ),
        }
        for event in events
    ]
    observations = [event for event in observations if event["end"] > event["start"]]
    points = sorted(
        {
            point
            for event in observations
            for point in (
                event["start"],
                event["end"],
                min(event["end"], event["start"] + body.min_shot),
            )
        }
    )
    shots = []
    previous = []
    last_switch = points[0] if points else 0
    for start, end in zip(points, points[1:]):
        if end <= start:
            continue
        active = sorted(
            [event for event in observations if event["start"] <= start < event["end"]],
            key=lambda event: (event["start_time"], event["id"]),
            reverse=True,
        )
        cameras = list(dict.fromkeys(event["camera"] for event in active))
        if body.mode == "follow":
            cameras = cameras[:1]
            if (
                previous
                and previous[0] in {event["camera"] for event in active}
                and start - last_switch < body.min_shot
            ):
                cameras = previous
        if cameras != previous:
            last_switch = start
        ids = sorted(event["id"] for event in active if event["camera"] in cameras)
        if shots and shots[-1].cameras == cameras:
            shots[-1].end = end
            shots[-1].event_ids = sorted(set(shots[-1].event_ids) | set(ids))
        elif end - start < 0.2 and shots:
            # Sub-frame slivers cannot form useful cuts; keep the previous
            # view for that fraction, rather than imply a new identity join.
            shots[-1].end = end
        else:
            shots.append(Shot(start=start, end=end, cameras=cameras, event_ids=ids))
        previous = cameras
    sources = {camera for shot in shots for camera in shot.cameras}
    return MultiCamPlan(
        shots=shots,
        clock_offsets={
            camera: offset
            for camera, offset in body.clock_offsets.items()
            if camera in sources
        },
    )

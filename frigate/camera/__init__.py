import multiprocessing as mp
import queue
from multiprocessing.managers import SyncManager, ValueProxy
from multiprocessing.sharedctypes import Synchronized
from multiprocessing.synchronize import Event

# Auto Zoom automation states matching the data-model AutoZoomSession.automation_state
AUTO_ZOOM_STATES = (
    "off",
    "ready",
    "tracking",
    "holding",
    "returning_home",
    "paused_manual",
    "suspended",
)

# Auto Zoom camera support classifications
AUTO_ZOOM_SUPPORT_CLASSES = ("none", "zoom_only", "full_ptz", "limited")
AUTO_ZOOM_SUPPORT_STATUSES = ("supported", "degraded", "unsupported")


class CameraMetrics:
    camera_fps: ValueProxy[float]
    detection_fps: ValueProxy[float]
    detection_frame: ValueProxy[float]
    process_fps: ValueProxy[float]
    skipped_fps: ValueProxy[float]
    read_start: ValueProxy[float]
    audio_rms: ValueProxy[float]
    audio_dBFS: ValueProxy[float]

    frame_queue: queue.Queue

    process_pid: ValueProxy[int]
    capture_process_pid: ValueProxy[int]
    ffmpeg_pid: ValueProxy[int]
    reconnects_last_hour: ValueProxy[int]
    stalls_last_hour: ValueProxy[int]

    def __init__(self, manager: SyncManager):
        self.camera_fps = manager.Value("d", 0)
        self.detection_fps = manager.Value("d", 0)
        self.detection_frame = manager.Value("d", 0)
        self.process_fps = manager.Value("d", 0)
        self.skipped_fps = manager.Value("d", 0)
        self.read_start = manager.Value("d", 0)
        self.audio_rms = manager.Value("d", 0)
        self.audio_dBFS = manager.Value("d", 0)

        self.frame_queue = manager.Queue(maxsize=2)

        self.process_pid = manager.Value("i", 0)
        self.capture_process_pid = manager.Value("i", 0)
        self.ffmpeg_pid = manager.Value("i", 0)
        self.reconnects_last_hour = manager.Value("i", 0)
        self.stalls_last_hour = manager.Value("i", 0)


class PTZMetrics:
    autotracker_enabled: Synchronized

    start_time: Synchronized
    stop_time: Synchronized
    frame_time: Synchronized
    zoom_level: Synchronized
    max_zoom: Synchronized
    min_zoom: Synchronized

    tracking_active: Event
    motor_stopped: Event
    reset: Event

    def __init__(self, *, autotracker_enabled: bool):
        self.autotracker_enabled = mp.Value("i", autotracker_enabled)  # type: ignore[assignment]

        self.start_time = mp.Value("d", 0)  # type: ignore[assignment]
        self.stop_time = mp.Value("d", 0)  # type: ignore[assignment]
        self.frame_time = mp.Value("d", 0)  # type: ignore[assignment]
        self.zoom_level = mp.Value("d", 0)  # type: ignore[assignment]
        self.max_zoom = mp.Value("d", 0)  # type: ignore[assignment]
        self.min_zoom = mp.Value("d", 0)  # type: ignore[assignment]

        self.tracking_active = mp.Event()
        self.motor_stopped = mp.Event()
        self.reset = mp.Event()

        self.motor_stopped.set()


class AutoZoomMetrics:
    """Shared-memory metrics for the Auto Zoom feature on one camera."""

    auto_zoom_enabled: Synchronized
    automation_state: ValueProxy[str]
    current_zoom_level: Synchronized
    desired_zoom_level: Synchronized
    primary_target_id: ValueProxy[str]
    last_action: ValueProxy[str]
    last_action_reason: ValueProxy[str]
    last_suppression_reason: ValueProxy[str]
    support_status: ValueProxy[str]

    active: Event
    manual_override: Event

    def __init__(self, *, enabled: bool, manager: SyncManager):
        self.auto_zoom_enabled = mp.Value("i", enabled)  # type: ignore[assignment]
        self.automation_state = manager.Value(str, "off")
        self.current_zoom_level = mp.Value("d", 0.0)  # type: ignore[assignment]
        self.desired_zoom_level = mp.Value("d", 0.0)  # type: ignore[assignment]
        self.primary_target_id = manager.Value(str, "")
        self.last_action = manager.Value(str, "none")
        self.last_action_reason = manager.Value(str, "")
        self.last_suppression_reason = manager.Value(str, "")
        self.support_status = manager.Value(str, "unsupported")

        self.active = mp.Event()
        self.manual_override = mp.Event()

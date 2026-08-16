import { Recording } from "@/types/record";
import { DynamicPlayback } from "@/types/playback";
import { PreviewController } from "../PreviewPlayer";
import { TimeRange, TrackingDetailsSequence } from "@/types/timeline";
import {
  calculateInpointOffset,
  calculateSeekPosition,
  playWithTemporaryMuteFallback,
} from "@/utils/videoUtil";

const SEEK_PLAY_FALLBACK_MS = 1000;

type PlayerMode = "playback" | "scrubbing";

export class DynamicVideoController {
  // main state
  public camera = "";
  private playerController: HTMLVideoElement;
  private previewController?: PreviewController;
  private setNoRecording: (noRecs: boolean) => void;
  private setFocusedItem: (timeline: TrackingDetailsSequence) => void;
  private playerMode: PlayerMode = "playback";

  // playback
  private recordings: Recording[] = [];
  private timeRange: TimeRange = { after: 0, before: 0 };
  private inpointOffset: number = 0;
  private annotationOffset: number;

  constructor(
    camera: string,
    playerController: HTMLVideoElement,
    previewController: PreviewController | undefined,
    annotationOffset: number,
    defaultMode: PlayerMode,
    setNoRecording: (noRecs: boolean) => void,
    setFocusedItem: (timeline: TrackingDetailsSequence) => void,
  ) {
    this.camera = camera;
    this.playerController = playerController;
    this.previewController = previewController;
    this.annotationOffset = annotationOffset;
    this.playerMode = defaultMode;
    this.setNoRecording = setNoRecording;
    this.setFocusedItem = setFocusedItem;
  }

  newPlayback(newPlayback: DynamicPlayback) {
    this.recordings = newPlayback.recordings;
    this.timeRange = newPlayback.timeRange;
    this.inpointOffset = calculateInpointOffset(
      this.timeRange.after,
      this.recordings[0],
    );
  }

  play() {
    this.playerController.play();
  }

  pause() {
    this.playerController.pause();
  }

  setPlaybackRate(rate: number) {
    this.playerController.playbackRate = rate;
  }

  isPlaying(): boolean {
    return !this.playerController.paused && !this.playerController.ended;
  }

  seekToTimestamp(time: number, play: boolean = false) {
    // a seek outside the current playback window is a no-op: the view
    // moves its anchor and chunk on such seeks, and the rebuilt source
    // resumes at the anchor (startPosition plus the post-load seek).
    // Seeking here would only reposition the outgoing source's media
    if (time < this.timeRange.after || time > this.timeRange.before) {
      return;
    }

    if (this.playerMode != "playback") {
      this.playerMode = "playback";
    }

    const seekSeconds = calculateSeekPosition(
      time,
      this.recordings,
      this.inpointOffset,
    );

    if (seekSeconds === undefined) {
      this.setNoRecording(true);
      return;
    }

    if (this.playerController.currentTime === seekSeconds) {
      // seeking to the current position fires no seeked event, so apply
      // the play intent directly (this includes position 0, which the
      // player sits at before its first seek)
      if (play) {
        playWithTemporaryMuteFallback(this.playerController);
      } else {
        this.playerController.pause();
      }
      return;
    }

    this.playerController.currentTime = seekSeconds;

    if (play) {
      this.waitAndPlay();
    } else {
      this.playerController.pause();
    }
  }

  waitAndPlay() {
    return new Promise((resolve) => {
      let fallback: NodeJS.Timeout | undefined;

      const onSeekedHandler = () => {
        clearTimeout(fallback);
        this.playerController.removeEventListener("seeked", onSeekedHandler);
        playWithTemporaryMuteFallback(this.playerController);
        resolve(undefined);
      };

      this.playerController.addEventListener("seeked", onSeekedHandler, {
        once: true,
      });

      // iOS ManagedMediaSource pauses hls.js buffering, so `seeked` may
      // never fire; playing is what prompts WebKit to resume streaming
      if ("ManagedMediaSource" in window) {
        fallback = setTimeout(onSeekedHandler, SEEK_PLAY_FALLBACK_MS);
      }
    });
  }

  seekToTimelineItem(timeline: TrackingDetailsSequence) {
    this.playerController.pause();
    this.seekToTimestamp(timeline.timestamp + this.annotationOffset);
    this.setFocusedItem(timeline);
  }

  getProgress(playerTime: number): number {
    // take a player time in seconds and convert to timestamp in timeline
    const recordings = this.recordings || [];
    let totalTime = 0;
    for (const segment of recordings) {
      if (totalTime + segment.duration > playerTime) {
        // playlist media from before the span's wall start (keyframe
        // back-snap lead-in) clamps to the span start
        const wallLength = segment.end_time - segment.start_time;
        const leadIn = Math.max(0, segment.duration - wallLength);
        return (
          segment.start_time + Math.max(0, playerTime - totalTime - leadIn)
        );
      }
      totalTime += segment.duration;
    }

    // past the modeled total: clamp to the covered end rather than
    // reporting wall-clock zero
    return recordings.length > 0
      ? recordings[recordings.length - 1].end_time
      : 0;
  }

  scrubToTimestamp(time: number, saveIfNotReady: boolean = false) {
    if (!this.previewController) {
      return;
    }

    const scrubResult = this.previewController.scrubToTimestamp(time);

    if (!scrubResult && saveIfNotReady) {
      this.previewController.setNewPreviewStartTime(time);
    }

    // pause even when no preview can render this range: a hidden player
    // left running reports stale times once the drag releases, bouncing
    // the handlebar back and sometimes swallowing the release seek
    if (this.playerMode != "scrubbing") {
      this.playerMode = "scrubbing";
      this.playerController.pause();
    }
  }

  /**
   * Keep a secondary high-resolution player close to the master's timeline.
   * Seeking is deliberately thresholded to avoid restarting HLS playback on
   * every timeupdate event while still correcting meaningful drift.
   */
  synchronizeToTimestamp(
    time: number,
    play: boolean,
    toleranceSeconds: number = 0.35,
  ): boolean {
    if (!this.recordings.length) {
      return false;
    }

    const seekSeconds = calculateSeekPosition(
      time,
      this.recordings,
      this.inpointOffset,
    );

    if (seekSeconds === undefined) {
      // Do not let a player keep advancing through the concatenated VOD
      // playlist while the shared timeline is inside a gap for this camera.
      // It will be resumed automatically as soon as a later shared timestamp
      // belongs to one of its recording segments.
      this.playerController.pause();
      return false;
    }

    if (
      !Number.isFinite(this.playerController.currentTime) ||
      Math.abs(this.playerController.currentTime - seekSeconds) >
        toleranceSeconds
    ) {
      this.playerController.currentTime = seekSeconds;
    }

    if (play) {
      if (!this.isPlaying()) {
        void this.playerController.play();
      }
    } else if (this.isPlaying()) {
      this.playerController.pause();
    }

    return true;
  }

  hasRecordingAtTime(time: number): boolean {
    if (!this.recordings || this.recordings.length == 0) {
      return false;
    }

    return (
      this.recordings.find(
        (segment) => segment.start_time <= time && segment.end_time >= time,
      ) != undefined
    );
  }
}

export default typeof DynamicVideoController;

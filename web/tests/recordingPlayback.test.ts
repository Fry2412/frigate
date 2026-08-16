import { describe, expect, it, vi } from "vitest";
import { calculateSeekPosition } from "../src/utils/videoUtil";
import { DynamicVideoController } from "../src/components/player/dynamic/DynamicVideoController";
import type { Recording } from "../src/types/record";

function recording(
  start: number,
  end: number,
  duration = end - start,
): Recording {
  return {
    id: String(start),
    camera: "test",
    start_time: start,
    end_time: end,
    duration,
    path: "",
    segment_size: 0,
    motion: 0,
    objects: 0,
    dBFS: 0,
  };
}

describe("absolute-time multicamera playback", () => {
  it("rejects gaps instead of seeking to an unrelated next recording", () => {
    const clips = [recording(100, 110), recording(120, 130)];
    expect(calculateSeekPosition(115, clips)).toBeUndefined();
    expect(calculateSeekPosition(125, clips)).toBe(15);
  });

  it("includes keyframe lead-in while mapping to wall clock", () => {
    const clips = [recording(100, 110, 12), recording(120, 130, 11)];
    expect(calculateSeekPosition(105, clips)).toBe(7);
    expect(calculateSeekPosition(125, clips)).toBe(18);
    const video = {
      currentTime: 0,
      paused: true,
      pause: vi.fn(),
    } as unknown as HTMLVideoElement;
    const controller = new DynamicVideoController(
      "test",
      video,
      undefined,
      0,
      "playback",
      vi.fn(),
      vi.fn(),
    );
    controller.newPlayback({
      recordings: clips,
      timeRange: { after: 100, before: 130 },
    });
    expect(controller.getProgress(18)).toBe(125);
    expect(controller.getProgress(1)).toBe(100);
  });

  it("keeps two cameras with different coverage on the same absolute timestamp", () => {
    const clips = [
      [recording(100, 110), recording(120, 130)],
      [recording(120, 130, 12)],
    ];
    const players = clips.map((recordings, i) => {
      const video = {
        currentTime: 0,
        paused: true,
        pause: vi.fn(),
        play: vi.fn(),
      } as unknown as HTMLVideoElement;
      const controller = new DynamicVideoController(
        String(i),
        video,
        undefined,
        0,
        "playback",
        vi.fn(),
        vi.fn(),
      );
      controller.newPlayback({
        recordings,
        timeRange: { after: 100, before: 130 },
      });
      controller.synchronizeToTimestamp(125, false);
      return { video, controller };
    });
    expect(players[0].video.currentTime).toBe(15);
    expect(players[1].video.currentTime).toBe(7);
    for (const { video, controller } of players)
      expect(controller.getProgress(video.currentTime)).toBe(125);
  });
});

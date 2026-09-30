import { describe, expect, it } from "vitest";
import { LiveStreamGovernor } from "@/components/player/LiveStreamGovernor";

describe("auto live stream policy", () => {
  it("steps down on congestion and retries higher quality after recovery", () => {
    let now = 4000;
    const governor = new LiveStreamGovernor(4, () => now);
    now += 4000;
    governor.sample({ bytes: 1000, mediaSeconds: 1, wallSeconds: 3 });
    expect(governor.getSnapshot().rung).toBe(1);
    now += 61000;
    governor.tick();
    expect(governor.getSnapshot().rung).toBe(0);
  });

  it("distinguishes offline cameras from a stalled online stream", () => {
    const governor = new LiveStreamGovernor(4);
    expect(governor.playerError("stalled", false)).toBe(false);
    expect(governor.getSnapshot().rung).toBe(0);
    expect(governor.playerError("stalled", true)).toBe(true);
    expect(governor.getSnapshot().rung).toBe(1);
  });

  it("holds data saver at the lowest stream and skips unsupported codecs", () => {
    let now = 0;
    const governor = new LiveStreamGovernor(4, () => now);
    governor.setHoldLow(true);
    expect(governor.getSnapshot().rung).toBe(2);
    now = 61000;
    governor.tick();
    expect(governor.getSnapshot().rung).toBe(2);
    governor.setHoldLow(false);
    governor.reset();
    governor.playerError("mse-codec", true);
    now += 61000;
    governor.tick();
    expect(governor.getSnapshot().rung).toBe(1);
  });
});

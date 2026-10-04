import { describe, expect, it } from "vitest";
import { MultiCamPlan } from "@/types/multicam";
import { isMultiCamPlan, locatePlanTime, splitPlanShot } from "@/utils/multicamPlan";

const plan: MultiCamPlan = { version: 1, stream: "auto", width: 1280, fps: 15, audio_camera: null, clock_offsets: {}, shots: [
  { start: 100, end: 110, cameras: ["front", "garden"] },
  { start: 120, end: 130, cameras: ["garden"] },
] };

describe("multicam edit plan", () => {
  it("maps output time across cuts without inventing source continuity", () => {
    expect(locatePlanTime(plan.shots, 9)?.timestamp).toBe(109);
    expect(locatePlanTime(plan.shots, 10)).toEqual({ index: 1, timestamp: 120, outputStart: 10 });
    expect(locatePlanTime(plan.shots, 15)?.timestamp).toBe(125);
  });
  it("splits immutably while retaining the exact source times and cameras", () => {
    const edited = splitPlanShot(plan, 0, 104);
    expect(edited.shots.map(shot => [shot.start, shot.end])).toEqual([[100, 104], [104, 110], [120, 130]]);
    expect(edited.shots[1].cameras).toEqual(["front", "garden"]);
    expect(plan.shots).toHaveLength(2);
    expect(splitPlanShot(plan, 0, 110)).toBe(plan);
  });
  it("rejects incompatible or malformed saved plans before rendering them", () => {
    expect(isMultiCamPlan(plan)).toBe(true);
    expect(isMultiCamPlan({ ...plan, version: 2 })).toBe(false);
    expect(isMultiCamPlan({ ...plan, shots: [{ start: Infinity, end: 120, cameras: ["front"] }] })).toBe(false);
    expect(isMultiCamPlan({ ...plan, shots: [] })).toBe(false);
  });
});

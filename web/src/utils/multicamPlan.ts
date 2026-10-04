import { MultiCamPlan, MultiCamShot } from "@/types/multicam";

export function locatePlanTime(shots: MultiCamShot[], outputTime: number) {
  let offset = 0;
  for (let index = 0; index < shots.length; index++) {
    const shot = shots[index];
    const duration = shot.end - shot.start;
    if (outputTime < offset + duration || index === shots.length - 1) {
      return {
        index,
        timestamp:
          shot.start +
          Math.max(0, Math.min(duration - 0.001, outputTime - offset)),
        outputStart: offset,
      };
    }
    offset += duration;
  }
  return undefined;
}

export function splitPlanShot(
  plan: MultiCamPlan,
  index: number,
  timestamp: number,
): MultiCamPlan {
  const shot = plan.shots[index];
  if (
    !shot ||
    timestamp - shot.start < 0.2 ||
    shot.end - timestamp < 0.2 ||
    plan.shots.length >= 64
  )
    return plan;
  return {
    ...plan,
    shots: [
      ...plan.shots.slice(0, index),
      { ...shot, end: timestamp },
      { ...shot, start: timestamp },
      ...plan.shots.slice(index + 1),
    ],
  };
}

export function isMultiCamPlan(value: unknown): value is MultiCamPlan {
  if (!value || typeof value !== "object") return false;
  const plan = value as MultiCamPlan;
  return (
    plan.version === 1 &&
    Array.isArray(plan.shots) &&
    plan.shots.length > 0 &&
    plan.shots.length <= 64 &&
    plan.shots.every(
      (shot) =>
        Number.isFinite(shot.start) &&
        Number.isFinite(shot.end) &&
        shot.end > shot.start &&
        Array.isArray(shot.cameras) &&
        shot.cameras.length <= 4 &&
        shot.cameras.every((camera) => typeof camera === "string"),
    ) &&
    ["auto", "main", "sub"].includes(plan.stream) &&
    [1280, 1920].includes(plan.width) &&
    [15, 25, 30].includes(plan.fps) &&
    (plan.audio_camera === null || typeof plan.audio_camera === "string") &&
    typeof plan.clock_offsets === "object" &&
    plan.clock_offsets !== null
  );
}

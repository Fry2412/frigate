export type MultiCamShot = {
  start: number;
  end: number;
  cameras: string[];
  event_ids?: string[];
};

export type MultiCamPlan = {
  version: 1;
  shots: MultiCamShot[];
  stream: "auto" | "main" | "sub";
  width: 1280 | 1920;
  fps: 15 | 25 | 30;
  audio_camera: string | null;
  clock_offsets: Record<string, number>;
};

export type MultiCamPreview = {
  plan: MultiCamPlan;
  duration: number;
  windows: {
    output_start: number;
    start: number;
    end: number;
    cameras: string[];
    coverage: Record<string, { start: number; end: number; stream: string }[]>;
  }[];
};

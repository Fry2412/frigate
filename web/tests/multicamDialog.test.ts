import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import MultiCamExportDialog from "@/components/overlay/MultiCamExportDialog";
import { MultiCamPlan } from "@/types/multicam";

vi.mock("axios", () => ({
  default: { post: vi.fn(), isAxiosError: () => false },
}));
vi.mock("swr", () => ({ default: () => ({ data: undefined }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/hooks/use-allowed-cameras", () => ({
  useAllowedCameras: () => ["front", "garden"],
}));
vi.mock("@/hooks/use-user-persistence", () => ({
  useUserPersistence: () => [undefined, vi.fn(), true],
}));
vi.mock("@/components/camera/FriendlyNameLabel", () => ({
  CameraNameLabel: ({ camera }: { camera: string }) =>
    React.createElement("span", null, camera),
}));
vi.mock("@/components/player/dynamic/DynamicVideoPlayer", () => ({
  default: () => null,
}));

const host = document.createElement("div");
document.body.append(host);
let root: ReturnType<typeof createRoot>;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  vi.clearAllMocks();
});

function button(text: string) {
  const result = [...document.querySelectorAll("button")].find(
    (node) => node.textContent === text,
  );
  if (!result) throw new Error("Missing button: " + text);
  return result;
}

describe("multicam export editing flow", () => {
  it("previews and exports exactly the camera cuts edited in the dialog", async () => {
    const requests: { endpoint: string; plan: MultiCamPlan }[] = [];
    vi.mocked(axios.post).mockImplementation(async (endpoint, body) => {
      requests.push({ endpoint, plan: body.plan });
      if (endpoint.endsWith("preview"))
        return {
          data: {
            plan: body.plan,
            duration: 60,
            windows: body.plan.shots.map(
              (shot: MultiCamPlan["shots"][0], index: number) => ({
                ...shot,
                output_start: index * 30,
                coverage: { front: [], garden: [] },
              }),
            ),
          },
        };
      return { data: { export_id: "multicam_test" } };
    });
    root = createRoot(host);
    await act(async () =>
      root.render(
        React.createElement(
          MemoryRouter,
          null,
          React.createElement(MultiCamExportDialog, {
            cameras: ["front", "garden"],
            currentTime: 100,
            onOpen: vi.fn(),
          }),
        ),
      ),
    );
    await act(async () => button("multicam.title").click());
    await act(async () => button("multicam.split").click());
    const checkboxes = document.querySelectorAll<HTMLInputElement>(
      'input[type="checkbox"]',
    );
    await act(async () => checkboxes[1].click());
    await act(async () => button("multicam.preview").click());
    expect(requests[0].plan.shots.map((shot) => shot.cameras)).toEqual([
      ["front"],
      ["front", "garden"],
    ]);
    await act(async () => button("multicam.export").click());
    expect(requests[1].plan).toEqual(requests[0].plan);
    expect(button("multicam.export").disabled).toBe(true);
  });
});

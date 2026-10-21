import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import MultiCamExportDialog from "@/components/overlay/MultiCamExportDialog";

const state = vi.hoisted(() => ({
  jobs: undefined as undefined | { id: string; status: string }[],
}));
vi.mock("axios", () => ({
  default: { post: vi.fn(), isAxiosError: () => false },
}));
vi.mock("swr", () => ({ default: () => ({ data: state.jobs }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/hooks/use-allowed-cameras", () => ({
  useAllowedCameras: () => ["front", "garden", "birdseye"],
}));
vi.mock("@/components/camera/FriendlyNameLabel", () => ({
  CameraNameLabel: ({ camera }: { camera: string }) =>
    React.createElement("span", null, camera),
}));

const host = document.createElement("div");
document.body.append(host);
let root: ReturnType<typeof createRoot>;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  state.jobs = undefined;
});
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

async function render() {
  root = createRoot(host);
  await act(async () =>
    root.render(
      React.createElement(
        MemoryRouter,
        null,
        React.createElement(MultiCamExportDialog, {
          cameras: ["front", "garden", "forbidden", "birdseye"],
          currentTime: 100,
          range: { after: 100, before: 220 },
          onOpen: vi.fn(),
        }),
      ),
    ),
  );
  await act(async () => button("multicam.title").click());
}

function queuedResults() {
  return ["front", "garden"].map((camera) => ({
    camera,
    export_id: camera,
    success: true,
  }));
}

function setDate(id: string, value: string) {
  const input = document.getElementById(id) as HTMLInputElement;
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("multicam ZIP export", () => {
  it("exports allowed cameras for the selected range without a composite plan", async () => {
    vi.mocked(axios.post).mockResolvedValue({
      data: { results: queuedResults() },
    });
    await render();
    expect(document.querySelectorAll('[role="checkbox"]')).toHaveLength(2);
    await act(async () => button("multicam.createZip").click());
    expect(axios.post).toHaveBeenCalledExactlyOnceWith("exports/batch", {
      new_case_name: "MultiCam",
      items: ["front", "garden"].map((camera) => ({
        camera,
        start_time: 100,
        end_time: 220,
        friendly_name: `MultiCam - ${camera}`,
      })),
    });
    expect(document.querySelector("a[download]")).toBeNull();
    expect(document.querySelector('[role="status"]')?.textContent).toContain(
      "multicam.preparing",
    );
  });

  it("requires a camera and an increasing time range", async () => {
    await render();
    for (const checkbox of document.querySelectorAll<HTMLButtonElement>(
      '[role="checkbox"]',
    )) {
      await act(async () => checkbox.click());
    }
    expect(button("multicam.createZip").disabled).toBe(true);
    await act(async () =>
      document.querySelector<HTMLButtonElement>('[role="checkbox"]')!.click(),
    );
    await act(async () => setDate("multicam-end", "1970-01-01T00:00:00"));
    expect(button("multicam.createZip").disabled).toBe(true);
    expect(document.querySelector('[role="alert"]')?.textContent).toBe(
      "multicam.invalidRange",
    );
    expect(axios.post).not.toHaveBeenCalled();
  });

  it("offers one ZIP containing every completed video", async () => {
    state.jobs = [
      { id: "front", status: "success" },
      { id: "garden", status: "success" },
    ];
    vi.mocked(axios.post).mockResolvedValue({
      data: { results: queuedResults() },
    });
    await render();
    await act(async () => button("multicam.createZip").click());
    const link = document.querySelector<HTMLAnchorElement>("a[download]")!;
    expect(link.textContent).toBe("multicam.downloadZip");
    expect(new URL(link.href).pathname).toBe("/api/exports/archive");
    expect(new URL(link.href).searchParams.getAll("ids")).toEqual([
      "front",
      "garden",
    ]);
  });

  it("explicitly labels partial downloads and excludes failed videos", async () => {
    state.jobs = [{ id: "front", status: "success" }];
    vi.mocked(axios.post).mockResolvedValue({
      data: {
        results: [
          queuedResults()[0],
          { camera: "garden", success: false, error: "No recordings found" },
        ],
      },
    });
    await render();
    await act(async () => button("multicam.createZip").click());
    const link = document.querySelector<HTMLAnchorElement>("a[download]")!;
    expect(link.textContent).toBe("multicam.downloadPartial");
    expect(new URL(link.href).searchParams.getAll("ids")).toEqual(["front"]);
    expect(document.querySelector('[role="status"]')?.textContent).toContain(
      "No recordings found",
    );
    expect(document.querySelector('[role="status"]')?.textContent).toContain(
      "multicam.partial",
    );
  });

  it("allows retrying after a rejected batch", async () => {
    vi.mocked(axios.post).mockRejectedValue(new Error("Queue full"));
    await render();
    await act(async () => button("multicam.createZip").click());
    expect(button("multicam.createZip").disabled).toBe(false);
    expect(document.querySelector("a[download]")).toBeNull();
  });
});

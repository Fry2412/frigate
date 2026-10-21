import { beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import { fetchMultiCamExportJobs } from "@/utils/multicamExport";

vi.mock("axios", () => ({
  default: {
    get: vi.fn(),
    isAxiosError: (error: { response?: unknown }) => Boolean(error.response),
  },
}));
const gone = { response: { status: 404 } };
beforeEach(() => {
  vi.resetAllMocks();
});

describe("multicam export status recovery", () => {
  it("uses live job states while exports run", async () => {
    vi.mocked(axios.get).mockResolvedValue({
      data: { id: "front", status: "running" },
    });
    expect(await fetchMultiCamExportJobs(["front"])).toEqual([
      { id: "front", status: "running" },
    ]);
    expect(axios.get).toHaveBeenCalledTimes(1);
  });
  it("recovers finished exports after job cleanup", async () => {
    vi.mocked(axios.get)
      .mockRejectedValueOnce(gone)
      .mockResolvedValueOnce({
        data: [{ id: "front", camera: "front", in_progress: false }],
      });
    expect((await fetchMultiCamExportJobs(["front"]))[0].status).toBe(
      "success",
    );
    expect(axios.get).toHaveBeenLastCalledWith("exports");
  });
  it("does not poll orphaned or missing exports forever", async () => {
    vi.mocked(axios.get)
      .mockRejectedValueOnce(gone)
      .mockRejectedValueOnce(gone)
      .mockResolvedValueOnce({ data: [{ id: "front", in_progress: true }] });
    expect(
      (await fetchMultiCamExportJobs(["front", "garden"])).map(
        (job) => job.status,
      ),
    ).toEqual(["failed", "failed"]);
  });
  it("keeps network and authorization errors visible for retries", async () => {
    const error = { response: { status: 403 } };
    vi.mocked(axios.get).mockRejectedValue(error);
    await expect(fetchMultiCamExportJobs(["front"])).rejects.toEqual(error);
  });
});

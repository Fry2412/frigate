import axios from "axios";
import { Export, ExportJob } from "@/types/export";

// Finished jobs leave the in-memory queue after five seconds. Persisted exports
// remain the source of truth when returning to a closed dialog or background tab.
export async function fetchMultiCamExportJobs(
  ids: string[],
): Promise<ExportJob[]> {
  const results = await Promise.all(
    ids.map(async (id) => {
      try {
        return (await axios.get<ExportJob>(`jobs/export/${id}`)).data;
      } catch (error) {
        if (!axios.isAxiosError(error) || error.response?.status !== 404)
          throw error;
        return undefined;
      }
    }),
  );
  const exports = results.some((job) => !job)
    ? (await axios.get<Export[]>("exports")).data
    : [];
  return results.map((job, index) => {
    if (job) return job;
    const saved = exports.find((item) => item.id === ids[index]);
    return {
      id: ids[index],
      camera: saved?.camera ?? "",
      job_type: "export",
      request_start_time: 0,
      request_end_time: 0,
      status: saved && !saved.in_progress ? "success" : "failed",
    };
  });
}

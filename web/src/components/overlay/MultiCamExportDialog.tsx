import { useState } from "react";
import axios from "axios";
import useSWR from "swr";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { LuArchive, LuCheck, LuDownload, LuLoaderCircle } from "react-icons/lu";
import { Link } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAllowedCameras } from "@/hooks/use-allowed-cameras";
import { CameraNameLabel } from "@/components/camera/FriendlyNameLabel";
import { TimeRange } from "@/types/timeline";
import {
  BatchExportResponse,
  BatchExportResult,
  ExportJob,
  MAX_BATCH_EXPORT_ITEMS,
} from "@/types/export";
import { baseUrl } from "@/api/baseUrl";
import { fetchMultiCamExportJobs } from "@/utils/multicamExport";

function dateValue(time: number) {
  const date = new Date(time * 1000);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 19);
}

const pending = (job: ExportJob) => ["queued", "running"].includes(job.status);

export default function MultiCamExportDialog({
  cameras,
  currentTime,
  range,
  onOpen,
}: {
  cameras: string[];
  currentTime: number;
  range?: TimeRange;
  onOpen: () => void;
}) {
  const { t } = useTranslation(["components/dialog", "common"]);
  const allowed = useAllowedCameras().filter((camera) => camera !== "birdseye");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("MultiCam");
  const [selected, setSelected] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<BatchExportResult[]>();
  const ids =
    results?.flatMap((result) =>
      result.success && result.export_id ? [result.export_id] : [],
    ) ?? [];
  const { data: jobs, error: statusError } = useSWR<ExportJob[]>(
    open && ids.length ? ["multicam-zip-jobs", ids] : null,
    ([, exportIds]: [string, string[]]) => fetchMultiCamExportJobs(exportIds),
    {
      refreshInterval: (data) =>
        data && data.every((job) => !pending(job)) ? 0 : 1500,
    },
  );
  const readyIds =
    jobs?.filter((job) => job.status === "success").map((job) => job.id) ?? [];
  const active = ids.length > 0 && (!jobs || jobs.some(pending));
  const after = new Date(start).getTime() / 1000;
  const before = new Date(end).getTime() / 1000;
  const validRange =
    Number.isFinite(after) && Number.isFinite(before) && before > after;
  const invalidRange = Boolean(start && end && !validRange);
  const canStart =
    !busy && !results && name.trim() && selected.length > 0 && validRange;
  const complete = Boolean(results && !active);
  const allReady = complete && readyIds.length === results?.length;
  const archiveUrl = new URL("api/exports/archive", baseUrl);
  readyIds.forEach((id) => archiveUrl.searchParams.append("ids", id));

  async function submit() {
    if (!canStart) return;
    setBusy(true);
    try {
      const response = await axios.post<BatchExportResponse>("exports/batch", {
        new_case_name: name.trim(),
        items: selected.map((camera) => ({
          camera,
          start_time: after,
          end_time: before,
          friendly_name: `${name.trim()} - ${camera}`,
        })),
      });
      setResults(response.data.results);
    } catch (error) {
      toast.error(
        axios.isAxiosError(error)
          ? String(
              error.response?.data?.message ??
                error.response?.data?.detail ??
                error.message,
            )
          : String(error),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (busy) return;
        setOpen(value);
        if (value) {
          onOpen();
          if (!results) {
            setSelected(
              [
                ...new Set(
                  cameras.filter((camera) => allowed.includes(camera)),
                ),
              ].slice(0, MAX_BATCH_EXPORT_ITEMS),
            );
            setStart(dateValue(Math.floor(range?.after ?? currentTime)));
            setEnd(dateValue(Math.floor(range?.before ?? currentTime + 60)));
          }
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" title={t("multicam.title")}>
          <LuArchive className="size-4" />
          <span className="ml-2 hidden lg:inline">{t("multicam.title")}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("multicam.title")}</DialogTitle>
          <DialogDescription>{t("multicam.zipDescription")}</DialogDescription>
        </DialogHeader>
        <fieldset
          disabled={busy || Boolean(results)}
          className="min-w-0 space-y-5"
        >
          <div className="space-y-2">
            <Label htmlFor="multicam-name">{t("multicam.name")}</Label>
            <Input
              id="multicam-name"
              value={name}
              maxLength={100}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="min-w-0 space-y-2">
              <Label htmlFor="multicam-start">{t("multicam.start")}</Label>
              <Input
                className="min-w-0"
                id="multicam-start"
                type="datetime-local"
                step={1}
                value={start}
                onChange={(event) => setStart(event.target.value)}
                aria-invalid={invalidRange}
              />
            </div>
            <div className="min-w-0 space-y-2">
              <Label htmlFor="multicam-end">{t("multicam.end")}</Label>
              <Input
                className="min-w-0"
                id="multicam-end"
                type="datetime-local"
                step={1}
                value={end}
                onChange={(event) => setEnd(event.target.value)}
                aria-invalid={invalidRange}
              />
            </div>
          </div>
          {invalidRange && (
            <p role="alert" className="text-sm text-danger">
              {t("multicam.invalidRange")}
            </p>
          )}
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2 text-sm">
              <span id="multicam-cameras">{t("multicam.cameras")}</span>
              <span className="text-muted-foreground">
                {t("multicam.selectedCount", { count: selected.length })}
              </span>
            </div>
            <div
              role="group"
              aria-labelledby="multicam-cameras"
              className="grid max-h-48 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2"
            >
              {allowed.map((camera) => (
                <label
                  key={camera}
                  className="flex cursor-pointer items-center gap-3 rounded-lg border border-input p-3 text-sm has-[[data-state=checked]]:border-selected has-[[data-state=checked]]:bg-selected/10"
                >
                  <Checkbox
                    checked={selected.includes(camera)}
                    disabled={
                      !selected.includes(camera) &&
                      selected.length >= MAX_BATCH_EXPORT_ITEMS
                    }
                    onCheckedChange={(checked) =>
                      setSelected((value) =>
                        checked === true
                          ? [...value, camera]
                          : value.filter((item) => item !== camera),
                      )
                    }
                  />
                  <CameraNameLabel camera={camera} />
                </label>
              ))}
            </div>
            {!selected.length && (
              <p className="text-sm text-muted-foreground">
                {t("multicam.selectCameras")}
              </p>
            )}
          </div>
        </fieldset>
        {!results && (
          <p className="rounded-lg bg-secondary p-3 text-sm text-muted-foreground">
            {t("multicam.zipHint")}
          </p>
        )}
        {results && (
          <div
            className="space-y-3 rounded-lg border border-input p-3"
            role="status"
            aria-live="polite"
          >
            <p className="flex items-center gap-2 text-sm font-medium">
              {active ? (
                <LuLoaderCircle className="size-4 animate-spin" />
              ) : allReady ? (
                <LuCheck className="size-4 text-success" />
              ) : (
                <LuArchive className="size-4" />
              )}
              {t(
                active
                  ? "multicam.preparing"
                  : allReady
                    ? "multicam.ready"
                    : "multicam.partial",
              )}
            </p>
            {results.map((result) => {
              const job = jobs?.find((item) => item.id === result.export_id);
              const failed =
                !result.success ||
                job?.status === "failed" ||
                job?.status === "cancelled";
              return (
                <div key={result.camera} className="space-y-1 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <CameraNameLabel camera={result.camera} />
                    <span
                      className={
                        failed ? "text-danger" : "text-muted-foreground"
                      }
                    >
                      {t(
                        failed
                          ? "multicam.failed"
                          : job?.status === "success"
                            ? "multicam.videoReady"
                            : "multicam.preparing",
                      )}
                    </span>
                  </div>
                  {(result.error || job?.error_message) && (
                    <p className="text-xs text-danger">
                      {result.error || job?.error_message}
                    </p>
                  )}
                </div>
              );
            })}
            {statusError && (
              <p className="text-sm text-danger">{t("multicam.statusError")}</p>
            )}
          </div>
        )}
        <DialogFooter className="gap-2 sm:flex-wrap">
          {results && (
            <Button variant="outline" asChild>
              <Link to="/export">{t("multicam.openExports")}</Link>
            </Button>
          )}
          {complete && (
            <Button variant="outline" onClick={() => setResults(undefined)}>
              {t("multicam.newExport")}
            </Button>
          )}
          {!results ? (
            <Button variant="select" disabled={!canStart} onClick={submit}>
              {busy && <LuLoaderCircle className="mr-2 size-4 animate-spin" />}
              {t("multicam.createZip")}
            </Button>
          ) : complete && readyIds.length > 0 ? (
            <Button variant="select" asChild>
              <a href={archiveUrl.toString()} download>
                <LuDownload className="mr-2 size-4" />
                {t(
                  allReady
                    ? "multicam.downloadZip"
                    : "multicam.downloadPartial",
                  { count: readyIds.length },
                )}
              </a>
            </Button>
          ) : (
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("multicam.close")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

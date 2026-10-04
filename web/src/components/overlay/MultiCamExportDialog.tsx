import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import useSWR from "swr";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { LuClapperboard } from "react-icons/lu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAllowedCameras } from "@/hooks/use-allowed-cameras";
import { useUserPersistence } from "@/hooks/use-user-persistence";
import { MultiCamPlan, MultiCamPreview, MultiCamShot } from "@/types/multicam";
import { TimeRange } from "@/types/timeline";
import { ExportJob } from "@/types/export";
import {
  isMultiCamPlan,
  locatePlanTime,
  splitPlanShot,
} from "@/utils/multicamPlan";
import DynamicVideoPlayer from "@/components/player/dynamic/DynamicVideoPlayer";
import { DynamicVideoController } from "@/components/player/dynamic/DynamicVideoController";
import { DetailStreamProvider } from "@/context/detail-stream-context";
import { VideoResolutionType } from "@/types/live";
import { CameraNameLabel } from "@/components/camera/FriendlyNameLabel";
import { Link } from "react-router-dom";

function dateValue(time: number) {
  const date = new Date(time * 1000);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 19);
}

function PreviewCamera({
  camera,
  shot,
  timestamp,
  playing,
  plan,
  covered,
  sourceStream,
}: {
  camera: string;
  shot: MultiCamShot;
  timestamp: number;
  playing: boolean;
  plan: MultiCamPlan;
  covered: boolean;
  sourceStream?: "main" | "sub";
}) {
  const { t } = useTranslation("components/dialog");
  const [controller, setController] = useState<DynamicVideoController>();
  const [, setResolution] = useState<VideoResolutionType>({
    width: 1280,
    height: 720,
  });
  const offset = plan.clock_offsets[camera] ?? 0;
  const ready = useCallback(
    (value: DynamicVideoController) => setController(value),
    [],
  );
  useEffect(() => {
    const synchronize = () =>
      controller?.synchronizeToTimestamp(timestamp + offset, playing, 0.25);
    synchronize();
    const timer = window.setInterval(synchronize, 250);
    return () => window.clearInterval(timer);
  }, [controller, timestamp, offset, playing]);
  return (
    <div className="relative flex min-h-0 items-center justify-center overflow-hidden bg-black text-white">
      <span className="absolute left-2 top-2 z-10 bg-black/60 px-2 text-xs">
        <CameraNameLabel camera={camera} />
      </span>
      {covered ? (
        <DynamicVideoPlayer
          camera={camera}
          timeRange={{
            after: Math.floor(shot.start + offset),
            before: Math.ceil(shot.end + offset),
          }}
          cameraPreviews={[]}
          startTimestamp={shot.start + offset}
          shouldPlay={playing}
          isScrubbing={false}
          hotKeys={false}
          supportsFullscreen={false}
          fullscreen={false}
          controlsActive={false}
          onControllerReady={ready}
          setFullResolution={setResolution}
          toggleFullscreen={() => {}}
          quality={sourceStream ?? plan.stream}
        />
      ) : (
        <span className="p-4 text-center text-sm">
          {t("multicam.noRecording")}
        </span>
      )}
    </div>
  );
}

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
  const { t } = useTranslation("components/dialog");
  const allowed = useAllowedCameras().filter((camera) => camera !== "birdseye");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("MultiCam");
  const [plan, setPlan] = useState<MultiCamPlan>();
  const [draft, setDraft, draftLoaded] = useUserPersistence<MultiCamPlan>(
    "multicam-export-draft",
  );
  const [preview, setPreview] = useState<MultiCamPreview>();
  const [outputTime, setOutputTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string>();
  const fileInput = useRef<HTMLInputElement>(null);
  const { data: job } = useSWR<ExportJob>(
    jobId && open ? `jobs/export/${jobId}` : null,
    { refreshInterval: 1500 },
  );
  const active =
    Boolean(jobId && !job) ||
    job?.status === "queued" ||
    job?.status === "running";
  const position = plan ? locatePlanTime(plan.shots, outputTime) : undefined;
  const previewWindow = position ? preview?.windows[position.index] : undefined;

  const updatePlan = (value: MultiCamPlan) => {
    setPlan(value);
    setPreview(undefined);
    setPlaying(false);
    setOutputTime(0);
  };

  useEffect(() => {
    if (!playing || !preview) return;
    let last = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const delta = (now - last) / 1000;
      last = now;
      setOutputTime((value) => {
        const next = value + delta;
        if (next >= preview.duration) setPlaying(false);
        return Math.min(next, preview.duration);
      });
    }, 250);
    return () => window.clearInterval(timer);
  }, [playing, preview]);

  const validate = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      const response = await axios.post<MultiCamPreview>(
        "exports/multicam/preview",
        { name, plan },
      );
      setPreview(response.data);
      setOutputTime(0);
      return response.data;
    } catch (error) {
      toast.error(
        axios.isAxiosError(error)
          ? String(error.response?.data?.detail ?? error.message)
          : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    if (!plan) return;
    setBusy(true);
    setPlaying(false);
    try {
      const response = await axios.post<{ export_id: string }>(
        "exports/multicam",
        { name, plan },
      );
      setJobId(response.data.export_id);
      setDraft(plan);
      toast.success(t("multicam.queued"));
    } catch (error) {
      toast.error(
        axios.isAxiosError(error)
          ? String(error.response?.data?.detail ?? error.message)
          : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  const setShot = (index: number, shot: MultiCamShot) =>
    plan &&
    updatePlan({
      ...plan,
      shots: plan.shots.map((item, i) => (i === index ? shot : item)),
    });
  const selected = plan
    ? [
        ...new Set(
          plan.shots
            .flatMap((shot) => shot.cameras)
            .concat(plan.audio_camera ? [plan.audio_camera] : []),
        ),
      ]
    : [];

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        setPlaying(false);
        if (value) {
          onOpen();
          if (!plan)
            updatePlan({
              version: 1,
              shots: [
                {
                  start: Math.floor(range?.after ?? currentTime),
                  end: Math.floor(range?.before ?? currentTime + 60),
                  cameras: cameras
                    .filter((camera) => allowed.includes(camera))
                    .slice(0, 4),
                },
              ],
              stream: "auto",
              width: 1280,
              fps: 15,
              audio_camera: null,
              clock_offsets: {},
            });
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" title={t("multicam.title")}>
          <LuClapperboard className="size-4" />
          <span className="ml-2 hidden lg:inline">{t("multicam.title")}</span>
        </Button>
      </DialogTrigger>
      <DialogContent
        className="max-h-[95dvh] max-w-5xl overflow-y-auto"
        aria-describedby="multicam-description"
      >
        <DialogHeader>
          <DialogTitle>{t("multicam.title")}</DialogTitle>
        </DialogHeader>
        <p id="multicam-description" className="text-sm text-muted-foreground">
          {t("multicam.description")}
        </p>
        {plan && (
          <>
            <Label htmlFor="multicam-name">{t("multicam.name")}</Label>
            <Input
              id="multicam-name"
              value={name}
              maxLength={100}
              onChange={(event) => setName(event.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={!draftLoaded}
                onClick={() => {
                  setDraft(plan);
                  toast.success(t("multicam.saved"));
                }}
              >
                {t("multicam.saveDraft")}
              </Button>
              <Button
                variant="outline"
                disabled={!draft || active}
                onClick={() => draft && updatePlan(draft)}
              >
                {t("multicam.restoreDraft")}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  const url = URL.createObjectURL(
                    new Blob([JSON.stringify(plan, null, 2)], {
                      type: "application/json",
                    }),
                  );
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = "multicam-plan.json";
                  link.click();
                  URL.revokeObjectURL(url);
                }}
              >
                {t("multicam.downloadPlan")}
              </Button>
              <Button
                variant="outline"
                disabled={active}
                onClick={() => fileInput.current?.click()}
              >
                {t("multicam.openPlan")}
              </Button>
              <input
                className="hidden"
                ref={fileInput}
                type="file"
                accept="application/json,.json"
                onChange={async (event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  try {
                    if (file.size > 100000)
                      throw new Error(t("multicam.invalidPlan"));
                    const value: unknown = JSON.parse(await file.text());
                    if (!isMultiCamPlan(value))
                      throw new Error(t("multicam.invalidPlan"));
                    updatePlan(value);
                  } catch {
                    toast.error(t("multicam.invalidPlan"));
                  }
                  event.target.value = "";
                }}
              />
            </div>
            <fieldset disabled={busy || active} className="space-y-3">
              {plan.shots.map((shot, index) => (
                <div className="space-y-2 rounded border p-3" key={index}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span>{index + 1}.</span>
                    <Input
                      aria-label={t("multicam.start")}
                      className="w-auto"
                      type="datetime-local"
                      step={1}
                      value={dateValue(shot.start)}
                      onChange={(event) => {
                        const value =
                          new Date(event.target.value).getTime() / 1000;
                        if (Number.isFinite(value))
                          setShot(index, { ...shot, start: value });
                      }}
                    />
                    <Input
                      aria-label={t("multicam.end")}
                      className="w-auto"
                      type="datetime-local"
                      step={1}
                      value={dateValue(shot.end)}
                      onChange={(event) => {
                        const value =
                          new Date(event.target.value).getTime() / 1000;
                        if (Number.isFinite(value))
                          setShot(index, { ...shot, end: value });
                      }}
                    />
                    <Button
                      variant="outline"
                      onClick={() =>
                        updatePlan(
                          splitPlanShot(
                            plan,
                            index,
                            Math.floor((shot.start + shot.end) / 2),
                          ),
                        )
                      }
                    >
                      {t("multicam.split")}
                    </Button>
                    <Button
                      variant="outline"
                      disabled={plan.shots.length < 2}
                      onClick={() =>
                        updatePlan({
                          ...plan,
                          shots: plan.shots.filter((_, i) => i !== index),
                        })
                      }
                    >
                      {t("multicam.remove")}
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    {allowed.map((camera) => (
                      <label
                        className="flex items-center gap-2 text-sm"
                        key={camera}
                      >
                        <input
                          type="checkbox"
                          checked={shot.cameras.includes(camera)}
                          disabled={
                            !shot.cameras.includes(camera) &&
                            (shot.cameras.length >= 4 ||
                              (!selected.includes(camera) &&
                                selected.length >= 4))
                          }
                          onChange={(event) =>
                            setShot(index, {
                              ...shot,
                              cameras: event.target.checked
                                ? [...shot.cameras, camera]
                                : shot.cameras.filter(
                                    (item) => item !== camera,
                                  ),
                            })
                          }
                        />
                        <CameraNameLabel camera={camera} />
                      </label>
                    ))}
                  </div>
                </div>
              ))}
              <div className="flex flex-wrap gap-4">
                <label>
                  {t("multicam.quality")}{" "}
                  <select
                    className="rounded bg-secondary p-2"
                    value={plan.stream}
                    onChange={(event) =>
                      updatePlan({
                        ...plan,
                        stream: event.target.value as MultiCamPlan["stream"],
                      })
                    }
                  >
                    <option value="auto">Auto</option>
                    <option value="main">Main</option>
                    <option value="sub">Sub</option>
                  </select>
                </label>
                <label>
                  {t("multicam.resolution")}{" "}
                  <select
                    className="rounded bg-secondary p-2"
                    value={plan.width}
                    onChange={(event) =>
                      updatePlan({
                        ...plan,
                        width: Number(
                          event.target.value,
                        ) as MultiCamPlan["width"],
                      })
                    }
                  >
                    <option value={1280}>720p</option>
                    <option value={1920}>1080p</option>
                  </select>
                </label>
                <label>
                  {t("multicam.audio")}{" "}
                  <select
                    className="rounded bg-secondary p-2"
                    value={plan.audio_camera ?? ""}
                    onChange={(event) =>
                      updatePlan({
                        ...plan,
                        audio_camera: event.target.value || null,
                      })
                    }
                  >
                    <option value="">{t("multicam.silent")}</option>
                    {allowed
                      .filter(
                        (camera) =>
                          selected.includes(camera) || selected.length < 4,
                      )
                      .map((camera) => (
                        <option key={camera} value={camera}>
                          {camera}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              <details>
                <summary>{t("multicam.offsets")}</summary>
                <p className="text-sm text-muted-foreground">
                  {t("multicam.offsetDescription")}
                </p>
                {selected.map((camera) => (
                  <label className="flex items-center gap-2" key={camera}>
                    <CameraNameLabel camera={camera} />
                    <Input
                      className="w-24"
                      type="number"
                      min={-30}
                      max={30}
                      step={0.1}
                      value={plan.clock_offsets[camera] ?? 0}
                      onChange={(event) =>
                        updatePlan({
                          ...plan,
                          clock_offsets: {
                            ...plan.clock_offsets,
                            [camera]: Number(event.target.value),
                          },
                        })
                      }
                    />
                    s
                  </label>
                ))}
              </details>
            </fieldset>
            <Button disabled={busy || active} onClick={validate}>
              {t("multicam.preview")}
            </Button>
            {preview && position && previewWindow && (
              <div className="space-y-2">
                <p className="text-sm">
                  {new Date(position.timestamp * 1000).toLocaleString()} ·{" "}
                  {t("multicam.previewSilent")}
                </p>
                <DetailStreamProvider
                  isDetailMode={false}
                  camera=""
                  currentTime={position.timestamp}
                >
                  <div
                    className={`grid aspect-video max-h-[45vh] w-full bg-black ${previewWindow.cameras.length > 1 ? "grid-cols-2" : "grid-cols-1"} ${previewWindow.cameras.length > 2 ? "grid-rows-2" : "grid-rows-1"}`}
                  >
                    {previewWindow.cameras.length === 0 ? (
                      <p className="m-auto text-white">
                        {t("multicam.noRecording")}
                      </p>
                    ) : (
                      previewWindow.cameras.map((camera) => (
                        <PreviewCamera
                          key={`${position.index}-${camera}`}
                          camera={camera}
                          shot={plan.shots[position.index]}
                          timestamp={position.timestamp}
                          playing={playing}
                          plan={plan}
                          covered={
                            previewWindow.coverage[camera]?.some(
                              (span) =>
                                position.timestamp >= span.start &&
                                position.timestamp < span.end,
                            ) ?? false
                          }
                          sourceStream={
                            previewWindow.coverage[camera]?.find(
                              (span) =>
                                position.timestamp >= span.start &&
                                position.timestamp < span.end,
                            )?.stream as "main" | "sub" | undefined
                          }
                        />
                      ))
                    )}
                  </div>
                </DetailStreamProvider>
                <Input
                  type="range"
                  aria-label={t("multicam.playhead")}
                  min={0}
                  max={preview.duration}
                  step={0.1}
                  value={outputTime}
                  onChange={(event) => {
                    setPlaying(false);
                    setOutputTime(Number(event.target.value));
                  }}
                />
                <Button
                  variant="outline"
                  onClick={() => {
                    if (outputTime >= preview.duration) setOutputTime(0);
                    setPlaying((value) => !value);
                  }}
                >
                  {playing ? t("multicam.pause") : t("multicam.play")}
                </Button>
                <Button
                  variant="outline"
                  disabled={active}
                  onClick={() =>
                    updatePlan(
                      splitPlanShot(
                        plan,
                        position.index,
                        Math.floor(position.timestamp),
                      ),
                    )
                  }
                >
                  {t("multicam.cutHere")}
                </Button>
              </div>
            )}
            <Button
              disabled={busy || active || !preview || !name.trim()}
              onClick={start}
            >
              {t("multicam.export")}
            </Button>
            {job && (
              <div role="status">
                <p>
                  {job.status} · {Math.round(job.progress_percent ?? 0)}%
                </p>
                {job.error_message && (
                  <p className="text-danger">{job.error_message}</p>
                )}
                {active && (
                  <Button
                    variant="outline"
                    onClick={() =>
                      axios.post(`exports/multicam/${jobId}/cancel`)
                    }
                  >
                    {t("multicam.cancel")}
                  </Button>
                )}
              </div>
            )}
            {jobId && !active && (
              <Link className="underline" to="/exports">
                {t("multicam.openExports")}
              </Link>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

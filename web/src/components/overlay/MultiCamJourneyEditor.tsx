import { useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MultiCamPlan } from "@/types/multicam";
import { baseUrl } from "@/api/baseUrl";
import { CameraNameLabel } from "@/components/camera/FriendlyNameLabel";

type Observation = {
  id: string;
  camera: string;
  label: string;
  start_time: number;
  end_time: number | null;
  zones?: string[];
};

export default function MultiCamJourneyEditor({
  plan,
  cameras,
  onPlan,
  disabled,
}: {
  plan: MultiCamPlan;
  cameras: string[];
  onPlan: (value: MultiCamPlan) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation("components/dialog");
  const [events, setEvents] = useState<Observation[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [seed, setSeed] = useState<string>();
  const [mode, setMode] = useState("follow");
  const [busy, setBusy] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const [minShot, setMinShot] = useState(3);
  const [padding, setPadding] = useState(2);
  const [transitions, setTransitions] = useState<Record<string, string[]>>({});
  const body = (seedId?: string) => ({
    cameras,
    after: plan.shots[0].start,
    before: plan.shots[plan.shots.length - 1].end,
    seed_id: seedId ?? null,
    selected_event_ids: selected,
    mode,
    min_shot: minShot,
    pre_capture: padding,
    post_capture: padding,
    transitions: Object.fromEntries(
      Object.entries(transitions)
        .filter(([camera]) => cameras.includes(camera))
        .map(([camera, targets]) => [
          camera,
          targets.filter((target) => cameras.includes(target)),
        ]),
    ),
    clock_offsets: Object.fromEntries(
      Object.entries(plan.clock_offsets).filter(([camera]) =>
        cameras.includes(camera),
      ),
    ),
  });

  const search = async (seedId?: string) => {
    setBusy(true);
    try {
      const response = await axios.post<{
        events: Observation[];
        truncated: boolean;
      }>("exports/multicam/journey", body(seedId));
      setEvents(response.data.events);
      setTruncated(response.data.truncated);
      setSeed(seedId);
      setSelected(seedId ? [seedId] : []);
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

  const build = async () => {
    setBusy(true);
    try {
      const response = await axios.post<{ plan: MultiCamPlan }>(
        "exports/multicam/journey/plan",
        body(seed),
      );
      onPlan({
        ...response.data.plan,
        stream: plan.stream,
        width: plan.width,
        fps: plan.fps,
        audio_camera: plan.audio_camera,
        clock_offsets: Object.fromEntries(
          Object.entries(plan.clock_offsets).filter(
            ([camera]) =>
              response.data.plan.shots.some((shot) =>
                shot.cameras.includes(camera),
              ) || camera === plan.audio_camera,
          ),
        ),
      });
      toast.success(t("multicam.journeyCreated"));
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

  return (
    <details className="rounded border p-3">
      <summary>{t("multicam.journeyTitle")}</summary>
      <fieldset disabled={busy || disabled} className="mt-3 space-y-3">
        <p className="text-sm text-muted-foreground">
          {t("multicam.journeyDescription")}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <label>
            {t("multicam.journeyMode")}{" "}
            <select
              className="rounded bg-secondary p-2"
              value={mode}
              onChange={(event) => setMode(event.target.value)}
            >
              <option value="follow">{t("multicam.follow")}</option>
              <option value="grid">{t("multicam.dynamicGrid")}</option>
            </select>
          </label>
          <label className="flex items-center gap-2">
            {t("multicam.minShot")}
            <Input
              className="w-20"
              type="number"
              min={1}
              max={10}
              value={minShot}
              onChange={(event) => setMinShot(Number(event.target.value))}
            />
            s
          </label>
          <label className="flex items-center gap-2">
            {t("multicam.padding")}
            <Input
              className="w-20"
              type="number"
              min={0}
              max={10}
              value={padding}
              onChange={(event) => setPadding(Number(event.target.value))}
            />
            s
          </label>
        </div>
        <details>
          <summary>{t("multicam.transitions")}</summary>
          <p className="text-sm text-muted-foreground">
            {t("multicam.transitionDescription")}
          </p>
          {cameras.map((camera) => (
            <div className="flex flex-wrap items-center gap-3" key={camera}>
              <CameraNameLabel camera={camera} /> →{" "}
              {cameras
                .filter((target) => target !== camera)
                .map((target) => (
                  <label key={target} className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={
                        !transitions[camera] ||
                        transitions[camera].includes(target)
                      }
                      onChange={(event) =>
                        setTransitions({
                          ...transitions,
                          [camera]: event.target.checked
                            ? [
                                ...(transitions[camera] ??
                                  cameras.filter((cam) => cam !== camera)),
                                target,
                              ]
                            : (transitions[camera] ?? cameras).filter(
                                (cam) => cam !== target,
                              ),
                        })
                      }
                    />
                    <CameraNameLabel camera={target} />
                  </label>
                ))}
            </div>
          ))}
        </details>
        <Button
          variant="outline"
          disabled={!cameras.length}
          onClick={() => search()}
        >
          {t("multicam.findObservations")}
        </Button>
        {truncated && (
          <p className="text-sm text-danger">{t("multicam.tooManyEvents")}</p>
        )}
        {events.length > 0 && (
          <p className="text-sm">
            {seed ? t("multicam.confirmIdentity") : t("multicam.chooseSeed")}
          </p>
        )}
        <div className="grid max-h-80 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
          {events.map((event) => (
            <div
              className="flex items-center gap-3 rounded border p-2"
              key={event.id}
            >
              <img
                className="h-16 w-24 object-contain"
                alt={event.label}
                src={`${baseUrl}api/events/${event.id}/thumbnail.jpg`}
                loading="lazy"
              />
              <div className="min-w-0 flex-1 text-sm">
                <CameraNameLabel camera={event.camera} />
                <p>
                  {event.label} ·{" "}
                  {new Date(event.start_time * 1000).toLocaleTimeString()}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {event.zones?.join(", ")}
                </p>
                {!seed ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => search(event.id)}
                  >
                    {t("multicam.selectTarget")}
                  </Button>
                ) : (
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selected.includes(event.id)}
                      disabled={
                        seed === event.id ||
                        (!selected.includes(event.id) && selected.length >= 64)
                      }
                      onChange={(change) =>
                        setSelected(
                          change.target.checked
                            ? [...selected, event.id]
                            : selected.filter((id) => id !== event.id),
                        )
                      }
                    />
                    {seed === event.id
                      ? t("multicam.target")
                      : t("multicam.sameTarget")}
                  </label>
                )}
              </div>
            </div>
          ))}
        </div>
        <Button disabled={!seed || selected.length === 0} onClick={build}>
          {t("multicam.buildJourney")}
        </Button>
      </fieldset>
    </details>
  );
}

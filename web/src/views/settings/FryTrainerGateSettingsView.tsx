import { useState } from "react";
import useSWR, { mutate } from "swr";
import axios from "axios";
import { toast } from "sonner";
import Heading from "@/components/ui/heading";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SettingsGroupCard } from "@/components/card/SettingsGroupCard";
import ActivityIndicator from "@/components/indicators/activity-indicator";
import { LuCopy, LuRefreshCw, LuShieldAlert } from "react-icons/lu";

type Runner = {
  id: string;
  name: string;
  status: string;
  enabled: boolean;
  last_seen_at?: string;
  runner_version: string;
  platform: string;
  current_job_id?: string;
  capabilities: {
    cuda?: boolean;
    gpu_name?: string;
    vram_mb?: number;
    cpu_cores?: number;
  };
};

type Dataset = {
  id: string;
  name: string;
  image_count: number;
  size: number;
};

type Job = {
  id: string;
  name: string;
  dataset_id: string;
  assigned_runner_id?: string;
  state: string;
  backend: string;
  progress: number;
  status_message?: string;
  failure_reason?: string;
};

const formatBytes = (value: number) => {
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
};

const statusVariant = (status: string) => {
  if (["ONLINE", "SUCCEEDED"].includes(status)) return "secondary" as const;
  if (["FAILED", "RUNNER_LOST", "DISABLED"].includes(status)) {
    return "destructive" as const;
  }
  return "outline" as const;
};

export default function FryTrainerGateSettingsView() {
  const {
    data: status,
    error: statusError,
    isLoading,
  } = useSWR<{
    available: boolean;
    runner_count: number;
    job_counts: Record<string, number>;
  }>("frytrainergate/status", { refreshInterval: 10000 });
  const { data: runnersData } = useSWR<{ runners: Runner[] }>(
    "frytrainergate/runners",
    { refreshInterval: 10000 },
  );
  const { data: datasetsData } = useSWR<{ datasets: Dataset[] }>(
    "frytrainergate/datasets",
  );
  const { data: jobsData } = useSWR<{ jobs: Job[] }>("frytrainergate/jobs", {
    refreshInterval: 5000,
  });
  const { data: modelsData } = useSWR<{
    models: Array<Record<string, unknown>>;
  }>("frytrainergate/models");

  const [runnerName, setRunnerName] = useState("");
  const [pairingToken, setPairingToken] = useState<string | null>(null);
  const [rotatedSecret, setRotatedSecret] = useState<string | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const [jobName, setJobName] = useState("");
  const [selectedDataset, setSelectedDataset] = useState("");
  const [selectedRunner, setSelectedRunner] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    await Promise.all([
      mutate("frytrainergate/status"),
      mutate("frytrainergate/runners"),
      mutate("frytrainergate/datasets"),
      mutate("frytrainergate/jobs"),
      mutate("frytrainergate/models"),
    ]);
  };

  const action = async (work: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try {
      await work();
      toast.success(success);
      await refresh();
    } catch (error) {
      const message = axios.isAxiosError(error)
        ? error.response?.data?.detail
        : undefined;
      toast.error(message || "FryTrainerGate request failed");
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) return <ActivityIndicator />;

  const runners = runnersData?.runners ?? [];
  const datasets = datasetsData?.datasets ?? [];
  const jobs = jobsData?.jobs ?? [];

  return (
    <div className="flex size-full max-w-7xl flex-col gap-5 pr-2">
      <div className="flex items-center justify-between gap-4">
        <div>
          <Heading as="h4">FryTrainerGate</Heading>
          <p className="mt-1 text-sm text-muted-foreground">
            Securely orchestrate custom model training on separate Runner
            machines.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={busy}>
          <LuRefreshCw className="mr-2 size-4" /> Refresh
        </Button>
      </div>

      {(statusError || !status?.available) && (
        <Alert variant="warning">
          <LuShieldAlert />
          <AlertTitle>Controller unavailable</AlertTitle>
          <AlertDescription>
            Configure the Frygate service credential and start the separate
            FryTrainerGate Controller. Frigate itself continues operating
            normally.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <SettingsGroupCard title="Overview">
          <div className="text-2xl font-semibold">
            {status?.runner_count ?? 0}
          </div>
          <div className="text-sm text-muted-foreground">
            registered runners
          </div>
        </SettingsGroupCard>
        <SettingsGroupCard title="Queued jobs">
          <div className="text-2xl font-semibold">
            {status?.job_counts?.QUEUED ?? 0}
          </div>
          <div className="text-sm text-muted-foreground">
            waiting for a compatible runner
          </div>
        </SettingsGroupCard>
        <SettingsGroupCard title="Security boundary">
          <div className="text-sm text-muted-foreground">
            Browser traffic is proxied by Frygate. Dataset and artifact bytes
            are never exposed through public anonymous URLs.
          </div>
        </SettingsGroupCard>
      </div>

      <SettingsGroupCard title="Runners">
        <div className="mb-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <div>
            <Label htmlFor="runner-name">Add Runner</Label>
            <Input
              id="runner-name"
              value={runnerName}
              onChange={(event) => setRunnerName(event.target.value)}
              placeholder="Gaming PC"
              className="mt-2"
            />
          </div>
          <Button
            className="self-end"
            disabled={busy || !runnerName.trim()}
            onClick={() =>
              action(async () => {
                const response = await axios.post(
                  "frytrainergate/runners/pairing",
                  {
                    name: runnerName.trim(),
                  },
                );
                setPairingToken(response.data.pairing_token);
                setRunnerName("");
              }, "Pairing token created")
            }
          >
            Create one-time token
          </Button>
        </div>
        {pairingToken && (
          <Alert className="mb-5">
            <AlertTitle>Copy this pairing token now</AlertTitle>
            <AlertDescription>
              It is shown once, expires shortly, and cannot be reused after
              registration.
              <div className="mt-3 flex flex-wrap gap-2">
                <code className="rounded bg-muted px-3 py-2 text-xs">
                  {pairingToken}
                </code>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => navigator.clipboard?.writeText(pairingToken)}
                >
                  <LuCopy className="mr-2 size-4" /> Copy
                </Button>
              </div>
              <code className="mt-3 block break-all rounded bg-muted p-2 text-xs">
                docker run --rm --gpus all -e
                FRYTRAINERGATE_URL=https://runner.example.tld -e
                FRYTRAINERGATE_PAIRING_TOKEN='{pairingToken}' -v
                frytrainergate-runner-data:/data
                ghcr.io/fry2412/frigate-frytrainergate-runner:TAG
              </code>
            </AlertDescription>
          </Alert>
        )}
        {rotatedSecret && (
          <Alert className="mb-5">
            <AlertTitle>New Runner credential</AlertTitle>
            <AlertDescription>
              Replace the persisted Runner credential with this value. It will
              not be shown again.
              <code className="mt-2 block break-all rounded bg-muted p-2 text-xs">
                {rotatedSecret}
              </code>
            </AlertDescription>
          </Alert>
        )}
        <div className="space-y-3">
          {runners.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No Runners registered.
            </p>
          )}
          {runners.map((runner) => (
            <div
              key={runner.id}
              className="rounded-md border border-border/70 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-medium">{runner.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {runner.platform} · v{runner.runner_version}
                  </div>
                </div>
                <Badge variant={statusVariant(runner.status)}>
                  {runner.status}
                </Badge>
              </div>
              <div className="mt-3 grid gap-2 text-sm text-muted-foreground md:grid-cols-4">
                <span>GPU: {runner.capabilities.gpu_name || "none"}</span>
                <span>
                  VRAM:{" "}
                  {runner.capabilities.vram_mb
                    ? `${runner.capabilities.vram_mb} MB`
                    : "—"}
                </span>
                <span>CUDA: {runner.capabilities.cuda ? "yes" : "no"}</span>
                <span>Job: {runner.current_job_id || "—"}</span>
              </div>
              <div className="mt-2 text-xs text-muted-foreground">
                Last seen:{" "}
                {runner.last_seen_at
                  ? new Date(runner.last_seen_at).toLocaleString()
                  : "never"}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      const name = window.prompt("Runner name", runner.name);
                      if (!name?.trim()) return;
                      await axios.patch(`frytrainergate/runners/${runner.id}`, {
                        name: name.trim(),
                      });
                    }, "Runner renamed")
                  }
                >
                  Rename
                </Button>
                {runner.enabled ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      action(
                        () =>
                          axios.post(
                            `frytrainergate/runners/${runner.id}/disable`,
                          ),
                        "Runner disabled",
                      )
                    }
                  >
                    Disable
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() =>
                      action(
                        () =>
                          axios.post(
                            `frytrainergate/runners/${runner.id}/enable`,
                          ),
                        "Runner enabled",
                      )
                    }
                  >
                    Enable
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy || !runner.enabled}
                  onClick={() =>
                    action(async () => {
                      const response = await axios.post(
                        `frytrainergate/runners/${runner.id}/rotate`,
                      );
                      setRotatedSecret(response.data.runner_secret);
                    }, "Runner credential rotated")
                  }
                >
                  Rotate credential
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    action(
                      () =>
                        axios.post(
                          `frytrainergate/runners/${runner.id}/revoke`,
                        ),
                      "Runner revoked",
                    )
                  }
                >
                  Revoke
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={busy}
                  onClick={() => {
                    if (
                      !window.confirm(
                        "Delete this Runner? Its credential will be revoked.",
                      )
                    )
                      return;
                    void action(
                      () => axios.delete(`frytrainergate/runners/${runner.id}`),
                      "Runner deleted",
                    );
                  }}
                >
                  Delete
                </Button>
              </div>
            </div>
          ))}
        </div>
      </SettingsGroupCard>

      <SettingsGroupCard title="Datasets">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <Input
            value={datasetName}
            onChange={(event) => setDatasetName(event.target.value)}
            placeholder="Driveway validation set"
          />
          <Button
            disabled={busy || !datasetName.trim()}
            onClick={() =>
              action(async () => {
                await axios.post("frytrainergate/datasets", {
                  name: datasetName.trim(),
                });
                setDatasetName("");
              }, "Dataset created")
            }
          >
            Create dataset
          </Button>
        </div>
        <div className="mt-4 space-y-2">
          {datasets.map((dataset) => (
            <div
              key={dataset.id}
              className="flex flex-wrap justify-between gap-2 rounded border border-border/60 p-3 text-sm"
            >
              <span className="font-medium">{dataset.name}</span>
              <span className="text-muted-foreground">
                {dataset.image_count} images · {formatBytes(dataset.size)}
              </span>
            </div>
          ))}
          {datasets.length === 0 && (
            <p className="text-sm text-muted-foreground">No datasets yet.</p>
          )}
        </div>
      </SettingsGroupCard>

      <SettingsGroupCard title="Training jobs">
        <div className="grid gap-3 md:grid-cols-4">
          <Input
            value={jobName}
            onChange={(event) => setJobName(event.target.value)}
            placeholder="Development pipeline check"
          />
          <select
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            value={selectedDataset}
            onChange={(event) => setSelectedDataset(event.target.value)}
          >
            <option value="">Select dataset</option>
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
          <select
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            value={selectedRunner}
            onChange={(event) => setSelectedRunner(event.target.value)}
          >
            <option value="">Automatic runner</option>
            {runners
              .filter((runner) => runner.enabled)
              .map((runner) => (
                <option key={runner.id} value={runner.id}>
                  {runner.name}
                </option>
              ))}
          </select>
          <Button
            disabled={busy || !jobName.trim() || !selectedDataset}
            onClick={() =>
              action(async () => {
                await axios.post("frytrainergate/jobs", {
                  name: jobName.trim(),
                  dataset_id: selectedDataset,
                  runner_id: selectedRunner || null,
                  backend: "development_test",
                  config: { epochs: 3 },
                  requirements: { training_backend: "development_test" },
                });
                setJobName("");
              }, "Training job created")
            }
          >
            Submit test job
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          The development/test backend produces a clearly labeled deterministic
          artifact; it is not an inference model.
        </p>
        <div className="mt-4 space-y-2">
          {jobs.map((job) => (
            <div key={job.id} className="rounded border border-border/60 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{job.name}</span>
                <Badge variant={statusVariant(job.state)}>{job.state}</Badge>
              </div>
              <div className="mt-2 text-sm text-muted-foreground">
                {job.backend} · {Math.round(job.progress)}% ·{" "}
                {job.status_message || "—"}
              </div>
              {job.failure_reason && (
                <div className="mt-1 text-sm text-destructive">
                  {job.failure_reason}
                </div>
              )}
              {!["SUCCEEDED", "FAILED", "CANCELLED", "RUNNER_LOST"].includes(
                job.state,
              ) && (
                <Button
                  className="mt-3"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    action(
                      () => axios.post(`frytrainergate/jobs/${job.id}/cancel`),
                      "Cancellation requested",
                    )
                  }
                >
                  Cancel
                </Button>
              )}
            </div>
          ))}
          {jobs.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No training jobs yet.
            </p>
          )}
        </div>
      </SettingsGroupCard>

      <SettingsGroupCard title="Model artifacts">
        <div className="space-y-2">
          {(modelsData?.models ?? []).map((model) => (
            <div
              key={String(model.id)}
              className="rounded border border-border/60 p-3 text-sm"
            >
              <div className="font-medium">{String(model.filename)}</div>
              <div className="text-muted-foreground">
                {String(model.model_format)} ·{" "}
                {formatBytes(Number(model.size) || 0)} · SHA-256{" "}
                {String(model.sha256)}
              </div>
            </div>
          ))}
          {(modelsData?.models ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">
              No artifacts have been uploaded.
            </p>
          )}
        </div>
      </SettingsGroupCard>
    </div>
  );
}

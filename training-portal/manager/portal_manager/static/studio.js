const el = (id) => document.getElementById(id);
const node = (tag, text, className) => {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
};
const ref = (dataset) => ({id: dataset.id, manifest_sha256: dataset.manifest_sha256});
const key = (dataset) => `${dataset.id}:${dataset.manifest_sha256}`;
const number = (id) => Number(el(id).value);
const kinds = {prepare_dataset: "Dataset preparation", base_train: "Base training", refine: "Camera refinement", custom: "Custom training"};

export function createStudio(request, message) {
  let datasets = [], models = [], jobs = [], images = [], connected = false;
  let jobsSignature = "";
  let catalogSignature = "";
  let camerasSignature = "";
  const modelNames = new Map();
  el("prepare-submit").disabled = true;

  function options(select, entries, placeholder) {
    const previous = select.value;
    select.replaceChildren(new Option(placeholder, ""));
    for (const [value, label] of entries) select.append(new Option(label, value));
    if (entries.some(([value]) => value === previous)) select.value = previous;
  }
  const datasetSelected = () => datasets.find((dataset) => key(dataset) === el("base-dataset").value);
  const modelSelected = () => models.find((model) => model.id === el("refine-model").value);

  function updateSelection() {
    el("prepare-submit").disabled = !connected;
    const dataset = datasetSelected();
    el("base-submit").disabled = !connected || !dataset;
    el("dataset-summary").textContent = dataset
      ? `${dataset.classes.length} classes · ${dataset.train_images.toLocaleString()} training / ${dataset.val_images.toLocaleString()} validation images · ${dataset.runner_ids.length} runner(s)`
      : "Prepare COCO below or import a reviewed dataset on a runner.";
    const model = modelSelected();
    el("refine-taxonomy").textContent = model
      ? `Output vocabulary: ${model.classes.length} classes. The parent class order is inherited: ${model.classes.slice(0, 6).join(", ")}${model.classes.length > 6 ? ", …" : ""}.`
      : "Save a successful training result in the model library first.";
    const selectedCameras = el("refine-cameras").querySelectorAll("input:checked");
    el("refine-submit").disabled = !connected || !model || !selectedCameras.length;
    const replayDataset = model?.dataset && datasets.find((item) => key(item) === key(model.dataset));
    el("replay-summary").textContent = replayDataset
      ? `Optional references use ${replayDataset.name}'s training split. 0 uses camera images only.`
      : "0 uses camera images only. Reference replay requires the parent's original dataset on the selected runner.";
  }

  function renderCameras() {
    const signature = JSON.stringify(images.map((image) => [image.id, image.camera, image.verified]));
    if (signature === camerasSignature) return;
    camerasSignature = signature;
    const host = el("refine-cameras");
    const selected = new Set([...host.querySelectorAll("input:checked")].map((input) => input.value));
    host.replaceChildren();
    const cameras = [...new Set(images.map((image) => image.camera))].sort();
    if (!cameras.length) host.append(node("p", "Submit or upload camera images, then mark them reviewed.", "muted"));
    for (const camera of cameras) {
      const reviewed = images.filter((image) => image.camera === camera && image.verified).length;
      const label = node("label", undefined, "check-label");
      const input = node("input"); input.type = "checkbox"; input.value = camera;
      input.checked = selected.has(camera); input.disabled = !reviewed;
      input.addEventListener("change", updateSelection);
      label.append(input, node("span", `${camera} · ${reviewed} reviewed`)); host.append(label);
    }
  }

  function renderModels() {
    const host = el("models"); host.replaceChildren();
    if (!models.length) host.append(node("p", "No saved models yet. Train a base model, then save its successful result below.", "empty"));
    for (const model of models) {
      const card = node("article", undefined, "model-card");
      card.append(node("h3", model.name), node("p", `${model.classes.length} classes · ${kinds[model.kind] || model.kind}`));
      card.append(node("p", `Checkpoint ${model.sha256.slice(0, 12)} · ${new Date(model.created_at * 1000).toLocaleDateString()}`, "form-help"));
      if (model.parent_model_id) card.append(node("p", `Parent: ${models.find((item) => item.id === model.parent_model_id)?.name || model.parent_model_id.slice(0, 8)}`, "form-help"));
      const choose = node("button", "Use for refinement"); choose.type = "button";
      choose.addEventListener("click", () => { el("refine-model").value = model.id; updateSelection(); el("refine-model").focus(); });
      card.append(choose); host.append(card);
    }
  }

  function download(job) {
    const button = node("button", "Download result"); button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const blob = await request(`/api/v1/jobs/${encodeURIComponent(job.id)}/artifact`);
        const link = node("a"); link.href = URL.createObjectURL(blob); link.download = `${job.id}-result.zip`;
        link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    });
    return button;
  }

  function renderJobs() {
    const signature = JSON.stringify([jobs.map((job) => [job.id, job.status, job.error, job.artifact_available]), models.map((model) => model.job_id)]);
    if (signature === jobsSignature) return;
    jobsSignature = signature;
    const host = el("jobs"); host.replaceChildren();
    if (!jobs.length) host.append(node("p", "No jobs yet. Dataset preparation and training progress appear here.", "empty"));
    const savedJobs = new Set(models.map((model) => model.job_id));
    for (const job of jobs) {
      const row = node("article", undefined, "job-row");
      const info = node("div", undefined, "job-info");
      info.append(node("strong", kinds[job.kind || "custom"] || job.kind), node("span", job.status, `job-status ${job.status}`));
      info.append(node("p", `${job.id.slice(0, 8)} · ${new Date(job.created_at * 1000).toLocaleString()}`, "form-help"));
      if (job.options?.cameras?.length) info.append(node("p", job.options.cameras.join(", "), "form-help"));
      if (job.error) info.append(node("p", job.error, "danger"));
      row.append(info);
      const actions = node("div", undefined, "job-actions");
      if (job.artifact_available) actions.append(download(job));
      if (job.status === "succeeded" && job.kind !== "prepare_dataset" && !savedJobs.has(job.id)) {
        const form = node("form", undefined, "save-model-form");
        const label = node("label", "Model name"); const name = node("input");
        name.required = true; name.maxLength = 100; name.placeholder = job.kind === "refine" ? "Front door · refined" : "My base model";
        name.value = modelNames.get(job.id) || "";
        name.addEventListener("input", () => modelNames.set(job.id, name.value)); label.append(name);
        const save = node("button", "Save trusted model");
        form.append(label, save); form.addEventListener("submit", async (event) => {
          event.preventDefault(); save.disabled = true;
          try { await post("/api/v1/models", {job_id: job.id, name: name.value.trim()}); await refresh(); message("Model saved. It can now be selected for camera refinement."); }
          catch (error) { message(error.message, true); }
          finally { save.disabled = false; }
        }); actions.append(form);
      } else if (savedJobs.has(job.id)) actions.append(node("span", "Saved in model library", "form-help"));
      row.append(actions); host.append(row);
    }
  }

  const post = (url, body) => request(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  async function submit(form, action) {
    const button = form.querySelector("button"); button.disabled = true;
    try { await action(); await refresh(); }
    catch (error) { message(error.message, true); }
    finally { button.disabled = false; updateSelection(); }
  }
  el("base-dataset").addEventListener("change", updateSelection);
  el("refine-model").addEventListener("change", updateSelection);
  el("prepare-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submit(event.currentTarget, async () => {
      await post("/api/v1/datasets/prepare", {source: "coco2017", train_images: number("prepare-train"), val_images: number("prepare-val"), seed: number("prepare-seed"), license_ack: el("prepare-license").checked});
      message("COCO preparation queued. The dataset will appear when the runner has finished preparing it.");
    });
  });
  el("base-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submit(event.currentTarget, async () => {
      const dataset = datasetSelected(); if (!dataset) throw new Error("Select a prepared dataset.");
      await post("/api/v1/jobs", {kind: "base_train", dataset: ref(dataset), epochs: number("base-epochs"), batch_size: number("base-batch"), image_size: number("base-size"), initialization: el("base-initialization").value});
      message("Base training queued. Save its successful result to the model library afterwards.");
    });
  });
  el("refine-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await submit(event.currentTarget, async () => {
      const model = modelSelected(); if (!model) throw new Error("Select a saved parent model.");
      const replay = number("refine-replay");
      const body = {kind: "refine", base_model_id: model.id, cameras: [...el("refine-cameras").querySelectorAll("input:checked")].map((input) => input.value), epochs: number("refine-epochs"), batch_size: number("refine-batch"), image_size: number("refine-size"), replay_images: replay};
      if (replay > 0) {
        if (!model.dataset || !datasets.some((item) => key(item) === key(model.dataset))) throw new Error("The parent's reference dataset is not available. Use 0 reference images or prepare the matching dataset.");
        body.dataset = ref(model.dataset);
      }
      await post("/api/v1/jobs", body); message("Camera refinement queued. The parent's full output class list is inherited.");
    });
  });

  async function refresh() {
    [datasets, models, jobs] = await Promise.all([request("/api/v1/datasets"), request("/api/v1/models"), request("/api/v1/jobs")]);
    connected = true;
    const signature = JSON.stringify([datasets, models]);
    if (signature !== catalogSignature) {
      catalogSignature = signature;
      options(el("base-dataset"), datasets.map((dataset) => [key(dataset), `${dataset.name} · ${dataset.manifest_sha256.slice(0, 8)}`]), "Select a prepared dataset");
      options(el("refine-model"), models.map((model) => [model.id, `${model.name} · ${model.classes.length} classes`]), "Select a saved model");
      renderModels();
    }
    renderCameras(); renderJobs(); updateSelection();
  }
  return {refresh, setImages(value) { images = value; renderCameras(); updateSelection(); }, disconnect() { connected = false; el("prepare-submit").disabled = true; updateSelection(); }};
}

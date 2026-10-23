---
id: model-trainer
title: Model trainer submissions
---

Frigate can optionally send snapshots to a self-hosted model training portal for
review and manual annotations. This integration is disabled by default and is
separate from Frigate+'s model discovery and `plus://` model downloads.

Configure the portal and explicitly select it as the image submission
destination:

```yaml
model_trainer:
  enabled: true
  url: http://manager:8080
  api_key: "{FRIGATE_MODEL_TRAINER_API_KEY}"

image_submission_api: model_trainer
```

Set `FRIGATE_MODEL_TRAINER_API_KEY` in the Frigate container environment or
provide a Docker secret with that name. Secret values are hidden from the
`/api/config` response. The portal API key is sent only to the configured
portal URL.

`image_submission_api` defaults to `plus`, preserving existing Frigate+
submissions. Setting it to `model_trainer` routes event snapshots, false
positive annotations, and recording snapshots to the portal. The selection
does not change `plus_api` model discovery, metadata lookup, or loading of
`plus://` models.

Event snapshots are submitted as JPEG images. The event box can be included as
a positive annotation, while false positives are submitted as negative
annotations. Portal IDs are stored in Frigate's existing submission field with
a `portal:` prefix. To avoid sending an existing submission to the wrong
service, events must continue to use the destination where they were first
submitted.

This is an opt-in POC integration. It supports image review and manual positive
and negative annotations; it does not provide automatic prelabels, Coral INT8
compilation, or a Coral-ready model guarantee.

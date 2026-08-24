"""Deterministic development backend used to validate the full data path.

This is intentionally not presented as a detector or a trained model.  It
creates a small, inspectable development artifact from the received dataset.
The runner dispatches to this known module only; no command is accepted from a
job payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    dataset = Path(args.dataset).resolve()
    spec = Path(args.spec).resolve()
    output = Path(args.output).resolve()
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = json.loads(spec.read_text(encoding="utf-8"))
    images = manifest.get("images", [])
    epochs = int(config.get("epochs", 1))
    delay = float(os.environ.get("FRYTRAINERGATE_TEST_STEP_DELAY", "0.05"))
    dataset_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    for epoch in range(1, epochs + 1):
        time.sleep(delay)
        print(
            "PROGRESS "
            + json.dumps(
                {
                    "epoch": epoch,
                    "total_epochs": epochs,
                    "progress": epoch / epochs * 100,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    output.write_text(
        json.dumps(
            {
                "artifact_type": "development_test_artifact",
                "not_a_detector_model": True,
                "protocol_version": "1.0",
                "dataset_image_count": len(images),
                "dataset_manifest_sha256": dataset_digest,
                "training_config": config,
            },
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

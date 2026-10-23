"""Create disposable synthetic data for container import/training checks.

This tests execution only. Its results say nothing about detector quality.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def create(root: Path):
    for split in ("train", "val"):
        for kind in ("images", "labels"):
            (root / kind / split).mkdir(parents=True, exist_ok=True)
        for index in range(2):
            image = Image.new("RGB", (64, 64), (30, 40 + index * 30, 50))
            ImageDraw.Draw(image).rectangle((16, 16, 48, 48), fill=(20, 190, 130))
            image.save(root / "images" / split / f"{index}.jpg")
            (root / "labels" / split / f"{index}.txt").write_text(
                "0 0.5 0.5 0.5 0.5\n", encoding="utf-8"
            )
    (root / "data.yaml").write_text(
        "path: /smoke\ntrain: images/train\nval: images/val\nnames: [synthetic]\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    create(parser.parse_args().directory)

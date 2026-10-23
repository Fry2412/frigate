import base64
import uuid

import requests
from numpy import ndarray

from frigate.plus import get_jpg_bytes


def validate_submission_destination(
    image_submission_api: str, submission_id: str
) -> None:
    is_portal_id = submission_id.startswith("portal:")
    if (image_submission_api == "model_trainer") != is_portal_id:
        raise ValueError(
            "This event was submitted to a different image destination. "
            "Select its original destination before submitting again."
        )


class ModelTrainerApi:
    """Client for the optional, single-tenant image training portal."""

    def __init__(
        self, url: str | None, api_key: str | None, enabled: bool = True
    ) -> None:
        self.url = (url or "").rstrip("/")
        self.api_key = api_key or ""
        self.enabled = enabled
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def is_active(self) -> bool:
        return bool(self.enabled and self.url and self.api_key)

    def _post(self, path: str, data: dict) -> requests.Response:
        response = self._session.post(
            f"{self.url}/api/v1/{path}",
            json=data,
            timeout=30,
            allow_redirects=False,
        )
        if not response.ok or 300 <= response.status_code < 400:
            raise RuntimeError(
                f"Model trainer request failed ({response.status_code}): {response.text}"
            )
        return response

    def upload_image(self, image: ndarray, camera: str) -> str:
        jpeg = get_jpg_bytes(image, 1920, 85)
        response = self._post(
            "images",
            {"camera": camera, "image_base64": base64.b64encode(jpeg).decode("ascii")},
        )
        image_id = response.json().get("id")
        try:
            image_id = str(uuid.UUID(str(image_id)))
        except (ValueError, AttributeError):
            raise ValueError("Model trainer returned an invalid image id") from None
        return f"portal:{image_id}"

    def add_annotation(
        self,
        portal_id: str,
        bbox: list[float],
        label: str,
        difficult: bool = False,
        negative: bool = False,
    ) -> None:
        if not portal_id.startswith("portal:"):
            raise ValueError(
                "Cannot submit a non-portal image ID to the model trainer. "
                "Select the image's original submission destination."
            )
        image_id = portal_id.removeprefix("portal:")
        try:
            image_id = str(uuid.UUID(image_id))
        except ValueError:
            raise ValueError("Invalid model trainer image ID") from None

        self._post(
            f"images/{image_id}/annotations",
            {
                "label": label,
                "bbox": bbox,
                "negative": negative,
                "difficult": difficult,
            },
        )

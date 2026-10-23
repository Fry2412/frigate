import base64
import uuid
from unittest.mock import Mock

import numpy as np
import pytest

from frigate.model_trainer import ModelTrainerApi, validate_submission_destination


def test_image_upload_posts_jpeg_as_base64_and_returns_portal_id(monkeypatch):
    api = ModelTrainerApi("https://trainer.example/", "token")
    image_id = str(uuid.uuid4())
    response = Mock(ok=True, status_code=200)
    response.json.return_value = {"id": image_id}
    post = Mock(return_value=response)
    monkeypatch.setattr(api._session, "post", post)

    submitted_id = api.upload_image(np.zeros((16, 16, 3), dtype=np.uint8), "front")

    assert submitted_id == f"portal:{image_id}"
    args, kwargs = post.call_args
    assert args[0] == "https://trainer.example/api/v1/images"
    assert kwargs["json"]["camera"] == "front"
    jpeg = base64.b64decode(kwargs["json"]["image_base64"])
    assert jpeg.startswith(b"\xff\xd8")
    assert kwargs["timeout"] == 30
    assert kwargs["allow_redirects"] is False
    assert api._session.headers["Authorization"] == "Bearer token"


@pytest.mark.parametrize("negative", [False, True])
def test_annotation_posts_normalized_xywh_payload(monkeypatch, negative):
    api = ModelTrainerApi("http://trainer", "token")
    image_id = str(uuid.uuid4())
    response = Mock(ok=True, status_code=200)
    post = Mock(return_value=response)
    monkeypatch.setattr(api._session, "post", post)

    api.add_annotation(
        f"portal:{image_id}", [0.1, 0.2, 0.3, 0.4], "person", negative=negative
    )

    assert (
        post.call_args.args[0] == f"http://trainer/api/v1/images/{image_id}/annotations"
    )
    assert post.call_args.kwargs["json"] == {
        "label": "person",
        "bbox": [0.1, 0.2, 0.3, 0.4],
        "negative": negative,
        "difficult": False,
    }


def test_annotation_rejects_plus_ids_and_http_failures(monkeypatch):
    api = ModelTrainerApi("http://trainer", "token")
    with pytest.raises(ValueError, match="non-portal image ID"):
        api.add_annotation("plus-image-id", [0, 0, 1, 1], "person")

    response = Mock(ok=False, status_code=401, text="unauthorized")
    monkeypatch.setattr(api._session, "post", Mock(return_value=response))
    with pytest.raises(Exception, match="401.*unauthorized"):
        api.add_annotation(
            f"portal:{uuid.uuid4()}", [0, 0, 1, 1], "person", negative=True
        )


def test_http_redirects_are_rejected_without_following_cross_host_location(
    monkeypatch,
):
    api = ModelTrainerApi("https://trainer.example", "token")
    response = Mock(ok=True, status_code=302, text="redirect")
    response.headers = {"Location": "https://attacker.example/collect"}
    post = Mock(return_value=response)
    monkeypatch.setattr(api._session, "post", post)

    with pytest.raises(RuntimeError, match="302"):
        api.upload_image(np.zeros((8, 8, 3), dtype=np.uint8), "front")

    post.assert_called_once()
    assert post.call_args.kwargs["allow_redirects"] is False


def test_submission_ids_cannot_be_reused_with_a_different_destination():
    validate_submission_destination("model_trainer", f"portal:{uuid.uuid4()}")
    validate_submission_destination("plus", "plus-image-id")

    with pytest.raises(ValueError, match="different image destination"):
        validate_submission_destination("model_trainer", "plus-image-id")
    with pytest.raises(ValueError, match="different image destination"):
        validate_submission_destination("plus", f"portal:{uuid.uuid4()}")

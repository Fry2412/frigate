import copy
from unittest.mock import patch

from fastapi import Response
from frigate.api.auth import get_allowed_cameras_for_filter
from frigate.models import Export, ExportCase, Recordings
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpMultiCam(BaseTestHttp):
    def setUp(self):
        super().setUp([Export, ExportCase, Recordings])
        self.minimal_config["cameras"]["back_door"] = copy.deepcopy(
            self.minimal_config["cameras"]["front_door"]
        )
        self.minimal_config["auth"] = {
            "enabled": False,
            "roles": {"limited": ["front_door"]},
        }
        self.app = self.create_app()
        self.app.dependency_overrides.pop(get_allowed_cameras_for_filter)
        self.body = {
            "name": "Journey",
            "plan": {
                "shots": [
                    {"start": 100, "end": 110, "cameras": ["front_door", "back_door"]}
                ]
            },
        }
        self.limited = {"remote-user": "limited", "remote-role": "limited"}
        Export.create(
            id="multicam_test",
            camera="front_door",
            name="Journey",
            date=100,
            video_path="/media/frigate/exports/multicam_test.mp4",
            thumb_path="/media/frigate/exports/multicam_test.webp",
            in_progress=False,
            composite_plan=self.body["plan"],
        )

    def test_rejects_inaccessible_camera_on_start_and_preview(self):
        with (
            patch("frigate.api.export.start_export_job") as start,
            AuthTestClient(self.app) as client,
        ):
            for endpoint in ("/exports/multicam", "/exports/multicam/preview"):
                response = client.post(endpoint, json=self.body, headers=self.limited)
                self.assertEqual(response.status_code, 403)
        start.assert_not_called()

    def test_audio_camera_requires_access_too(self):
        body = copy.deepcopy(self.body)
        body["plan"]["shots"][0]["cameras"] = ["front_door"]
        body["plan"]["audio_camera"] = "back_door"
        with AuthTestClient(self.app) as client:
            self.assertEqual(
                client.post(
                    "/exports/multicam/preview", json=body, headers=self.limited
                ).status_code,
                403,
            )

    def test_start_retains_plan_and_allows_authorized_user(self):
        with (
            patch("frigate.api.export.start_export_job") as start,
            AuthTestClient(self.app) as client,
        ):
            response = client.post("/exports/multicam", json=self.body)
        self.assertEqual(response.status_code, 200)
        job = start.call_args.args[1]
        self.assertEqual(
            job.composite_plan["shots"][0]["cameras"], ["front_door", "back_door"]
        )

    def test_list_and_detail_require_every_camera(self):
        with AuthTestClient(self.app) as client:
            self.assertEqual(client.get("/exports", headers=self.limited).json(), [])
            self.assertEqual(
                client.get("/exports/multicam_test", headers=self.limited).status_code,
                403,
            )
            self.assertEqual(client.get("/exports/multicam_test").status_code, 200)

    def test_preview_reports_absolute_and_output_times(self):
        with AuthTestClient(self.app) as client:
            response = client.post("/exports/multicam/preview", json=self.body)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["duration"], 10)
        self.assertEqual(result["windows"][0]["output_start"], 0)
        self.assertEqual(
            result["windows"][0]["coverage"], {"front_door": [], "back_door": []}
        )

    def test_media_auth_checks_download_and_thumbnail(self):
        for extension in ("mp4", "webp"):
            with (
                self.subTest(extension=extension),
                patch(
                    "frigate.api.auth._authenticate_request",
                    return_value=Response(
                        status_code=202, headers={"remote-role": "limited"}
                    ),
                ),
                AuthTestClient(self.app) as client,
            ):
                response = client.get(
                    "/auth",
                    headers={
                        "x-original-url": f"http://frigate/exports/multicam_test.{extension}"
                    },
                )
            self.assertEqual(response.status_code, 403)
        with (
            patch(
                "frigate.api.auth._authenticate_request",
                return_value=Response(
                    status_code=202, headers={"remote-role": "admin"}
                ),
            ),
            AuthTestClient(self.app) as client,
        ):
            self.assertEqual(
                client.get(
                    "/auth",
                    headers={
                        "x-original-url": "http://frigate/exports/multicam_test.mp4"
                    },
                ).status_code,
                202,
            )
            self.assertEqual(
                client.get(
                    "/auth",
                    headers={
                        "x-original-url": "http://frigate/exports/.multicam/job/source_0.mp4"
                    },
                ).status_code,
                403,
            )

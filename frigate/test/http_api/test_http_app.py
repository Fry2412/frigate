from unittest.mock import Mock

from frigate.models import Event, Recordings, ReviewSegment
from frigate.stats.emitter import StatsEmitter
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpApp(BaseTestHttp):
    def setUp(self):
        super().setUp([Event, Recordings, ReviewSegment])
        self.app = super().create_app()

    def test_config_redacts_model_trainer_key_and_reports_submission_provider(self):
        self.minimal_config["model_trainer"] = {
            "enabled": True,
            "url": "http://trainer",
            "api_key": "secret-token",
        }
        self.minimal_config["environment_vars"] = {
            "FRIGATE_MODEL_TRAINER_API_KEY": "secret-token"
        }
        self.minimal_config["image_submission_api"] = "model_trainer"
        app = super().create_app()

        with AuthTestClient(app) as client:
            response = client.get("/config")

        config = response.json()
        assert response.status_code == 200
        assert config["model_trainer"]["enabled"] is True
        assert "api_key" not in config["model_trainer"]
        assert "FRIGATE_MODEL_TRAINER_API_KEY" not in config["environment_vars"]
        assert "secret-token" not in response.text
        assert config["plus"] == {"enabled": True, "provider": "model_trainer"}

    ####################################################################################################################
    ###################################  GET /stats Endpoint   #########################################################
    ####################################################################################################################
    def test_stats_endpoint(self):
        stats = Mock(spec=StatsEmitter)
        stats.get_latest_stats.return_value = self.test_stats
        app = super().create_app(stats)

        with AuthTestClient(app) as client:
            response = client.get("/stats")
            response_json = response.json()
            assert response_json == self.test_stats

    def test_config_set_in_memory_replaces_objects_track_list(self):
        self.minimal_config["cameras"]["front_door"]["objects"] = {
            "track": ["person", "car"],
        }
        app = super().create_app()
        app.config_publisher = Mock()

        with AuthTestClient(app) as client:
            response = client.put(
                "/config/set",
                json={
                    "requires_restart": 0,
                    "skip_save": True,
                    "update_topic": "config/cameras/front_door/objects",
                    "config_data": {
                        "cameras": {
                            "front_door": {
                                "objects": {
                                    "track": ["person"],
                                }
                            }
                        }
                    },
                },
            )

            assert response.status_code == 200
            assert app.frigate_config.cameras["front_door"].objects.track == ["person"]

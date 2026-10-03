"""Frigate+ startup should survive transient connection failures."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from frigate.detectors.detector_config import ModelConfig
from frigate.plus import PlusApi


class TestPlusStartup(unittest.TestCase):
    def test_connection_retry_policy(self):
        api = PlusApi()
        retry = api._session.get_adapter(api.host).max_retries
        self.assertEqual(retry.connect, 5)
        self.assertEqual(retry.backoff_factor, 1)

    def test_model_download_failure_is_validation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            api = Mock()
            api.get_model_download_url.side_effect = requests.exceptions.ConnectionError
            model = ModelConfig(path="plus://unreachable")
            with patch("frigate.detectors.detector_config.MODEL_CACHE_DIR", directory):
                with self.assertRaisesRegex(
                    ValueError, r"Unable to connect to Frigate\+"
                ):
                    model.check_and_load_plus_model(api)
            self.assertFalse((Path(directory) / "unreachable").exists())

    def test_model_info_failure_does_not_create_empty_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "unreachable").write_bytes(b"cached model")
            api = Mock()
            api.get_model_info.side_effect = requests.exceptions.ConnectionError
            model = ModelConfig(path="plus://unreachable")
            with patch("frigate.detectors.detector_config.MODEL_CACHE_DIR", directory):
                with self.assertRaisesRegex(ValueError, "download model info"):
                    model.check_and_load_plus_model(api)
            self.assertFalse((Path(directory) / "unreachable.json").exists())

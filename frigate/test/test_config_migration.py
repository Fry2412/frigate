"""Regression tests for config migrations spanning multiple versions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ruamel.yaml import YAML

from frigate.util.config import CURRENT_CONFIG_VERSION, migrate_frigate_config


class TestMigrateConfigFile(unittest.TestCase):
    def test_top_level_changes_survive_later_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yml"
            original = (
                "mqtt:\n  enabled: false\n"
                "genai:\n  provider: ollama\n  model: llava\n"
                "  prompt: describe it\n"
                "auth:\n  enabled: true\n  mode: hybrid\n"
                "  oidc:\n    enabled: true\n"
                "cameras: {}\nversion: 0.15-1\n"
            )
            config_path.write_text(original)
            with patch("frigate.util.config.CONFIG_DIR", directory):
                migrate_frigate_config(str(config_path))

            migrated = YAML().load(config_path)
            self.assertEqual(migrated["version"], CURRENT_CONFIG_VERSION)
            self.assertTrue(migrated["detect"]["enabled"])
            self.assertEqual(migrated["objects"]["genai"], {"prompt": "describe it"})
            self.assertEqual(migrated["genai"]["default"]["provider"], "ollama")
            self.assertEqual(migrated["genai"]["default"]["model"], "llava")
            self.assertEqual(migrated["auth"]["mode"], "hybrid")
            self.assertTrue(migrated["auth"]["oidc"]["enabled"])
            self.assertEqual(
                (Path(directory) / "backup_config.yaml").read_text(), original
            )

            with patch("frigate.util.config.CONFIG_DIR", directory):
                migrate_frigate_config(str(config_path))
            self.assertEqual(YAML().load(config_path), migrated)

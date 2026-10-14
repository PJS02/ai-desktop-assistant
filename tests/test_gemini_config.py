import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai.gemini_client import load_gemini_config


class GeminiConfigTests(unittest.TestCase):
    def test_loads_legacy_config_when_central_config_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy_path = Path(directory) / "gemini_config.json"
            central_path = Path(directory) / "central" / "gemini_config.json"
            legacy_path.write_text('{"api_key": "test"}', encoding="utf-8")
            with patch("ai.gemini_client.CONFIG_PATH", central_path), patch(
                "ai.gemini_client.LEGACY_CONFIG_PATHS", (legacy_path,)
            ):
                self.assertEqual(load_gemini_config(), {"api_key": "test"})
            self.assertEqual(central_path.read_text(encoding="utf-8"), '{\n  "api_key": "test"\n}')

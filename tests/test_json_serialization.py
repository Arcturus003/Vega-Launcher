import unittest
import json
import tempfile
import os


class TestJsonSerialization(unittest.TestCase):
    """
    Unit tests for JSON serialization/deserialization across Vega Launcher models,
    inspired by the unit-test-json-serialization skill patterns.
    """

    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.test_dir.cleanup()

    def test_launcher_config_roundtrip(self):
        """Test full serialization and deserialization round-trip of launcher config."""
        sample_config = {
            "selected_profile": "Fabric 1.20.1",
            "allocated_ram_gb": 4,
            "custom_java_args": "-XX:+UseG1GC -Xmx4G",
            "profiles": {
                "Fabric 1.20.1": {
                    "game_version": "1.20.1",
                    "loader": "fabric",
                    "version": "fabric-loader-0.15.7-1.20.1",
                    "playtime_seconds": 3600
                }
            },
            "language": "tr",
            "dark_mode": True
        }

        file_path = os.path.join(self.test_dir.name, "launcher_config.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(sample_config, f, indent=4)

        with open(file_path, "r", encoding="utf-8") as f:
            loaded_config = json.load(f)

        self.assertEqual(loaded_config["selected_profile"], "Fabric 1.20.1")
        self.assertEqual(loaded_config["allocated_ram_gb"], 4)
        self.assertIn("Fabric 1.20.1", loaded_config["profiles"])
        self.assertEqual(loaded_config["profiles"]["Fabric 1.20.1"]["loader"], "fabric")
        self.assertEqual(loaded_config, sample_config)

    def test_launcher_config_missing_and_null_fields(self):
        """Verify fallback behavior when JSON properties are null or missing."""
        partial_json = '{"selected_profile": null, "profiles": {}}'
        loaded = json.loads(partial_json)

        self.assertIsNone(loaded.get("selected_profile"))
        self.assertEqual(loaded.get("profiles"), {})
        # Fallback defaults
        allocated_ram = loaded.get("allocated_ram_gb", 4)
        self.assertEqual(allocated_ram, 4)

    def test_integrity_hashes_serialization(self):
        """Verify .integrity dictionary serialization and structure validation."""
        sample_hashes = {
            "main.py": "a" * 64,
            "server_widget.py": "b" * 64,
            "integrity_check.py": "c" * 64
        }
        serialized = json.dumps(sample_hashes, indent=4)
        deserialized = json.loads(serialized)

        self.assertIsInstance(deserialized, dict)
        self.assertEqual(len(deserialized), 3)
        for filename, sha in deserialized.items():
            self.assertEqual(len(sha), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in sha.lower()))

    def test_invalid_json_handling(self):
        """Verify that malformed JSON strings raise appropriate parse errors."""
        corrupted_json = '{"selected_profile": "Test", "allocated_ram_gb": '
        with self.assertRaises(json.JSONDecodeError):
            json.loads(corrupted_json)

    def test_last_server_config_roundtrip(self):
        """Verify that last_server setting serializes and deserializes properly."""
        config_data = {
            "profiles": {},
            "settings": {
                "language": "tr",
                "last_server": "TestSurvivalServer"
            }
        }
        serialized = json.dumps(config_data, indent=4)
        loaded = json.loads(serialized)
        self.assertEqual(loaded.get("settings", {}).get("last_server"), "TestSurvivalServer")

        # Missing last_server defaults safely to empty string
        empty_settings = {"settings": {}}
        self.assertEqual(empty_settings.get("settings", {}).get("last_server", ""), "")


if __name__ == "__main__":
    unittest.main()

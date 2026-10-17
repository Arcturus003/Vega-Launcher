import unittest
import os
import shutil
import tempfile
import json
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for widget testing
app = QApplication.instance() or QApplication([])

from server_widget import ServerWidget


class TestServerPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.servers_dir = os.path.join(self.temp_dir, "servers")
        os.makedirs(self.servers_dir, exist_ok=True)
        self.config_path = os.path.join(self.temp_dir, "launcher_config.json")
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"profiles": {}, "settings": {"last_server": "TestBeta"}}, f, indent=4)

        # Create two server folders
        os.makedirs(os.path.join(self.servers_dir, "TestAlpha"), exist_ok=True)
        os.makedirs(os.path.join(self.servers_dir, "TestBeta"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_refresh_server_list_selects_last_server(self):
        widget = ServerWidget()
        widget.servers_dir = self.servers_dir
        # Mock _get_config_path
        widget._get_config_path = lambda: self.config_path

        widget.refresh_server_list()
        self.assertEqual(widget.server_selector.currentText(), "TestBeta")

    def test_selection_change_persists_last_server(self):
        widget = ServerWidget()
        widget.servers_dir = self.servers_dir
        widget._get_config_path = lambda: self.config_path

        widget.refresh_server_list()
        # Change selection to TestAlpha
        idx = widget.server_selector.findText("TestAlpha")
        widget.server_selector.setCurrentIndex(idx)

        # Verify config file on disk was updated
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("settings", {}).get("last_server"), "TestAlpha")

    def test_fallback_when_last_server_does_not_exist(self):
        # Set non-existent server in config
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"profiles": {}, "settings": {"last_server": "NonExistent"}}, f, indent=4)

        widget = ServerWidget()
        widget.servers_dir = self.servers_dir
        widget._get_config_path = lambda: self.config_path

        widget.refresh_server_list()
        # Should gracefully fall back to the first available server
        self.assertIn(widget.server_selector.currentText(), ["TestAlpha", "TestBeta"])


if __name__ == "__main__":
    unittest.main()

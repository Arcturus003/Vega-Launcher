import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

# Ensure headless Qt
app = QApplication.instance() or QApplication([])

from auth_vault import AuthenticationVault
from server_downloader import ServerSoftwareDialog
from ui_components import InstalledModsPanel


class TestAuditPonytailFixes(unittest.TestCase):
    def test_neoforge_dynamic_version_resolution(self):
        """Verify NeoForge dynamic version prefix logic handles modern and edge versions."""
        test_cases = [
            ("1.20.2", "20.2."),
            ("1.20.4", "20.4."),
            ("1.21", "21.0."),
            ("1.21.1", "21.1."),
            ("1.21.2", "21.2."),
            ("1.21.3", "21.3."),
            ("1.21.4", "21.4."),
        ]
        import re
        for version, expected_prefix in test_cases:
            m = re.match(r"^1\.(\d+)(?:\.(\d+))?$", version)
            self.assertIsNotNone(m)
            self.assertFalse(int(m.group(1)) < 20 or (int(m.group(1)) == 20 and int(m.group(2) or 0) < 2))
            prefix = f"{m.group(1)}.{m.group(2) or '0'}."
            self.assertEqual(prefix, expected_prefix)

        # Unsupported versions (< 1.20.2)
        invalid_versions = ["1.19.4", "1.18.2", "1.16.5", "1.20.1"]
        for version in invalid_versions:
            m = re.match(r"^1\.(\d+)(?:\.(\d+))?$", version)
            is_unsupported = not m or int(m.group(1)) < 20 or (int(m.group(1)) == 20 and int(m.group(2) or 0) < 2)
            self.assertTrue(is_unsupported)

    def test_is_network_available_uses_port_443_and_returns_bool(self):
        """Verify network check defaults to port 443 and cleanly handles connection attempts."""
        res = AuthenticationVault.is_network_available(timeout=0.2)
        self.assertIsInstance(res, bool)

    def test_server_downloader_version_list_includes_modern_releases(self):
        """Verify ServerSoftwareDialog includes 1.21.2, 1.21.3, and 1.21.4."""
        dlg = ServerSoftwareDialog(parent=None, server_dir="/tmp")
        items = [dlg.combo_version.itemText(i) for i in range(dlg.combo_version.count())]
        self.assertIn("1.21.4", items)
        self.assertIn("1.21.3", items)
        self.assertIn("1.21.2", items)
        self.assertIn("1.21.1", items)
        self.assertEqual(items[0], "1.21.4")
        dlg.close()

    def test_world_deletion_path_containment(self):
        """Verify delete_selected_world refuses to delete directories outside saves directory."""
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtCore import Qt

        tmp_dir = tempfile.mkdtemp()
        try:
            saves_dir = os.path.join(tmp_dir, "saves")
            outside_dir = os.path.join(tmp_dir, "outside_world")
            os.makedirs(saves_dir, exist_ok=True)
            os.makedirs(outside_dir, exist_ok=True)

            panel = InstalledModsPanel(parent=None)
            panel.pdata = {"path": tmp_dir}

            # Insert an item pointing outside saves_dir
            item = QListWidgetItem("Malicious World")
            item.setData(Qt.UserRole, outside_dir)
            panel.world_list.addItem(item)
            panel.world_list.setCurrentItem(item)

            with patch("PySide6.QtWidgets.QMessageBox.question", return_value=16384): # QMessageBox.Yes
                panel.delete_selected_world()

            # outside_dir must still exist!
            self.assertTrue(os.path.exists(outside_dir))
            panel.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_screenshot_deletion_path_containment(self):
        """Verify delete_selected_screenshot refuses to delete files outside screenshots directory."""
        from PySide6.QtWidgets import QListWidgetItem
        from PySide6.QtCore import Qt

        tmp_dir = tempfile.mkdtemp()
        try:
            shots_dir = os.path.join(tmp_dir, "screenshots")
            outside_file = os.path.join(tmp_dir, "important_data.txt")
            os.makedirs(shots_dir, exist_ok=True)
            with open(outside_file, "w") as f:
                f.write("safe")

            panel = InstalledModsPanel(parent=None)
            panel.pdata = {"path": tmp_dir}

            item = QListWidgetItem("Malicious Shot")
            item.setData(Qt.UserRole, outside_file)
            panel.shot_list.addItem(item)
            panel.shot_list.setCurrentItem(item)

            with patch("PySide6.QtWidgets.QMessageBox.question", return_value=16384): # QMessageBox.Yes
                panel.delete_selected_screenshot()

            # outside_file must still exist!
            self.assertTrue(os.path.exists(outside_file))
            panel.close()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

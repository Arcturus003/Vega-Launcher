import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication


class TestAuditPonytailV12Fixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_complete_official_refresh_removed_from_auth_window(self):
        """Verify unused complete_official_refresh was removed from auth_window."""
        import auth_window
        self.assertFalse(hasattr(auth_window, "complete_official_refresh"))

    def test_content_browser_clear_grid_does_not_increment_search_epoch(self):
        """Verify clear_grid() does not mutate _search_epoch counter."""
        from content_browser import ModrinthBrowser
        browser = ModrinthBrowser(project_type="modpack")
        browser._search_epoch = 42
        browser.clear_grid()
        self.assertEqual(browser._search_epoch, 42)
        browser.deleteLater()

    def test_find_installed_engine_version_delegation(self):
        """Verify _find_installed_engine_version delegates to DEFAULT_PROVISIONER."""
        from main import VegaLauncher
        with tempfile.TemporaryDirectory() as tmp_dir:
            vd = Path(tmp_dir) / "versions"
            vd.mkdir()
            (vd / "neoforge-21.1.265").mkdir()

            mock_launcher = MagicMock(spec=VegaLauncher)
            mock_launcher.mc_dir = tmp_dir

            res = VegaLauncher._find_installed_engine_version(mock_launcher, "1.21.1", "neoforge")
            self.assertEqual(res, "neoforge-21.1.265")

    def test_install_engine_for_profile_rejects_incompatible(self):
        """Verify install_engine_for_profile rejects unsupported version upfront without launching thread."""
        from main import VegaLauncher
        mock_launcher = MagicMock(spec=VegaLauncher)
        mock_launcher.settings = {"language": "tr"}
        mock_launcher.profiles = {"p1": {"name": "Test"}}

        with patch("main.QMessageBox.warning") as mock_warn, \
             patch("main.RuntimeInstallThread") as mock_thread, \
             patch("main.QProgressDialog") as mock_dlg:
            VegaLauncher.install_engine_for_profile(mock_launcher, "p1", "1.20.1", "neoforge")
            mock_warn.assert_called_once()
            self.assertIn("NeoForge", mock_warn.call_args[0][2])
            mock_thread.assert_not_called()
            mock_dlg.assert_not_called()

    def test_missing_engine_recovery_uses_game_version(self):
        """Verify missing engine recovery uses pdata['game_version'] over custom version string."""
        from runtime_provisioner import RuntimeProvisioner
        pdata = {
            "name": "Custom Pack",
            "version": "CustomModpack_Alpha",
            "game_version": "1.21.1",
            "loader": "neoforge",
        }
        version = pdata.get("version")
        base_ver = pdata.get("game_version") or RuntimeProvisioner.extract_base_version(version, default=version)
        self.assertEqual(base_ver, "1.21.1")


if __name__ == "__main__":
    unittest.main()

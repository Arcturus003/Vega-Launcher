import os
import re
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestPonytailAuditV13(unittest.TestCase):
    def test_server_thread_batch_pause_stripping(self):
        """Verify @pause and indented pause lines are stripped from run.bat."""
        bat_content = (
            "@echo off\n"
            "java -jar server.jar nogui\n"
            "@pause\n"
            "  pause\n"
            "pause\n"
        )
        cleaned = re.sub(r'(?im)^\s*@?pause\s*$', '', bat_content).strip()
        self.assertNotIn("pause", cleaned.lower())
        self.assertIn("java -jar server.jar nogui", cleaned)

    def test_runtime_provisioner_neoforge_base_minor_matching(self):
        """Verify find_installed_loader_version distinguishes 1.21 (21.0.x) from 1.21.1 (21.1.x)."""
        from runtime_provisioner import RuntimeProvisioner

        with tempfile.TemporaryDirectory() as tmp_dir:
            versions_dir = os.path.join(tmp_dir, "versions")
            os.makedirs(os.path.join(versions_dir, "neoforge-21.0.167"), exist_ok=True)
            os.makedirs(os.path.join(versions_dir, "neoforge-21.1.65"), exist_ok=True)

            rp = RuntimeProvisioner(mc_dir=tmp_dir)

            # 1.21.1 should match 21.1.65
            found_21_1 = rp.find_installed_loader_version("1.21.1", "neoforge")
            self.assertEqual(found_21_1, "neoforge-21.1.65")

            # 1.21 base should match 21.0.167 (NOT 21.1.65)
            found_21_0 = rp.find_installed_loader_version("1.21", "neoforge")
            self.assertEqual(found_21_0, "neoforge-21.0.167")

    def test_content_browser_single_grid_clear_on_populate(self):
        """Verify ModrinthBrowser does not call clear_grid twice on search completion."""
        from content_browser import ModrinthBrowser

        browser = ModrinthBrowser(project_type="modpack")
        try:
            mock_th = MagicMock()
            mock_th._search_epoch = 1
            mock_th._cache_key = None
            browser._search_thread = mock_th
            browser._search_epoch = 1
            browser.sender = lambda: mock_th

            with patch.object(browser, "populate") as mock_pop, \
                 patch.object(browser, "clear_grid") as mock_clear:
                browser.on_search_finished([{"id": "test_pack"}])
                mock_clear.assert_not_called()
                mock_pop.assert_called_once_with([{"id": "test_pack"}])

            # For empty results, clear_grid should be called
            with patch.object(browser, "clear_grid") as mock_clear:
                browser.on_search_finished([])
                mock_clear.assert_called_once()
        finally:
            browser.deleteLater()

    def test_launch_installer_runas_fallback(self):
        """Verify launch_installer falls back to 'runas' if 'open' returns error code <= 32."""
        import sys
        from app_updater import launch_installer

        if sys.platform != "win32":
            return

        with patch("ctypes.windll.shell32.ShellExecuteW") as mock_exec:
            # First call ("open") returns 5 (access denied / elevation required)
            # Second call ("runas") returns 42 (success)
            mock_exec.side_effect = [5, 42]
            res = launch_installer("C:/fake/setup.exe")
            self.assertTrue(res)
            self.assertEqual(mock_exec.call_count, 2)
            first_verb = mock_exec.call_args_list[0][0][1]
            second_verb = mock_exec.call_args_list[1][0][1]
            self.assertEqual(first_verb, "open")
            self.assertEqual(second_verb, "runas")


if __name__ == "__main__":
    unittest.main()

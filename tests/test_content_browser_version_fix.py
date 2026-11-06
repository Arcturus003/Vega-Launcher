import unittest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
import sys

_app = QApplication.instance() or QApplication(sys.argv)

from runtime_provisioner import RuntimeProvisioner
from mod_manager import detect_profile_game_version
from content_browser import ModrinthBrowser


class TestContentBrowserVersionFix(unittest.TestCase):
    def test_runtime_provisioner_extract_neoforge_and_forge(self):
        # NeoForge semver variants
        self.assertEqual(RuntimeProvisioner.extract_base_version("neoforge-21.1.265"), "1.21.1")
        self.assertEqual(RuntimeProvisioner.extract_base_version("NeoForge 21.1"), "1.21.1")
        self.assertEqual(RuntimeProvisioner.extract_base_version("neoforge-20.4.80"), "1.20.4")
        self.assertEqual(RuntimeProvisioner.extract_base_version("neoforge-21.0.12"), "1.21")
        self.assertEqual(RuntimeProvisioner.extract_base_version("neoforge-20.2.86"), "1.20.2")

        # Standard loader variants
        self.assertEqual(RuntimeProvisioner.extract_base_version("fabric-loader-0.18.4-1.18.2"), "1.18.2")
        self.assertEqual(RuntimeProvisioner.extract_base_version("1.20.1"), "1.20.1")
        self.assertEqual(RuntimeProvisioner.extract_base_version("1.21.1-forge-52.0.1"), "1.21.1")

        # Forge without MC prefix
        self.assertEqual(RuntimeProvisioner.extract_base_version("forge-47.3.0"), "1.20.1")

    def test_detect_profile_game_version_sanitization(self):
        pdata1 = {"name": "MineColonies", "version": "neoforge-21.1.265"}
        self.assertEqual(detect_profile_game_version(pdata1), "1.21.1")

        pdata2 = {"name": "MineColonies", "game_version": "neoforge-21.1.265", "version": "neoforge-21.1.265"}
        self.assertEqual(detect_profile_game_version(pdata2), "1.21.1")

    def test_content_browser_get_active_version_resolves_clean_mc_version(self):
        browser = ModrinthBrowser("mod")
        mock_window = MagicMock()
        mock_window.get_selected_profile.return_value = (
            "test_pid",
            {"name": "MineColonies", "version": "neoforge-21.1.265", "loader": "neoforge"}
        )
        mock_window.active_profile_version = "neoforge-21.1.265"
        mock_window.active_profile_loader = "neoforge"
        browser.window = MagicMock(return_value=mock_window)

        # Combo is on "detect" by default
        active_ver = browser.get_active_version()
        self.assertEqual(active_ver, "1.21.1")
        self.assertNotEqual(active_ver, "1.265")
        self.assertNotEqual(active_ver, "neoforge-21.1.265")

        # Verify loader resolution
        self.assertEqual(browser.get_active_loader(), "neoforge")

    def test_shader_browser_ignores_loader_but_gets_version(self):
        shader_browser = ModrinthBrowser("shader")
        mock_window = MagicMock()
        mock_window.get_selected_profile.return_value = (
            "test_pid",
            {"name": "MineColonies", "version": "neoforge-21.1.265", "loader": "neoforge"}
        )
        mock_window.active_profile_version = "neoforge-21.1.265"
        shader_browser.window = MagicMock(return_value=mock_window)

        self.assertEqual(shader_browser.get_active_version(), "1.21.1")
        self.assertIsNone(shader_browser.get_active_loader())


if __name__ == "__main__":
    unittest.main()

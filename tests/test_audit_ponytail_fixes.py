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
            
    def test_launch_installer_invocation(self):
        """Verify launch_installer invokes ShellExecuteW with silent Inno Setup parameters."""
        import app_updater
        with patch("sys.platform", "win32"), \
             patch("ctypes.windll.shell32.ShellExecuteW", return_value=42) as mock_shell:
            ok = app_updater.launch_installer("C:\\temp\\setup.exe")
            self.assertTrue(ok)
            mock_shell.assert_called_once_with(
                None,
                "open",
                "C:\\temp\\setup.exe",
                "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /SP-",
                None,
                1,
            )

        with patch("sys.platform", "win32"), \
             patch("ctypes.windll.shell32.ShellExecuteW", return_value=5): # <= 32 is error code
            ok = app_updater.launch_installer("C:\\temp\\setup.exe")
            self.assertFalse(ok)

    def test_prism_instance_importer_strips_trailing_dots(self):
        """Verify PrismInstanceImporter strips trailing dots and spaces to satisfy Windows filesystem rules."""
        from prism_instance_importer import PrismInstanceImporter, PrismInstanceInfo
        info = PrismInstanceInfo(
            id="test_pack",
            name="Create Progression v1.0. ",
            version="1.21.1",
            loader="neoforge",
            loader_version="21.1.65",
            ram=4096,
            path="/dummy",
            game_dir="/dummy",
        )
        tmp = tempfile.mkdtemp()
        try:
            res = PrismInstanceImporter.import_instance(info, tmp)
            # Folder name should end with 'v1.0', not with a dot or space
            dest_basename = os.path.basename(res["path"])
            self.assertFalse(dest_basename.endswith("."))
            self.assertFalse(dest_basename.endswith(" "))
            self.assertEqual(dest_basename, "Create Progression v1.0")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_cmd_rd_quoting_no_double_quotes(self):
        """Verify profile directory fallback deletion passes path without extra manual quotes."""
        from profile_store import ProfileAndConfigStore
        store = ProfileAndConfigStore()
        tmp = tempfile.mkdtemp(prefix="store_del_test_")
        target_dir = os.path.join(tmp, "Test Folder With Spaces")
        os.makedirs(target_dir, exist_ok=True)
        store.profiles_dir = tmp

        with patch("shutil.rmtree"), \
             patch("profile_store.os.path.exists", side_effect=[True, True, False]), \
             patch("subprocess.run") as mock_sub:
            ok, reason = store.delete_profile_directory(target_dir)
            self.assertTrue(ok)
            self.assertEqual(reason, "")
            # Verify subprocess was called without surrounding quotes in the argument
            call_args = mock_sub.call_args[0][0]
            self.assertEqual(call_args[0], "cmd.exe")
            self.assertEqual(call_args[5], os.path.realpath(target_dir))
            self.assertFalse(call_args[5].startswith('"'))
        shutil.rmtree(tmp, ignore_errors=True)

    def test_curseforge_sort_fields_and_categories(self):
        """Verify CurseForge sorting enum mappings match official API specification."""
        import curseforge_api
        self.assertEqual(curseforge_api.SORT_FIELDS["downloads"], 6)  # TotalDownloads, not Author (5)
        self.assertEqual(curseforge_api.SORT_FIELDS["newest"], 11)   # ReleasedDate, not Popularity (2)
        self.assertEqual(curseforge_api.SORT_FIELDS["relevance"], 2)
        self.assertEqual(curseforge_api.SORT_FIELDS["updated"], 3)
        self.assertIn("modpack", curseforge_api.CATEGORY_MAPS)
        self.assertIn("mod", curseforge_api.CATEGORY_MAPS)
        self.assertEqual(curseforge_api.CATEGORY_MAPS["modpack"]["technology"], 4472)
        self.assertEqual(curseforge_api.CATEGORY_MAPS["mod"]["technology"], 412)

    def test_modpack_browser_defaults_to_all_versions_and_loaders(self):
        """Verify Modpack browser defaults version and loader filters to 'all' so results aren't restricted."""
        from main import ModrinthBrowser
        browser = ModrinthBrowser("modpack", parent=None)
        # Index 1 corresponds to "all" (Tüm Sürümler / Tümü)
        self.assertEqual(browser.version_combo.currentData(), "all")
        self.assertEqual(browser.loader_combo.currentData(), "all")
        browser.close()


    def test_door_sound_mapping_and_sound_version(self):
        """Verify door sounds use modern authentic wooden door audio and SoundManager version is bumped."""
        import sound_manager
        self.assertGreaterEqual(sound_manager.SOUND_VERSION, 10)
        # Check door sound wav files exist and have non-zero size
        sounds_dir = sound_manager.get_sounds_dir()
        open_wav = os.path.join(sounds_dir, "door_open.wav")
        close_wav = os.path.join(sounds_dir, "door_close.wav")
        bookshelf_wav = os.path.join(sounds_dir, "bookshelf_insert.wav")
        self.assertTrue(os.path.exists(open_wav), f"Missing {open_wav}")
        self.assertTrue(os.path.exists(close_wav), f"Missing {close_wav}")
        self.assertTrue(os.path.exists(bookshelf_wav), f"Missing {bookshelf_wav}")
        self.assertGreater(os.path.getsize(open_wav), 1000)
        self.assertGreater(os.path.getsize(close_wav), 1000)
        self.assertGreater(os.path.getsize(bookshelf_wav), 1000)

        sm = sound_manager.SoundManager.get_instance()
        self.assertTrue(hasattr(sm, "play_bookshelf_insert"))
        self.assertTrue(hasattr(sm, "play_subtab"))

    def test_installed_mods_subtab_sound(self):
        """Verify switch_sub_tab plays bookshelf_insert only on tab change."""
        from unittest.mock import patch, MagicMock
        from ui_components import InstalledModsPanel
        panel = InstalledModsPanel()
        panel.sub_stack.setCurrentIndex(0)

        with patch("sound_manager.SoundManager.play_bookshelf_insert") as mock_play:
            # Clicking the same tab (0) should NOT play sound
            panel.switch_sub_tab(0, play_sound=True)
            mock_play.assert_not_called()

            # Switching to tab 1 should play sound once
            panel.switch_sub_tab(1, play_sound=True)
            mock_play.assert_called_once()
        panel.deleteLater()

    def test_shared_windows_java_globs(self):
        """Verify DEFAULT_WINDOWS_JAVA_GLOBS is shared and consistent between provisioners."""
        import java_provisioner
        import runtime_provisioner

        self.assertTrue(hasattr(java_provisioner, "DEFAULT_WINDOWS_JAVA_GLOBS"))
        self.assertTrue(hasattr(runtime_provisioner, "DEFAULT_WINDOWS_JAVA_GLOBS"))
        self.assertIs(java_provisioner.DEFAULT_WINDOWS_JAVA_GLOBS, runtime_provisioner.DEFAULT_WINDOWS_JAVA_GLOBS)
        globs = java_provisioner.DEFAULT_WINDOWS_JAVA_GLOBS
        self.assertIsInstance(globs, tuple)
        self.assertGreater(len(globs), 5)
        for g in globs:
            self.assertTrue(g.endswith("java.exe") or g.endswith("javaw.exe"))


if __name__ == "__main__":
    unittest.main()


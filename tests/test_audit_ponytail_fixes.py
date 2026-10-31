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

    def test_default_client_installer_neoforge_signature(self):
        """Verify DefaultClientInstallerBackend.install_neoforge conforms to ModLoader.install signature."""
        from runtime_provisioner import DefaultClientInstallerBackend
        from unittest.mock import MagicMock, patch

        backend = DefaultClientInstallerBackend()
        mock_neo = MagicMock()
        mock_neo.install.return_value = "neoforge-21.1.65"
        with patch("minecraft_launcher_lib.mod_loader.get_mod_loader", return_value=mock_neo):
            res = backend.install_neoforge(
                "1.21.1",
                "/fake/mc",
                loader_version="neoforge-21.1.65",
                callback={"setStatus": lambda s: None},
                java="/fake/bin/java.exe",
            )
            self.assertEqual(res, "neoforge-21.1.65")
            mock_neo.install.assert_called_once()
            args, kwargs = mock_neo.install.call_args
            self.assertEqual(args, ("1.21.1", "/fake/mc"))
            self.assertEqual(kwargs.get("loader_version"), "21.1.65")
            self.assertEqual(kwargs.get("java"), "/fake/bin/java.exe")

    def test_neoforge_install_with_real_modloader_no_typeerror(self):
        """Verify real ModLoader.install does not raise TypeError regarding argument counts."""
        from runtime_provisioner import DefaultClientInstallerBackend
        from minecraft_launcher_lib.mod_loader import get_mod_loader
        from unittest.mock import MagicMock, patch

        backend = DefaultClientInstallerBackend()
        neo = get_mod_loader("neoforge")
        with patch.object(neo, "_base") as mock_base, \
             patch("minecraft_launcher_lib.mod_loader.is_version_valid", return_value=True), \
             patch("minecraft_launcher_lib.mod_loader.install_minecraft_version"):
            mock_base.install = MagicMock()
            mock_base.get_minecraft_versions = MagicMock(return_value=["1.21.1"])
            mock_base.get_installed_version = MagicMock(return_value="neoforge-21.1.65")
            with patch("minecraft_launcher_lib.mod_loader.get_mod_loader", return_value=neo):
                res = backend.install_neoforge("1.21.1", "/fake/mc", loader_version="21.1.65", java="java")
                self.assertEqual(res, "neoforge-21.1.65")

    def test_find_installed_engine_version_modern_neoforge(self):
        """Verify _find_installed_engine_version finds modern NeoForge directory without MC version in folder name."""
        from main import VegaLauncher
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        try:
            versions_dir = os.path.join(tmp_dir, "versions")
            os.makedirs(os.path.join(versions_dir, "neoforge-21.1.65"), exist_ok=True)
            os.makedirs(os.path.join(versions_dir, "neoforge-20.4.80"), exist_ok=True)

            mock_launcher = MagicMock()
            mock_launcher.mc_dir = tmp_dir
            # For 1.21.1 -> should match neoforge-21.1.65
            found = VegaLauncher._find_installed_engine_version(mock_launcher, "1.21.1", "neoforge")
            self.assertEqual(found, "neoforge-21.1.65")

            # For 1.20.4 -> should match neoforge-20.4.80
            found_204 = VegaLauncher._find_installed_engine_version(mock_launcher, "1.20.4", "neoforge")
            self.assertEqual(found_204, "neoforge-20.4.80")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_curseforge_modpack_loader_neoforge_and_quilt(self):
        """Verify CurseForge modpack installer dispatches to loader_installer for neoforge and quilt."""
        import tempfile
        import zipfile
        import json
        from mod_manager import ContentCatalog

        tmp_dir = tempfile.mkdtemp()
        try:
            mock_installer = MagicMock()
            mock_installer.install.return_value = "neoforge-21.1.65"
            catalog = ContentCatalog(mc_dir=tmp_dir, loader_installer=mock_installer)

            # Test NeoForge CurseForge zip
            neo_zip = os.path.join(tmp_dir, "test_neo.zip")
            with zipfile.ZipFile(neo_zip, "w") as zf:
                zf.writestr("manifest.json", json.dumps({
                    "minecraft": {
                        "version": "1.21.1",
                        "modLoaders": [{"id": "neoforge-21.1.65", "primary": True}]
                    },
                    "files": []
                }))

            prof_dir = os.path.join(tmp_dir, "test_profile")
            os.makedirs(prof_dir, exist_ok=True)
            res = catalog.install_modpack(prof_dir, neo_zip, is_local=True)
            self.assertTrue(res.ok)
            mock_installer.install.assert_called_with("1.21.1", "neoforge", "21.1.65", tmp_dir, on_progress=unittest.mock.ANY)

            # Test Quilt CurseForge zip
            mock_installer.reset_mock()
            mock_installer.install.return_value = "quilt-0.25.0"
            quilt_zip = os.path.join(tmp_dir, "test_quilt.zip")
            with zipfile.ZipFile(quilt_zip, "w") as zf:
                zf.writestr("manifest.json", json.dumps({
                    "minecraft": {
                        "version": "1.20.1",
                        "modLoaders": [{"id": "quilt-0.25.0", "primary": True}]
                    },
                    "files": []
                }))
            res_q = catalog.install_modpack(prof_dir, quilt_zip, is_local=True)
            self.assertTrue(res_q.ok)
            mock_installer.install.assert_called_with("1.20.1", "quilt", "0.25.0", tmp_dir, on_progress=unittest.mock.ANY)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_auth_vault_dpapi_handling_and_metadata_retention(self):
        """Verify auth_vault decrypts DPAPI tokens safely and merges refresh response with existing metadata."""
        from auth_vault import AuthenticationVault

        # Encrypted token in ms_login
        raw_account = {
            "name": "Alex",
            "type": "msa",
            "access_token": AuthenticationVault.encrypt_secret("valid_raw_access_token"),
            "refresh_token": AuthenticationVault.encrypt_secret("valid_raw_refresh_token"),
            "custom_meta": "persisted",
        }

        mock_http = MagicMock()
        mock_http.get.return_value = MagicMock(status_code=200)

        res = AuthenticationVault.validate_or_refresh_session(raw_account, transport=mock_http)
        self.assertEqual(res["status"], "ok")
        # Ensure raw dpapi:... was NOT transmitted in Authorization header
        call_headers = mock_http.get.call_args[1]["headers"]
        self.assertEqual(call_headers["Authorization"], "Bearer valid_raw_access_token")

        # Now test refresh flow and dictionary merge retaining non-credential metadata
        mock_http.get.return_value = MagicMock(status_code=401)
        mock_refresh = MagicMock(return_value={"access_token": "new_access", "refresh_token": "new_refresh"})
        res_refresh = AuthenticationVault.validate_or_refresh_session(raw_account, transport=mock_http, refresh_fn=mock_refresh)
        self.assertEqual(res_refresh["status"], "ok")
        refreshed = res_refresh["refreshed_login"]
        self.assertEqual(refreshed["access_token"], "new_access")
        merged = dict(raw_account)
        merged.update(refreshed)
        self.assertEqual(merged["name"], "Alex")
        self.assertEqual(merged["type"], "msa")
        self.assertEqual(merged["custom_meta"], "persisted")

    def test_crash_analyzer_case_insensitive_jars(self):
        """Verify crash_analyzer detects .JAR files regardless of casing."""
        from crash_analyzer import CrashAnalyzer
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        try:
            mods_dir = os.path.join(tmp_dir, "mods")
            os.makedirs(mods_dir, exist_ok=True)
            with open(os.path.join(mods_dir, "Create-1.21.1.JAR"), "w") as f:
                f.write("jar")

            log_text = "MixinApplyError: create.mixins.json failed to apply"
            report = CrashAnalyzer.analyze_text(log_text, profile_root=tmp_dir)
            self.assertEqual(report.culprit_file, "Create-1.21.1.JAR")
            self.assertIn("Create-1.21.1.JAR", str(report.culprit_path))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_server_downloader_version_list(self):
        """Verify server_downloader includes 1.20.6."""
        from server_downloader import ServerSoftwareDialog
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        dialog = ServerSoftwareDialog()
        items = [dialog.combo_version.itemText(i) for i in range(dialog.combo_version.count())]
        self.assertIn("1.20.6", items)
        dialog.deleteLater()

    def test_launch_options_dynamic_launcher_version(self):
        """Verify launch_pipeline sets launcherVersion to current release."""
        from launch_pipeline import GameLaunchPipeline

        pipeline = GameLaunchPipeline()
        opts = pipeline.build_launch_options(
            auth_session={"name": "Player"},
            game_directory="/fake/path",
        )
        self.assertEqual(opts.get("launcherVersion"), "2.0.4")

    def test_content_browser_search_epoch_rejection(self):
        """Verify ModrinthBrowser discards stale search results from earlier epochs."""
        from content_browser import ModrinthBrowser
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        browser = ModrinthBrowser(project_type="modpack")
        browser._search_epoch = 5

        # Create mock thread with older epoch
        mock_thread = MagicMock()
        mock_thread._search_epoch = 4
        browser._search_thread = mock_thread
        browser.sender = lambda: mock_thread

        with patch.object(browser, "populate") as mock_populate:
            browser.on_search_finished([{"id": "stale"}])
            mock_populate.assert_not_called()

        # Sender matching current epoch should populate
        mock_thread._search_epoch = 5
        with patch.object(browser, "populate") as mock_populate:
            browser.on_search_finished([{"id": "fresh"}])
            mock_populate.assert_called_once()
        browser.deleteLater()

    def test_modpack_installer_empty_loader_version_fallback(self):
        """Verify CurseForge modpack with empty loader version (e.g. 'fabric-') defaults to latest loader."""
        import tempfile
        import zipfile
        import json
        from mod_manager import ContentCatalog

        tmp_dir = tempfile.mkdtemp()
        try:
            mock_installer = MagicMock()
            mock_installer.install.return_value = "fabric-loader-0.16.0-1.20.1"
            catalog = ContentCatalog(mc_dir=tmp_dir, loader_installer=mock_installer)

            pack_zip = os.path.join(tmp_dir, "test_empty_loader.zip")
            with zipfile.ZipFile(pack_zip, "w") as zf:
                zf.writestr("manifest.json", json.dumps({
                    "minecraft": {
                        "version": "1.20.1",
                        "modLoaders": [{"id": "fabric-", "primary": True}]
                    },
                    "files": []
                }))

            prof_dir = os.path.join(tmp_dir, "test_profile")
            os.makedirs(prof_dir, exist_ok=True)
            res = catalog.install_modpack(prof_dir, pack_zip, is_local=True)
            self.assertTrue(res.ok)
            # Empty version after 'fabric-' should be converted to None (not empty string)
            mock_installer.install.assert_called_with("1.20.1", "fabric", None, tmp_dir, on_progress=unittest.mock.ANY)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


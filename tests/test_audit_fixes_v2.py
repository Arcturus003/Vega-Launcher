import unittest
import os
import sys
import tempfile
import zipfile
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QPixmap

app = QApplication.instance()
if not app:
    app = QApplication([])

import card_widget
from card_widget import (
    CardWidget, _ICON_CACHE, _PIXMAP_CACHE, _cache_icon,
    _PENDING_ICON_QUEUE, _IN_FLIGHT_REQUESTS, ImageLoaderThread
)
import auth_window
from auth_window import protect_token, unprotect_token, LoginWorkerThread, MicrosoftLoginDialog
from ui_components import WorldBackupThread
from main import TokenValidationThread, AddProfileDialog, VegaLauncher
from server_downloader import ServerSoftwareDialog
from mod_manager import ModrinthAPI


class TestAuditFixesV2(unittest.TestCase):
    def tearDown(self):
        app.processEvents()

    # 1. Dungeons download safety check & case handling
    def test_dungeons_handle_download_validation(self):
        launcher = MagicMock(spec=VegaLauncher)
        launcher.settings = {"language": "en"}

        # 1a. Invalid extension (.exe)
        download_bad = MagicMock()
        download_bad.suggestedFileName.return_value = "trojan.exe"
        with patch("main.os.path.exists", return_value=True), patch("main.QMessageBox.warning") as mock_warn:
            VegaLauncher.handle_dungeons_download(launcher, download_bad)
            download_bad.cancel.assert_called_once()
            download_bad.accept.assert_not_called()
            mock_warn.assert_called_once()

        # 1b. None / empty filename
        download_none = MagicMock()
        download_none.suggestedFileName.return_value = None
        with patch("main.os.path.exists", return_value=True), patch("main.QMessageBox.warning"):
            VegaLauncher.handle_dungeons_download(launcher, download_none)
            download_none.cancel.assert_called_once()
            download_none.accept.assert_not_called()

        # 1c. Allowed uppercase .PAK
        download_pak = MagicMock()
        download_pak.suggestedFileName.return_value = "cool_skin.PAK"
        with patch("main.os.path.exists", return_value=True), \
             patch("main.CustomProgressOverlay"), \
             patch("main.os.makedirs"):
            VegaLauncher.handle_dungeons_download(launcher, download_pak)
            download_pak.accept.assert_called_once()
            download_pak.cancel.assert_not_called()

        # 1d. Allowed uppercase .ZIP
        download_zip = MagicMock()
        download_zip.suggestedFileName.return_value = "mod_pack.ZIP"
        with patch("main.os.path.exists", return_value=True), \
             patch("main.CustomProgressOverlay"), \
             patch("main.os.makedirs"):
            VegaLauncher.handle_dungeons_download(launcher, download_zip)
            download_zip.accept.assert_called_once()
            download_zip.cancel.assert_not_called()

    # 2. DPAPI Token Protection, Idempotency & Roundtrip
    def test_dpapi_token_protection_and_roundtrip(self):
        raw_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_ms_token_payload"
        protected = protect_token(raw_token)

        if sys.platform == "win32":
            self.assertTrue(protected.startswith("dpapi:"), "Protected token on Windows must have dpapi: prefix")
            # Verify IDEMPOTENCY: protecting an already protected token does NOT double-encrypt
            protected_again = protect_token(protected)
            self.assertEqual(protected_again, protected, "protect_token must be idempotent")

        unprotected = unprotect_token(protected)
        self.assertEqual(unprotected, raw_token, "Decrypted token must match original token")

        # Test legacy plain token backward compatibility
        legacy_token = "old_unencrypted_token_12345"
        self.assertEqual(unprotect_token(legacy_token), legacy_token)

        # Test empty and None handling
        self.assertEqual(protect_token(""), "")
        self.assertEqual(protect_token(None), "")
        self.assertEqual(unprotect_token(""), "")
        self.assertEqual(unprotect_token(None), "")

    # 3. Non-blocking OAuth Worker Threads
    def test_login_worker_thread_success_and_error(self):
        thread_ok = LoginWorkerThread("client_id", "redirect_uri", "code", "verifier")
        results_ok = []
        thread_ok.finished_login.connect(lambda s, d, e: results_ok.append((s, d, e)))
        with patch("minecraft_launcher_lib.microsoft_account.complete_login", return_value={"name": "Player"}):
            thread_ok.run()
        self.assertEqual(len(results_ok), 1)
        self.assertTrue(results_ok[0][0])
        self.assertEqual(results_ok[0][1], {"name": "Player"})

        thread_err = LoginWorkerThread("client_id", "redirect_uri", "code", "verifier")
        results_err = []
        thread_err.finished_login.connect(lambda s, d, e: results_err.append((s, d, e)))
        with patch("minecraft_launcher_lib.microsoft_account.complete_login", side_effect=Exception("OAuth error")):
            thread_err.run()
        self.assertEqual(len(results_err), 1)
        self.assertFalse(results_err[0][0])
        self.assertIn("OAuth error", results_err[0][2])

    def test_token_validation_thread_branches(self):
        # 3a. Valid token
        thread = TokenValidationThread({"access_token": "valid_token"})
        results = []
        thread.validation_finished.connect(lambda res: results.append(res))
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            thread.run()
        self.assertEqual(results[0].get("status"), "ok")

        # 3b. Network error during profile check
        thread = TokenValidationThread({"access_token": "some_token"})
        results = []
        thread.validation_finished.connect(lambda res: results.append(res))
        with patch("requests.get", side_effect=Exception("Connection timed out")):
            thread.run()
        self.assertEqual(results[0].get("status"), "network_error")

        # 3c. 401 with successful token refresh
        thread = TokenValidationThread({"access_token": "expired", "refresh_token": "valid_ref"})
        results = []
        thread.validation_finished.connect(lambda res: results.append(res))
        with patch("requests.get") as mock_get, \
             patch("minecraft_launcher_lib.microsoft_account.complete_refresh", return_value={"access_token": "new_tok"}):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_get.return_value = mock_resp
            thread.run()
        self.assertEqual(results[0].get("status"), "ok")
        self.assertEqual(results[0].get("refreshed_login"), {"access_token": "new_tok"})

        # 3d. 401 with network error during token refresh
        thread = TokenValidationThread({"access_token": "expired", "refresh_token": "valid_ref"})
        results = []
        thread.validation_finished.connect(lambda res: results.append(res))
        with patch("requests.get") as mock_get, \
             patch("minecraft_launcher_lib.microsoft_account.complete_refresh", side_effect=OSError("Network unreachable")):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_get.return_value = mock_resp
            thread.run()
        self.assertEqual(results[0].get("status"), "network_error_abort")

        # 3e. 401 with expired/revoked refresh token
        thread = TokenValidationThread({"access_token": "expired", "refresh_token": "revoked"})
        results = []
        thread.validation_finished.connect(lambda res: results.append(res))
        with patch("requests.get") as mock_get, \
             patch("minecraft_launcher_lib.microsoft_account.complete_refresh", return_value={}):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_get.return_value = mock_resp
            thread.run()
        self.assertEqual(results[0].get("status"), "need_login")

    # 4. DetailPanel Thread Pruning Order
    def test_detail_panel_thread_pruning_order(self):
        from main import DetailPanel
        panel = DetailPanel()
        
        old_mock = MagicMock()
        old_mock.isRunning.return_value = False
        panel._api_threads = [old_mock]

        data = {"project_id": "test_proj"}
        with patch("content_browser.ProjectDetailsThread") as mock_thread_cls:
            new_thread = MagicMock()
            new_thread.isRunning.return_value = False
            mock_thread_cls.return_value = new_thread
            panel.update_info(data)

        self.assertIn(new_thread, panel._api_threads)
        self.assertNotIn(old_mock, panel._api_threads)

    # 5. Asynchronous World Save Backup Thread
    def test_world_backup_thread_execution_and_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            world_dir = os.path.join(temp_dir, "MyWorld")
            os.makedirs(world_dir)
            with open(os.path.join(world_dir, "level.dat"), "w") as f:
                f.write("dummy world data")

            base_zip = os.path.join(temp_dir, "MyWorld_backup")
            thread = WorldBackupThread(base_zip, world_dir)
            
            backup_results = []
            thread.backup_finished.connect(lambda success, path: backup_results.append((success, path)))
            thread.run()

            self.assertEqual(len(backup_results), 1)
            success, zip_path = backup_results[0]
            self.assertTrue(success)
            self.assertTrue(os.path.exists(zip_path))

            with zipfile.ZipFile(zip_path, "r") as zf:
                self.assertIn("level.dat", zf.namelist())

        # Test error handling
        bad_thread = WorldBackupThread("/invalid/path/backup", "/nonexistent/world/dir")
        err_results = []
        bad_thread.backup_finished.connect(lambda success, path: err_results.append((success, path)))
        bad_thread.run()
        self.assertEqual(len(err_results), 1)
        self.assertFalse(err_results[0][0])

    # 6. & 10. Card Icon Cache, Pixmap Cache & Throttle Queue
    def test_icon_cache_and_eviction(self):
        _ICON_CACHE.clear()
        _PIXMAP_CACHE.clear()
        dummy_data = b"image_data_123"
        _cache_icon("http://example.com/icon1.png", dummy_data)
        self.assertIn("http://example.com/icon1.png", _ICON_CACHE)
        self.assertEqual(_ICON_CACHE["http://example.com/icon1.png"], dummy_data)

        # Test cache eviction
        with patch.object(card_widget, "_MAX_CACHE_SIZE", 2):
            _cache_icon("http://example.com/icon2.png", b"data2")
            _cache_icon("http://example.com/icon3.png", b"data3")
            self.assertNotIn("http://example.com/icon1.png", _ICON_CACHE)
            self.assertIn("http://example.com/icon3.png", _ICON_CACHE)

    def test_cleanup_all_threads_clears_queue_and_requests(self):
        _PENDING_ICON_QUEUE.append((MagicMock(), "http://example.com/test.png"))
        _IN_FLIGHT_REQUESTS["http://example.com/test.png"] = [MagicMock()]
        self.assertTrue(len(_PENDING_ICON_QUEUE) > 0)
        self.assertTrue(len(_IN_FLIGHT_REQUESTS) > 0)
        CardWidget.cleanup_all_threads()
        self.assertEqual(len(_PENDING_ICON_QUEUE), 0)
        self.assertEqual(len(_IN_FLIGHT_REQUESTS), 0)

    # 7. Elimination of duplicate integrity hashing
    def test_no_verify_integrity_in_do_launch(self):
        import inspect
        source = inspect.getsource(VegaLauncher._do_launch)
        self.assertNotIn("verify_integrity", source, "verify_integrity should not be called in _do_launch")

    # 8. Modrinth User-Agent Headers in server_downloader.py
    def test_server_downloader_uses_modrinth_headers(self):
        import inspect
        import server_downloader
        source = inspect.getsource(server_downloader.ServerDownloadThread.run)
        self.assertIn("headers=ModrinthAPI.HEADERS", source)
        self.assertNotIn("User-Agent': 'Mozilla/5.0'", source)

    # 9. Localization in Modal Dialogs (AddProfileDialog, ServerSoftwareDialog, MicrosoftLoginDialog)
    def test_add_profile_dialog_localization(self):
        parent_en = QWidget()
        parent_en.settings = {"language": "en"}
        dlg_en = AddProfileDialog(parent=parent_en)
        self.assertEqual(dlg_en.windowTitle(), "Add New Profile")
        self.assertEqual(dlg_en.save_btn.text(), "Save")
        self.assertEqual(dlg_en.cancel_btn.text(), "Cancel")

        parent_tr = QWidget()
        parent_tr.settings = {"language": "tr"}
        dlg_tr = AddProfileDialog(parent=parent_tr)
        self.assertEqual(dlg_tr.windowTitle(), "Yeni Profil Ekle")
        self.assertEqual(dlg_tr.save_btn.text(), "Kaydet")
        self.assertEqual(dlg_tr.cancel_btn.text(), "İptal")

    def test_server_software_dialog_localization(self):
        parent_en = QWidget()
        parent_en.settings = {"language": "en"}
        dlg_en = ServerSoftwareDialog(parent=parent_en)
        self.assertEqual(dlg_en.windowTitle(), "Change Server Software / Engine")
        self.assertEqual(dlg_en.btn_install.text(), "Install Software")

        parent_tr = QWidget()
        parent_tr.settings = {"language": "tr"}
        dlg_tr = ServerSoftwareDialog(parent=parent_tr)
        self.assertEqual(dlg_tr.windowTitle(), "Yazılım / Motor Değiştir")
        self.assertEqual(dlg_tr.btn_install.text(), "Yazılımı Kur")

    def test_microsoft_login_dialog_localization_and_cleanup(self):
        parent_en = QWidget()
        parent_en.settings = {"language": "en"}
        with patch("minecraft_launcher_lib.microsoft_account.get_secure_login_data", return_value=("http://login", "state", "verif")):
            dlg_en = MicrosoftLoginDialog(parent=parent_en)
            self.assertEqual(dlg_en.windowTitle(), "Sign in with Microsoft")
            self.assertIn("Completing login", dlg_en.loading_label.text())

            # Verify cleanup on reject
            mock_worker = MagicMock()
            mock_worker.isRunning.return_value = True
            dlg_en._login_worker = mock_worker
            dlg_en.reject()
            mock_worker.quit.assert_called_once()
            mock_worker.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()

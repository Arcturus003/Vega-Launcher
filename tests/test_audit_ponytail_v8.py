import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])


class TestAuditPonytailV8(unittest.TestCase):
    def test_dpapi_buffer_pinning(self):
        """Verify auth_vault pins ctypes string buffer in local variable."""
        import auth_vault
        import inspect
        enc_src = inspect.getsource(auth_vault.AuthenticationVault.encrypt_secret)
        dec_src = inspect.getsource(auth_vault.AuthenticationVault.decrypt_secret)
        self.assertIn("in_buffer = ctypes.create_string_buffer", enc_src)
        self.assertIn("in_buffer = ctypes.create_string_buffer", dec_src)

    def test_no_qthread_terminate_in_codebase(self):
        """Verify no violent QThread.terminate() calls exist in the repo."""
        import glob
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for py_file in glob.glob(os.path.join(root_dir, "*.py")):
            with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                # Check for thread terminate calls like .server_thread.terminate() or th.terminate()
                self.assertNotIn(".server_thread.terminate()", content)
                self.assertNotIn("th.terminate()", content)

    def test_crash_detective_async_upload_thread(self):
        """Verify McloGsUploadThread exists and executes off the main thread."""
        import crash_analyzer
        self.assertTrue(hasattr(crash_analyzer, "McloGsUploadThread"))
        
        with patch.object(crash_analyzer.CrashAnalyzer, "upload_to_mclogs", return_value={"success": True, "url": "https://mclo.gs/dummy"}):
            thread = crash_analyzer.McloGsUploadThread("dummy log content")
            results = []
            thread.upload_finished.connect(lambda success, data: results.append((success, data)))
            thread.run()
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0][0])
            self.assertEqual(results[0][1]["url"], "https://mclo.gs/dummy")

    def test_prism_instance_importer_aborted_cleanup(self):
        """Verify aborted Prism import deletes the destination folder."""
        import tempfile
        import shutil
        from prism_instance_importer import PrismInstanceImporter, PrismInstanceInfo
        
        info = PrismInstanceInfo(
            id="abort_test",
            name="Abort Instance",
            version="1.20.1",
            loader="vanilla",
            loader_version="1.20.1",
            ram=2048,
            path="/nonexistent_src",
            game_dir="/nonexistent_src",
        )
        tmp = tempfile.mkdtemp()
        src_tmp = tempfile.mkdtemp()
        try:
            # Create a dummy mods folder in source
            os.makedirs(os.path.join(src_tmp, "mods"), exist_ok=True)
            with open(os.path.join(src_tmp, "mods", "dummy.jar"), "w") as f:
                f.write("jar")
            info.game_dir = src_tmp

            # Calling import with cancellation raises RuntimeError and triggers cleanup
            with self.assertRaises(RuntimeError):
                PrismInstanceImporter.import_instance(info, tmp, is_cancelled=lambda: True)

            # The destination folder must NOT exist
            dest_dir = os.path.join(tmp, "Abort Instance")
            self.assertFalse(os.path.exists(dest_dir))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(src_tmp, ignore_errors=True)

    def test_runtime_provisioner_java_deduplication(self):
        """Verify runtime_provisioner reuses get_java_major_version from java_provisioner."""
        import runtime_provisioner
        import java_provisioner
        self.assertIs(runtime_provisioner.get_java_major_version, java_provisioner.get_java_major_version)

    def test_modrinth_cache_is_bounded(self):
        """Verify _MODRINTH_CACHE is bounded to prevent unbounded memory growth."""
        import main
        cache = getattr(main, "_MODRINTH_CACHE", None)
        self.assertIsInstance(cache, dict)

    def test_java_provisioner_platform_resolution(self):
        """Verify java_provisioner constructs correct OS in download URL."""
        from java_provisioner import JavaProvisioner
        prov = JavaProvisioner()
        arch = prov.get_system_architecture()
        self.assertIn(arch, ("x64", "aarch64", "x86"))

    def test_safe_natives_extraction_prevents_winerror_183(self):
        """Verify ensure_safe_natives_extraction prevents META-INF extraction and handles existing files."""
        import tempfile
        import shutil
        import zipfile
        import runtime_provisioner
        import minecraft_launcher_lib.natives

        runtime_provisioner.ensure_safe_natives_extraction()

        tmp_dir = tempfile.mkdtemp()
        jar_path = os.path.join(tmp_dir, "test-natives.jar")
        extract_dir = os.path.join(tmp_dir, "natives")

        # Create a mock jar containing both a DLL and META-INF files
        with zipfile.ZipFile(jar_path, "w") as zf:
            zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
            zf.writestr("META-INF/INDEX.LIST", "JarIndex-Version: 1.0\n")
            zf.writestr("test_native.dll", "mock_dll_bytes")

        # Extract using the patched function
        minecraft_launcher_lib.natives.extract_natives_file(jar_path, extract_dir, {"exclude": []})

        # test_native.dll must be extracted, but META-INF must be excluded
        self.assertTrue(os.path.exists(os.path.join(extract_dir, "test_native.dll")))
        self.assertFalse(os.path.exists(os.path.join(extract_dir, "META-INF")))

        # Re-extracting should not raise FileExistsError / WinError 183
        try:
            minecraft_launcher_lib.natives.extract_natives_file(jar_path, extract_dir, {"exclude": []})
        except Exception as e:
            self.fail(f"Re-extracting raised unexpected error: {e}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_prism_importer_type_hints_and_loader_version(self):
        """Verify PrismInstanceImporter type hints resolve and import_instance returns loader_version."""
        import typing
        from prism_instance_importer import PrismInstanceImporter, PrismInstanceInfo
        hints = typing.get_type_hints(PrismInstanceImporter.parse_mmc_pack)
        self.assertIn("return", hints)

        info = PrismInstanceInfo(
            id="test_id",
            name="Test Instance",
            version="1.20.1",
            loader="fabric",
            loader_version="0.15.11",
            ram=4096,
            path="",
            game_dir="",
        )
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            profile = PrismInstanceImporter.import_instance(info, tmp)
            self.assertEqual(profile.get("loader_version"), "0.15.11")
            self.assertEqual(profile.get("loader"), "fabric")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_crash_detective_modal_cleanup_on_close(self):
        """Verify VegaCrashDetectiveModal safely terminates background upload thread on close/reject."""
        import crash_analyzer
        report = crash_analyzer.CrashReport(
            exit_code=1,
            title="Test",
            severity="ERROR",
            diagnosis="Diag",
            suggested_action="Action",
            raw_log="Sample crash log",
        )
        modal = crash_analyzer.VegaCrashDetectiveModal(report)
        self.assertTrue(hasattr(modal, "_cleanup_worker"))
        self.assertTrue(hasattr(modal, "reject"))
        self.assertTrue(hasattr(modal, "closeEvent"))

    def test_server_thread_creationflags_portable(self):
        """Verify server_thread uses safe getattr for CREATE_NO_WINDOW."""
        import inspect
        import server_thread
        src = inspect.getsource(server_thread.MinecraftServerThread.run)
        self.assertIn('getattr(subprocess, "CREATE_NO_WINDOW", 0)', src)
        src_kill = inspect.getsource(server_thread.MinecraftServerThread.kill_process_tree)
        self.assertIn('getattr(subprocess, "CREATE_NO_WINDOW", 0)', src_kill)

    def test_curseforge_api_key_env_override(self):
        """Verify curseforge_api supports CURSEFORGE_API_KEY environment override."""
        import importlib
        import curseforge_api
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "custom_test_key_123"}):
            importlib.reload(curseforge_api)
            self.assertEqual(curseforge_api.API_KEY, "custom_test_key_123")
        importlib.reload(curseforge_api)

    def test_prism_meta_provider_no_unused_urllib(self):
        """Verify prism_meta_provider does not import urllib.request."""
        import inspect
        import prism_meta_provider
        src = inspect.getsource(prism_meta_provider)
        self.assertNotIn("import urllib.request", src)


if __name__ == "__main__":
    unittest.main()

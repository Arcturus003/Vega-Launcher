import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from runtime_provisioner import (
    DefaultClientInstallerBackend,
    RuntimeInstallThread,
    RuntimeProvisioner,
    RuntimeSpec,
)


class FakeClientInstallerBackend:
    """Mock backend satisfying the installer seam for testing."""
    def __init__(self):
        self.calls = []

    def install_vanilla(self, version_id, mc_dir, callback=None):
        self.calls.append(("vanilla", version_id, mc_dir))
        if callback and "setProgress" in callback:
            if "setMax" in callback:
                callback["setMax"](100)
            callback["setProgress"](50)
            callback["setProgress"](100)

    def install_fabric(self, mc_version, mc_dir, loader_version=None, callback=None):
        self.calls.append(("fabric", mc_version, mc_dir, loader_version))
        return f"fabric-loader-{loader_version or '0.15.7'}-{mc_version}"

    def install_quilt(self, mc_version, mc_dir, loader_version=None, callback=None):
        self.calls.append(("quilt", mc_version, mc_dir, loader_version))
        return f"quilt-loader-{loader_version or '0.25.0'}-{mc_version}"

    def install_forge(self, mc_version, mc_dir, forge_version=None, callback=None):
        self.calls.append(("forge", mc_version, mc_dir, forge_version))
        return f"{mc_version}-forge-{forge_version or '47.2.0'}"

    def install_neoforge(self, mc_version, mc_dir, loader_version=None, callback=None):
        self.calls.append(("neoforge", mc_version, mc_dir, loader_version))
        return f"neoforge-{loader_version or '20.4.80'}-{mc_version}"


class TestRuntimeProvisionerModule(unittest.TestCase):
    def test_runtime_spec_properties(self):
        spec = RuntimeSpec(mc_version="1.20.1", loader=" Fabric ", loader_version="0.15.7")
        self.assertEqual(spec.mc_version, "1.20.1")
        self.assertEqual(spec.loader, " Fabric ")
        self.assertEqual(spec.normalized_loader, "fabric")
        self.assertEqual(spec.loader_version, "0.15.7")
        self.assertFalse(spec.is_server)

    def test_extract_base_version(self):
        self.assertEqual(RuntimeProvisioner.extract_base_version("1.20.1"), "1.20.1")
        self.assertEqual(RuntimeProvisioner.extract_base_version("fabric-loader-0.15.7-1.20.1"), "1.20.1")
        self.assertEqual(RuntimeProvisioner.extract_base_version("1.19.4-forge-45.1.0"), "1.19.4")
        self.assertEqual(RuntimeProvisioner.extract_base_version("1.16.5"), "1.16.5")
        self.assertEqual(RuntimeProvisioner.extract_base_version(None), "1.20.1")
        self.assertIsNone(RuntimeProvisioner.extract_base_version(None, default=None))
        self.assertIsNone(RuntimeProvisioner.extract_base_version("no_version_here", default=None))

    def test_detect_client_runtime_explicit(self):
        spec = RuntimeProvisioner.detect_client_runtime({"loader": "fabric", "version": "1.20.1"})
        self.assertEqual(spec.loader, "fabric")
        self.assertEqual(spec.mc_version, "1.20.1")

        spec_neo = RuntimeProvisioner.detect_client_runtime({"loader": "neoforge", "game_version": "1.20.4"})
        self.assertEqual(spec_neo.loader, "neoforge")
        self.assertEqual(spec_neo.mc_version, "1.20.4")

    def test_detect_client_runtime_inferred(self):
        self.assertEqual(
            RuntimeProvisioner.detect_client_runtime({"version": "fabric-loader-0.15.7-1.20.1"}).loader,
            "fabric"
        )
        self.assertEqual(
            RuntimeProvisioner.detect_client_runtime({"version": "quilt-loader-1.20.1"}).loader,
            "quilt"
        )
        self.assertEqual(
            RuntimeProvisioner.detect_client_runtime({"version": "1.20.1-forge-47.2.0"}).loader,
            "forge"
        )
        self.assertEqual(
            RuntimeProvisioner.detect_client_runtime({"version": "1.20.4-neoforge-20.4.80"}).loader,
            "neoforge"
        )
        self.assertEqual(
            RuntimeProvisioner.detect_client_runtime({"version": "1.20.1"}).loader,
            "vanilla"
        )
        self.assertEqual(
            RuntimeProvisioner.detect_client_runtime({}).loader,
            "vanilla"
        )
        self.assertEqual(
            RuntimeProvisioner.detect_client_runtime(None).loader,
            "vanilla"
        )

    def test_detect_client_runtime_mods_voting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mods_dir = os.path.join(temp_dir, "mods")
            os.makedirs(mods_dir, exist_ok=True)
            with open(os.path.join(mods_dir, "sodium-fabric-1.20.1.jar"), "w") as f:
                f.write("jar")
            with open(os.path.join(mods_dir, "iris-fabric-1.20.1.jar"), "w") as f:
                f.write("jar")
            with open(os.path.join(mods_dir, "jei-forge-1.20.1.jar"), "w") as f:
                f.write("jar")

            spec = RuntimeProvisioner.detect_client_runtime({"version": "1.20.1", "path": temp_dir})
            self.assertEqual(spec.loader, "fabric")

    def test_detect_server_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            # Purpur jar
            with open(os.path.join(temp_dir, "purpur-1.20.1-2100.jar"), "w") as f:
                f.write("jar")
            spec = RuntimeProvisioner.detect_server_runtime(temp_dir)
            self.assertEqual(spec.loader, "purpur")
            self.assertEqual(spec.mc_version, "1.20.1")
            self.assertTrue(spec.is_server)

        with tempfile.TemporaryDirectory() as temp_dir:
            # Libraries detection for Forge
            forge_lib = os.path.join(temp_dir, "libraries", "net", "minecraftforge")
            os.makedirs(forge_lib, exist_ok=True)
            spec = RuntimeProvisioner.detect_server_runtime(temp_dir)
            self.assertEqual(spec.loader, "forge")
            self.assertTrue(spec.is_server)

        # Nonexistent dir
        spec_empty = RuntimeProvisioner.detect_server_runtime("/nonexistent/dir")
        self.assertEqual(spec_empty.loader, "purpur")
        self.assertEqual(spec_empty.mc_version, "1.20.1")

    def test_install_client_runtime_all_loaders(self):
        backend = FakeClientInstallerBackend()
        provisioner = RuntimeProvisioner(installer_backend=backend, mc_dir="/mock/minecraft")

        progress_calls = []
        def _on_prog(cur, tot, msg):
            progress_calls.append((cur, tot, msg))

        # Vanilla
        res_v = provisioner.install_client_runtime(
            RuntimeSpec(mc_version="1.20.1", loader="vanilla"),
            on_progress=_on_prog,
        )
        self.assertEqual(res_v, "1.20.1")
        self.assertEqual(backend.calls[-1], ("vanilla", "1.20.1", "/mock/minecraft"))

        # Fabric
        res_fab = provisioner.install_client_runtime(
            RuntimeSpec(mc_version="1.20.1", loader="fabric", loader_version="0.15.7"),
            on_progress=_on_prog,
        )
        self.assertEqual(res_fab, "fabric-loader-0.15.7-1.20.1")
        self.assertEqual(backend.calls[-1], ("fabric", "1.20.1", "/mock/minecraft", "0.15.7"))

        # Quilt
        res_q = provisioner.install_client_runtime(
            RuntimeSpec(mc_version="1.20.1", loader="quilt", loader_version="0.25.0"),
            on_progress=_on_prog,
        )
        self.assertEqual(res_q, "quilt-loader-0.25.0-1.20.1")
        self.assertEqual(backend.calls[-1], ("quilt", "1.20.1", "/mock/minecraft", "0.25.0"))

        # Forge
        res_fg = provisioner.install_client_runtime(
            RuntimeSpec(mc_version="1.20.1", loader="forge", loader_version="47.2.0"),
            on_progress=_on_prog,
        )
        self.assertEqual(res_fg, "1.20.1-forge-47.2.0")
        self.assertEqual(backend.calls[-1], ("forge", "1.20.1", "/mock/minecraft", "47.2.0"))

        # NeoForge
        res_neo = provisioner.install_client_runtime(
            RuntimeSpec(mc_version="1.20.4", loader="neoforge", loader_version="20.4.80"),
            on_progress=_on_prog,
        )
        self.assertEqual(res_neo, "neoforge-20.4.80-1.20.4")
        self.assertEqual(backend.calls[-1], ("neoforge", "1.20.4", "/mock/minecraft", "20.4.80"))

        # Verify progress messages were received
        self.assertTrue(len(progress_calls) > 0)

    def test_install_client_runtime_cancellation(self):
        backend = FakeClientInstallerBackend()
        provisioner = RuntimeProvisioner(installer_backend=backend, mc_dir="/mock/minecraft")

        with self.assertRaises(Exception) as ctx:
            provisioner.install_client_runtime(
                RuntimeSpec(mc_version="1.20.1", loader="vanilla"),
                is_cancelled=lambda: True,
            )
        self.assertIn("iptal edildi", str(ctx.exception))

    def test_provision_server_runtime_purpur_and_cancellation(self):
        provisioner = RuntimeProvisioner()

        class DummyResponse:
            def __init__(self, data=b"mock-server-binary-content"):
                self.data = io.BytesIO(data)
                self.headers = {"Content-Length": str(len(data))}

            def getheader(self, name, default=None):
                return self.headers.get(name, default)

            def read(self, chunk_size=-1):
                return self.data.read(chunk_size)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            server_jar = os.path.join(temp_dir, "server.jar")
            logs = []
            progress = []

            with patch("urllib.request.urlopen", return_value=DummyResponse(b"purpur-data")):
                out_path = provisioner.provision_server_runtime(
                    software="purpur",
                    version="1.20.1",
                    target_path=server_jar,
                    on_progress=progress.append,
                    on_log=logs.append,
                )
                self.assertEqual(str(out_path), server_jar)
                self.assertTrue(os.path.exists(server_jar))
                with open(server_jar, "rb") as f:
                    self.assertEqual(f.read(), b"purpur-data")
                self.assertTrue(len(progress) > 0)
                self.assertIn(100, progress)

            # Test cancellation
            with patch("urllib.request.urlopen", return_value=DummyResponse(b"data")):
                with self.assertRaises(Exception) as ctx:
                    provisioner.provision_server_runtime(
                        software="purpur",
                        version="1.20.1",
                        target_path=server_jar,
                        is_cancelled=lambda: True,
                    )
                self.assertIn("iptal edildi", str(ctx.exception))

    def test_runtime_install_thread_signals(self):
        backend = FakeClientInstallerBackend()
        spec = RuntimeSpec(mc_version="1.20.1", loader="fabric", loader_version="0.15.7")
        provisioner = RuntimeProvisioner(installer_backend=backend, mc_dir="/mock/minecraft")

        thread = RuntimeInstallThread(
            spec=spec,
            mc_dir="/mock/minecraft",
            provisioner=provisioner,
        )

        progress_updates = []
        progress_vals = []
        finished_results = []

        thread.progress_update.connect(lambda msg: progress_updates.append(msg))
        thread.progress_val.connect(lambda val: progress_vals.append(val))
        thread.task_finished.connect(lambda success, ver: finished_results.append((success, ver)))

        thread.run()

        self.assertEqual(len(finished_results), 1)
        self.assertTrue(finished_results[0][0])  # success
        self.assertEqual(finished_results[0][1], "fabric-loader-0.15.7-1.20.1")
        self.assertTrue(len(progress_updates) > 0)


class TestProfileEngineIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_add_profile_dialog_engine_selection(self):
        from main import AddProfileDialog
        dlg = AddProfileDialog()
        self.assertTrue(dlg.engine_combo.count() >= 5)

        # Select NeoForge
        idx = dlg.engine_combo.findData("neoforge")
        self.assertGreaterEqual(idx, 0)
        dlg.engine_combo.setCurrentIndex(idx)
        dlg.name_input.setText("Neo Adventure")

        data = dlg.get_data()
        self.assertEqual(data["name"], "Neo Adventure")
        self.assertEqual(data["loader"], "neoforge")
        self.assertIn("1.20.1", dlg.version_input.currentText())

    def test_find_installed_engine_version(self):
        from main import VegaLauncher
        with tempfile.TemporaryDirectory() as tmp_dir:
            versions_dir = Path(tmp_dir) / "versions"
            versions_dir.mkdir(parents=True, exist_ok=True)
            (versions_dir / "fabric-loader-0.15.11-1.20.1").mkdir()
            (versions_dir / "neoforge-20.4.80-1.20.4").mkdir()
            (versions_dir / "1.19.4-forge-45.1.0").mkdir()
            (versions_dir / "quilt-loader-0.25.0-1.20.1").mkdir()
            (versions_dir / "1.20.1").mkdir()

            mock_launcher = MagicMock(spec=VegaLauncher)
            mock_launcher.mc_dir = tmp_dir

            # Unbound method call passing mock_launcher
            found_fabric = VegaLauncher._find_installed_engine_version(mock_launcher, "1.20.1", "fabric")
            self.assertEqual(found_fabric, "fabric-loader-0.15.11-1.20.1")

            found_neoforge = VegaLauncher._find_installed_engine_version(mock_launcher, "1.20.4", "neoforge")
            self.assertEqual(found_neoforge, "neoforge-20.4.80-1.20.4")

            found_forge = VegaLauncher._find_installed_engine_version(mock_launcher, "1.19.4", "forge")
            self.assertEqual(found_forge, "1.19.4-forge-45.1.0")

            found_quilt = VegaLauncher._find_installed_engine_version(mock_launcher, "1.20.1", "quilt")
            self.assertEqual(found_quilt, "quilt-loader-0.25.0-1.20.1")

            found_vanilla = VegaLauncher._find_installed_engine_version(mock_launcher, "1.20.1", "vanilla")
            self.assertEqual(found_vanilla, "1.20.1")

            # Missing engine returns None
            found_missing = VegaLauncher._find_installed_engine_version(mock_launcher, "1.16.5", "neoforge")
            self.assertIsNone(found_missing)

    def test_add_profile_triggers_engine_install(self):
        from PySide6.QtWidgets import QDialog
        from main import VegaLauncher

        mock_launcher = MagicMock(spec=VegaLauncher)
        mock_launcher.profiles = {}
        mock_launcher.save_config = MagicMock()
        mock_launcher.refresh_profile_list = MagicMock()
        mock_launcher._get_profile_item = MagicMock(return_value=None)
        mock_launcher.on_profile_selected = MagicMock()
        mock_launcher._generate_unique_profile_name = MagicMock(return_value=("TestPack", "/dummy/path"))
        mock_launcher.install_engine_for_profile = MagicMock()

        dummy_dialog = MagicMock()
        dummy_dialog.exec.return_value = QDialog.Accepted
        dummy_dialog.get_data.return_value = {
            "name": "AutoEngineProfile",
            "version": "1.20.1",
            "loader": "neoforge",
            "ram": 4096
        }

        with patch("main.AddProfileDialog", return_value=dummy_dialog), patch("main.os.makedirs"):
            VegaLauncher.add_profile(mock_launcher)

            # Verifies profile was registered with loader
            self.assertEqual(len(mock_launcher.profiles), 1)
            pid = list(mock_launcher.profiles.keys())[0]
            self.assertEqual(mock_launcher.profiles[pid]["loader"], "neoforge")
            mock_launcher.install_engine_for_profile.assert_called_once_with(pid, "1.20.1", "neoforge")


if __name__ == "__main__":
    unittest.main()


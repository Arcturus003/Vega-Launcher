import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from prism_instance_importer import (
    InstanceImportWorkerThread,
    PrismInstanceImporter,
    PrismInstanceInfo,
)

app = QApplication.instance() or QApplication([])


class TestPrismInstanceImporter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="vega_prism_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_instance_cfg(self):
        cfg_path = os.path.join(self.temp_dir, "instance.cfg")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("InstanceType=OneSix\nname=Fabric Horizons\niconKey=fabric\nMaxMemAlloc=6144\n# comment\n[General]\n")

        props = PrismInstanceImporter.parse_instance_cfg(cfg_path)
        self.assertEqual(props.get("name"), "Fabric Horizons")
        self.assertEqual(props.get("iconKey"), "fabric")
        self.assertEqual(props.get("MaxMemAlloc"), "6144")

    def test_parse_mmc_pack(self):
        pack_path = os.path.join(self.temp_dir, "mmc-pack.json")
        data = {
            "components": [
                {"uid": "net.minecraft", "version": "1.21.1"},
                {"uid": "net.neoforged.neoforge", "version": "21.1.65"},
            ]
        }
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        mc_ver, loader, loader_ver = PrismInstanceImporter.parse_mmc_pack(pack_path)
        self.assertEqual(mc_ver, "1.21.1")
        self.assertEqual(loader, "neoforge")
        self.assertEqual(loader_ver, "21.1.65")

    def test_discover_instances(self):
        inst_dir = os.path.join(self.temp_dir, "MyInstance")
        os.makedirs(inst_dir, exist_ok=True)
        game_dir = os.path.join(inst_dir, ".minecraft")
        mods_dir = os.path.join(game_dir, "mods")
        saves_dir = os.path.join(game_dir, "saves", "NewWorld")
        os.makedirs(mods_dir, exist_ok=True)
        os.makedirs(saves_dir, exist_ok=True)

        with open(os.path.join(mods_dir, "testmod.jar"), "w") as f:
            f.write("dummy")
        with open(os.path.join(inst_dir, "instance.cfg"), "w", encoding="utf-8") as f:
            f.write("name=My Test Pack\niconKey=creeper\nMaxMemAlloc=8192\n")
        with open(os.path.join(inst_dir, "mmc-pack.json"), "w", encoding="utf-8") as f:
            json.dump({
                "components": [
                    {"uid": "net.minecraft", "version": "1.20.1"},
                    {"uid": "net.fabricmc.fabric-loader", "version": "0.15.11"},
                ]
            }, f)

        discovered = PrismInstanceImporter.discover_instances(search_paths=[self.temp_dir])
        self.assertEqual(len(discovered), 1)
        info = discovered[0]
        self.assertEqual(info.name, "My Test Pack")
        self.assertEqual(info.version, "1.20.1")
        self.assertEqual(info.loader, "fabric")
        self.assertEqual(info.loader_version, "0.15.11")
        self.assertEqual(info.ram, 8192)
        self.assertEqual(info.mod_count, 1)
        self.assertEqual(info.world_count, 1)

    def test_import_instance_selective_clean_copy(self):
        inst_dir = os.path.join(self.temp_dir, "source_instance")
        game_dir = os.path.join(inst_dir, ".minecraft")
        os.makedirs(os.path.join(game_dir, "mods"), exist_ok=True)
        os.makedirs(os.path.join(game_dir, "saves", "WorldA"), exist_ok=True)
        os.makedirs(os.path.join(game_dir, "logs"), exist_ok=True)
        os.makedirs(os.path.join(game_dir, "crash-reports"), exist_ok=True)

        with open(os.path.join(game_dir, "mods", "jei.jar"), "w") as f:
            f.write("mod_binary")
        with open(os.path.join(game_dir, "options.txt"), "w") as f:
            f.write("fov:70")
        with open(os.path.join(game_dir, "logs", "latest.log"), "w") as f:
            f.write("dirty_log")
        with open(os.path.join(game_dir, "crash-reports", "crash.txt"), "w") as f:
            f.write("crash")

        info = PrismInstanceInfo(
            id="source_instance",
            name="Source Pack",
            version="1.20.1",
            loader="fabric",
            loader_version="0.15.11",
            ram=4096,
            path=inst_dir,
            game_dir=game_dir,
            mod_count=1,
            world_count=1,
        )

        target_dir = os.path.join(self.temp_dir, "target_profiles")
        res = PrismInstanceImporter.import_instance(info, target_dir)

        dest_path = res["path"]
        self.assertTrue(os.path.isdir(dest_path))
        self.assertTrue(os.path.isfile(os.path.join(dest_path, "mods", "jei.jar")))
        self.assertTrue(os.path.isfile(os.path.join(dest_path, "options.txt")))
        self.assertTrue(os.path.isdir(os.path.join(dest_path, "saves", "WorldA")))
        # Ensure logs & crashes are excluded (clean copy)
        self.assertFalse(os.path.exists(os.path.join(dest_path, "logs")))
        self.assertFalse(os.path.exists(os.path.join(dest_path, "crash-reports")))

    def test_import_worker_thread(self):
        inst_dir = os.path.join(self.temp_dir, "worker_inst")
        game_dir = os.path.join(inst_dir, ".minecraft")
        os.makedirs(os.path.join(game_dir, "mods"), exist_ok=True)
        with open(os.path.join(game_dir, "options.txt"), "w") as f:
            f.write("lang:en_us")

        info = PrismInstanceInfo(
            id="worker_inst",
            name="Worker Pack",
            version="1.21.1",
            loader="neoforge",
            loader_version="21.1.65",
            ram=6144,
            path=inst_dir,
            game_dir=game_dir,
            mod_count=0,
            world_count=0,
        )

        target_dir = os.path.join(self.temp_dir, "target_profiles_worker")
        worker = InstanceImportWorkerThread(info, target_dir)

        progress_events = []
        finish_events = []
        worker.progress.connect(lambda c, t, m: progress_events.append((c, t, m)))
        worker.finished_import.connect(lambda ok, data, err: finish_events.append((ok, data, err)))

        worker.run()

        self.assertTrue(len(finish_events) == 1)
        ok, data, err = finish_events[0]
        self.assertTrue(ok)
        self.assertEqual(data["name"], "Worker Pack")
        self.assertEqual(data["loader"], "neoforge")
        self.assertEqual(data["ram"], 6144)
        self.assertTrue(os.path.isdir(data["path"]))


class TestAddProfileDialogPrismImport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="vega_dialog_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_profile_dialog_manual_data(self):
        from main import AddProfileDialog
        dlg = AddProfileDialog()
        dlg.name_input.setText("Custom Survival")
        dlg.ram_input.setValue(8192)
        data = dlg.get_data()
        self.assertEqual(data["name"], "Custom Survival")
        self.assertEqual(data["ram"], 8192)
        self.assertNotIn("imported_path", data)

    def test_add_profile_dialog_imported_data(self):
        from main import AddProfileDialog
        dlg = AddProfileDialog()
        dlg.imported_data = {
            "name": "Imported Pack",
            "version": "1.21.1",
            "loader": "neoforge",
            "ram": 6144,
            "path": "/mock/imported/path",
        }
        data = dlg.get_data()
        self.assertEqual(data["name"], "Imported Pack")
        self.assertEqual(data["version"], "1.21.1")
        self.assertEqual(data["loader"], "neoforge")
        self.assertEqual(data["ram"], 6144)
        self.assertEqual(data["imported_path"], "/mock/imported/path")

    def test_main_add_profile_with_imported_path(self):
        from main import VegaLauncher
        mock_launcher = MagicMock(spec=VegaLauncher)
        mock_launcher.profiles = {}
        mock_launcher.save_config = MagicMock()
        mock_launcher.refresh_profile_list = MagicMock()
        mock_launcher._get_profile_item = MagicMock(return_value=None)
        mock_launcher.on_profile_selected = MagicMock()
        mock_launcher.install_engine_for_profile = MagicMock()

        dummy_dialog = MagicMock()
        dummy_dialog.exec.return_value = QDialog.Accepted
        dummy_dialog.get_data.return_value = {
            "name": "Create: New World",
            "version": "1.21.1",
            "loader": "neoforge",
            "ram": 6144,
            "imported_path": os.path.join(self.temp_dir, "Create_New_World"),
        }

        with patch("main.AddProfileDialog", return_value=dummy_dialog):
            VegaLauncher.add_profile(mock_launcher)

        self.assertEqual(len(mock_launcher.profiles), 1)
        pid = list(mock_launcher.profiles.keys())[0]
        prof = mock_launcher.profiles[pid]
        self.assertEqual(prof["name"], "Create: New World")
        self.assertEqual(prof["version"], "1.21.1")
        self.assertEqual(prof["loader"], "neoforge")
        self.assertEqual(prof["ram"], 6144)
        self.assertEqual(prof["path"], os.path.join(self.temp_dir, "Create_New_World"))
        mock_launcher.install_engine_for_profile.assert_called_once_with(pid, "1.21.1", "neoforge")


if __name__ == "__main__":
    unittest.main()

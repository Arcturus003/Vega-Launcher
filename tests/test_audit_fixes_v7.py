import inspect
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server_instance import ServerProperties, ServerInstance


class TestAuditFixesV7(unittest.TestCase):
    def test_dungeons_download_filename_sanitized(self):
        """Finding 1: Verifies that handle_dungeons_download sanitizes download filename with os.path.basename."""
        from main import VegaLauncher
        source = inspect.getsource(VegaLauncher.handle_dungeons_download)
        self.assertIn("os.path.basename(raw_name)", source)

    def test_neoforge_server_jar_rename(self):
        """Finding 2: Verifies runtime_provisioner checks for both forge- and neoforge- prefixes."""
        rp_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime_provisioner.py")
        with open(rp_py, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('f.startswith("neoforge-")', content)

    def test_server_properties_port_persistence(self):
        """Finding 3: Verifies write_properties writes server-port into server.properties."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            instance = ServerInstance(tmp_dir)
            props = ServerProperties(server_port="25569", max_players=20)
            instance.write_properties(props)

            read_back = instance.read_properties()
            self.assertEqual(read_back.server_port, "25569")

            props_file = os.path.join(tmp_dir, "server.properties")
            with open(props_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("server-port=25569", content)

    def test_archive_extraction_no_powershell_fallback(self):
        """Finding 4: Verifies mod_manager does not use uncontained Expand-Archive fallback."""
        mm_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mod_manager.py")
        with open(mm_py, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("Expand-Archive", content)

    def test_shortcut_script_uses_safe_encoding(self):
        """Finding 5: Verifies create_profile_shortcut uses robust COM/PowerShell/utf-16le and avoids utf-8-sig BOM."""
        from main import VegaLauncher
        source = inspect.getsource(VegaLauncher.create_profile_shortcut)
        self.assertNotIn('encoding="utf-8-sig"', source)
        self.assertIn("WScript.Shell", source)

    def test_profile_deletion_cmd_path_quoted(self):
        """Finding 6: Verifies profile_store.py passes real_target without double-quoting to cmd.exe rd /s /q."""
        ps_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "profile_store.py")
        with open(ps_py, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('["cmd.exe", "/c", "rd", "/s", "/q", real_target]', content)

    def test_release_helper_runs_unittest_discover(self):
        """Finding 7: Verifies release_helper.py executes automated test discovery."""
        rh_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".agents", "skills", "build_vega_launcher", "scripts", "release_helper.py"
        )
        if not os.path.exists(rh_py):
            self.skipTest("release_helper.py not tracked in CI checkout")
        with open(rh_py, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('"-m", "unittest", "discover", "tests"', content)


    def test_installed_mods_search_filtering(self):
        """Verifies InstalledModsPanel search bar filters mod list in real-time."""
        from PySide6.QtWidgets import QApplication
        from ui_components import InstalledModsPanel
        app = QApplication.instance() or QApplication([])

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            f1 = os.path.join(tmp_dir, "Create-1.20.1-0.5.1.jar")
            f2 = os.path.join(tmp_dir, "DynamicFps-Fabric-3.9.5.jar")
            f3 = os.path.join(tmp_dir, "Sodium-1.20.1.jar")
            for fp in [f1, f2, f3]:
                with open(fp, "w") as f:
                    f.write("dummy")

            panel = InstalledModsPanel()
            panel.load_mods(tmp_dir)

            self.assertEqual(panel.mod_list.count(), 3)
            self.assertEqual(panel.mod_count_lbl.text(), "3 mod")

            # Search "create"
            panel.mod_search_input.setText("create")
            visible_items = [panel.mod_list.item(i) for i in range(3) if not panel.mod_list.item(i).isHidden()]
            self.assertEqual(len(visible_items), 1)
            from PySide6.QtCore import Qt
            self.assertIn("create", visible_items[0].data(Qt.UserRole))
            self.assertEqual(panel.mod_count_lbl.text(), "1 / 3 mod")

            # Search "fabric"
            panel.mod_search_input.setText("fabric")
            visible_items = [panel.mod_list.item(i) for i in range(3) if not panel.mod_list.item(i).isHidden()]
            self.assertEqual(len(visible_items), 1)
            self.assertEqual(panel.mod_count_lbl.text(), "1 / 3 mod")

            # Clear search
            panel.mod_search_input.setText("")
            visible_items = [panel.mod_list.item(i) for i in range(3) if not panel.mod_list.item(i).isHidden()]
            self.assertEqual(len(visible_items), 3)
            self.assertEqual(panel.mod_count_lbl.text(), "3 mod")

            # Language switch
            panel.set_language("en")
            self.assertIn("Search installed mods", panel.mod_search_input.placeholderText())
            self.assertEqual(panel.mod_count_lbl.text(), "3 mods")


if __name__ == "__main__":
    unittest.main()

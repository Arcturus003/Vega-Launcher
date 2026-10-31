import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestPonytailAuditV12(unittest.TestCase):
    def test_detect_client_runtime_case_insensitive_jars(self):
        """Verify detect_client_runtime recognizes uppercase .JAR files on Windows."""
        from runtime_provisioner import RuntimeProvisioner

        with tempfile.TemporaryDirectory() as tmp_dir:
            mods_dir = os.path.join(tmp_dir, "mods")
            os.makedirs(mods_dir, exist_ok=True)
            # Create files with uppercase extensions
            open(os.path.join(mods_dir, "FABRIC-API-1.0.JAR"), "w").close()
            open(os.path.join(mods_dir, "SODIUM-FABRIC.JAR"), "w").close()

            spec = RuntimeProvisioner.detect_client_runtime({"path": tmp_dir, "game_version": "1.20.1"})
            self.assertEqual(spec.loader, "fabric")

    def test_detect_server_runtime_case_insensitive_jars_and_logs(self):
        """Verify detect_server_runtime discovers uppercase .JAR server files and .LOG files."""
        from runtime_provisioner import RuntimeProvisioner

        with tempfile.TemporaryDirectory() as tmp_dir:
            open(os.path.join(tmp_dir, "PURPUR-1.20.4-1234.JAR"), "w").close()
            with open(os.path.join(tmp_dir, "LATEST.LOG"), "w", encoding="utf-8") as f:
                f.write("[INFO] Starting Minecraft 1.20.4 server...")

            spec = RuntimeProvisioner.detect_server_runtime(tmp_dir)
            self.assertEqual(spec.loader, "purpur")
            self.assertEqual(spec.mc_version, "1.20.4")

    def test_backup_manager_case_insensitive_filtering(self):
        """Verify BackupManager discovers uppercase .ZIP backups and collects uppercase configs."""
        from backup_manager import BackupManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            backups_dir = os.path.join(tmp_dir, "backups")
            os.makedirs(backups_dir, exist_ok=True)
            open(os.path.join(backups_dir, "BACKUP_2026-10-31.ZIP"), "w").close()

            found_backups = BackupManager.list_backups(tmp_dir)
            self.assertIn("BACKUP_2026-10-31.ZIP", found_backups)

            # Test config files collection
            open(os.path.join(tmp_dir, "SERVER.PROPERTIES"), "w").close()
            open(os.path.join(tmp_dir, "OPS.JSON"), "w").close()
            files_to_zip = BackupManager.collect_server_backup_files(tmp_dir)
            arc_names = [f[1] for f in files_to_zip]
            self.assertIn("SERVER.PROPERTIES", arc_names)
            self.assertIn("OPS.JSON", arc_names)

    def test_sound_manager_init_no_write_test_file(self):
        """Verify SoundManager uses os.access without generating .write_test on disk."""
        from sound_manager import SoundManager

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            with patch("sound_manager.generate_click_wav"), \
                 patch("sound_manager.generate_launch_wav"), \
                 patch("sound_manager.generate_levelup_wav"), \
                 patch("sound_manager.generate_error_wav"), \
                 patch("sound_manager.generate_door_open_wav"), \
                 patch("sound_manager.generate_door_close_wav"):
                sm = SoundManager()
                sm.sounds_dir = os.path.join(tmp_dir, "sounds")
                sm._init_sounds()
                self.assertFalse(os.path.exists(os.path.join(sm.sounds_dir, ".write_test")))
                self.assertTrue(os.path.isdir(sm.sounds_dir))

    def test_ui_components_case_insensitive_mod_display(self):
        """Verify ModItemWidget and format helpers handle uppercase extensions correctly."""
        from ui_components import _format_mod_display_name, ModItemWidget

        title, sub = _format_mod_display_name("CREATE-FABRIC-0.5.JAR")
        self.assertEqual(title.upper(), "CREATE")

        from PySide6.QtWidgets import QListWidget
        lw = QListWidget()
        widget = ModItemWidget("C:/fake/path/JEI.JAR.DISABLED", lw)
        self.assertTrue(widget.is_disabled)
        self.assertFalse(widget.toggle_btn.isChecked())


if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sound_manager import SoundManager, SOUND_VERSION
from mod_manager import ModrinthAPI
from PySide6.QtCore import QUrl


class TestAuditFixesV4(unittest.TestCase):
    def test_sound_version_file_and_cache_invalidation(self):
        """Verifies that .sound_version is written and stale assets trigger regeneration."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            # Create a stale .sound_version file with version 1
            version_file = os.path.join(tmp_dir, ".sound_version")
            with open(version_file, "w", encoding="utf-8") as f:
                f.write("1")

            # Initialize a new SoundManager with tmp_dir
            mgr = SoundManager(sounds_dir=tmp_dir)
            self.assertTrue(os.path.exists(version_file))
            with open(version_file, "r", encoding="utf-8") as f:
                current_ver = f.read().strip()
            self.assertEqual(current_ver, str(SOUND_VERSION))

            # Verify all expected wav files were generated
            for sname in ["click.wav", "launch.wav", "levelup.wav", "error.wav", "door_open.wav", "door_close.wav"]:
                fpath = os.path.join(tmp_dir, sname)
                self.assertTrue(os.path.exists(fpath))
                self.assertGreater(os.path.getsize(fpath), 0)

            # Release file handles held by QSoundEffect
            for eff in mgr._effects.values():
                eff.setSource(QUrl())
            for v in mgr._click_voices:
                v.setSource(QUrl())
            mgr._effects.clear()
            mgr._click_voices.clear()

    def test_modpack_engine_loader_version_passed(self):
        """Verifies that DefaultClientInstallerBackend in runtime_provisioner.py passes loader_version to install_fabric and install_quilt."""
        rp_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runtime_provisioner.py")
        with open(rp_py, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("install_fabric(mc_version, mc_dir, loader_version=loader_version", content)
        self.assertIn("install_quilt(mc_version, mc_dir, loader_version=loader_version", content)

    def test_curseforge_download_headers(self):
        """Verifies that CurseForge file downloads send ModrinthAPI.HEADERS."""
        mod_mgr_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mod_manager.py")
        with open(mod_mgr_py, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("requests.get(cf_url, headers=ModrinthAPI.HEADERS", content)

    def test_gallery_thumbnails_capped(self):
        """Verifies that DetailPanel caps gallery downloads to 6 items max."""
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        with open(main_py, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("capped_urls = urls_to_load[:6]", content)

    def test_theme_persistence_and_combobox(self):
        """Verifies that main.py uses self.settings['theme'] as single source of truth and blocks signals."""
        main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        with open(main_py, "r", encoding="utf-8") as f:
            content = f.read()

        # In apply_language, theme must be read from settings, not transient combo data
        self.assertIn('cur_data = self.settings.get("theme", "electric_amethyst")', content)
        # combo_theme population in _build_settings_page must block signals
        self.assertIn("self.combo_theme.blockSignals(True)", content)


if __name__ == "__main__":
    unittest.main()

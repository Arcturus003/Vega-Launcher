import os
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from main import (
    VegaLauncher,
    ProfileWidget,
    DetailPanel,
    ModrinthBrowser,
    EndermanInstallModal,
    CustomProgressOverlay,
)
from ui_components import ActionBar, NavBar, InstalledModsPanel
from card_widget import CardWidget
from engine_installer import EngineInstallDialog
from server_downloader import ServerSoftwareDialog
from server_widget import ProfileSelectDialog


class TestEnglishLocalization(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.launcher = VegaLauncher(data_dir=self.tmp_dir.name)
        self.launcher.settings["sound_enabled"] = False
        if hasattr(self.launcher, "sound_mgr") and self.launcher.sound_mgr:
            self.launcher.sound_mgr.set_enabled(False)

    def tearDown(self):
        self.launcher.close()
        self.tmp_dir.cleanup()

    def test_launcher_apply_language_english_and_turkish(self):
        self.launcher.settings["language"] = "en"
        self.launcher.apply_language("en")

        # Hero & Profile page
        self.assertEqual(self.launcher.hero_eyebrow.text(), "SELECTED PROFILE")
        self.assertEqual(self.launcher.hero_icon_box.toolTip(), "Edit Profile / Change Icon")
        self.assertEqual(self.launcher.add_profile_btn.text(), "+ New Profile")
        self.assertEqual(self.launcher.install_file_btn.text(), "Install Zip")

        # Bedrock & Dungeons pages
        self.assertEqual(self.launcher.bed_btn.text(), "PLAY BEDROCK")
        self.assertIn("cross-platform", self.launcher.bed_desc.text())
        self.assertEqual(self.launcher.dun_btn.text(), "ENTER DUNGEON")
        self.assertEqual(self.launcher.dun_mods_btn.text(), "Installed Mods")

        # ActionBar dynamic states
        ab = self.launcher.action_bar
        self.assertEqual(ab.play_btn.text(), "PLAY")
        ab.play_btn.setText("İndiriliyor...")
        ab.set_language("en")
        self.assertEqual(ab.play_btn.text(), "Downloading...")
        ab.set_language("tr")
        self.assertEqual(ab.play_btn.text(), "İndiriliyor...")
        ab.set_language("en")

        # ModrinthBrowser category chips & filter items
        pb = self.launcher.pack_browser
        chip_texts = [btn.text() for _, btn in pb.category_chips]
        self.assertIn("All", chip_texts)
        self.assertIn("FPS / Performance", chip_texts)
        self.assertIn("Adventure & RPG", chip_texts)
        self.assertIn("Technology", chip_texts)
        self.assertTrue(pb.version_combo.itemText(2).startswith("Version:"))
        self.assertTrue(pb.loader_combo.itemText(2).startswith("Loader:"))

        # DetailPanel
        dp = self.launcher.detail_panel
        self.assertEqual(dp.main_gallery_preview.text(), "No Images Available")
        self.assertEqual(dp.desc_header.text(), "About")

        # ServerWidget settings page labels & player list state
        sw = self.launcher.server_page
        sw.on_player_joined("Steve")
        self.assertEqual(sw.lbl_prop_motd.text(), "MOTD (Description):")
        self.assertEqual(sw.lbl_prop_max_players.text(), "Max Players:")
        self.assertEqual(sw.chk_crack.text(), "Enabled (online-mode=false)")
        self.assertEqual(sw.player_list.item(0).text(), "[Online] Steve")

        # Switch back to Turkish and verify restoration
        self.launcher.settings["language"] = "tr"
        self.launcher.apply_language("tr")
        self.assertEqual(self.launcher.bed_btn.text(), "BEDROCK OYNA")
        self.assertEqual(self.launcher.dun_btn.text(), "ZİNDANA GİR")
        self.assertEqual(sw.player_list.item(0).text(), "[Çevrimiçi] Steve")

    def test_dialogs_and_widgets_english(self):
        self.launcher.settings["language"] = "en"
        self.launcher.apply_language("en")

        pw = ProfileWidget("TestPack", "1.20.1", 4096, "pid1", lang="en")
        self.assertEqual(pw.update_btn.text(), "Update")
        pw.set_language("tr")
        self.assertEqual(pw.update_btn.text(), "Güncelle")

        card = CardWidget({}, lang="en")
        self.assertEqual(card.title.text(), "Untitled")
        self.assertEqual(card.update_btn.text(), "Update")
        card.set_language("tr")
        self.assertEqual(card.update_btn.text(), "Güncelle")

        modal = EndermanInstallModal("MyPack", self.launcher)
        self.assertEqual(modal.counter_lbl.text(), "Preparing...")
        self.assertEqual(modal.cancel_btn.text(), "Cancel")
        modal.set_progress(3, 10)
        self.assertEqual(modal.counter_lbl.text(), "3 / 10 Mods (30%)")

        overlay = CustomProgressOverlay("test.pak", self.launcher)
        self.assertEqual(overlay.title_lbl.text(), "Installing Mod...")
        self.assertIn("Downloading test.pak", overlay.desc_lbl.text())

        eng_dlg = EngineInstallDialog({"name": "TestPack", "version": "1.20.1"}, "pid1", self.launcher)
        self.assertEqual(eng_dlg.windowTitle(), "Engine Installer - TestPack")
        self.assertEqual(eng_dlg.install_btn.text(), "Install")

        srv_dlg = ServerSoftwareDialog(parent=self.launcher, server_dir=self.tmp_dir.name)
        self.assertIn("Purpur (Plugin)", [srv_dlg.combo_software.itemText(i) for i in range(srv_dlg.combo_software.count())])

        prof_dlg = ProfileSelectDialog(["Pack1 (1.20.1)"], self.launcher.server_page)
        self.assertEqual(prof_dlg.windowTitle(), "Select Client Profile")
        self.assertEqual(prof_dlg.btn_ok.text(), "Select")
        self.assertEqual(prof_dlg.btn_cancel.text(), "Cancel")


if __name__ == "__main__":
    unittest.main()

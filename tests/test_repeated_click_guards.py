import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QListWidgetItem

app = QApplication.instance()
if not app:
    app = QApplication([])

import ui_components
from app_updater import AppUpdater
from card_widget import CardWidget
from content_browser import DetailPanel, ModrinthBrowser
from main import EditProfileDialog, VegaLauncher, handle_cli_args
from server_widget import ServerProperties, ServerWidget
from sound_manager import SoundManager
from ui_components import InstalledModsPanel, NavBar, safe_open_path


class TestRepeatedClickGuards(unittest.TestCase):
    def test_on_play_blocks_when_launching_or_running_and_resets_on_abort(self):
        dummy = MagicMock(spec=VegaLauncher)
        dummy.settings = {"language": "tr"}
        dummy._is_launching = True
        dummy._is_game_running = False
        dummy.sound_mgr = MagicMock()
        dummy.get_selected_profile = MagicMock()

        VegaLauncher.on_play(dummy)
        dummy.get_selected_profile.assert_not_called()
        dummy.sound_mgr.play_click.assert_not_called()

        dummy._is_launching = False
        dummy._is_game_running = True
        VegaLauncher.on_play(dummy)
        dummy.get_selected_profile.assert_not_called()

        # When no profile is selected, _is_launching resets to False
        dummy._is_game_running = False
        dummy.get_selected_profile.return_value = (None, None)
        with patch("main.QMessageBox.warning"):
            VegaLauncher.on_play(dummy)
        self.assertFalse(dummy._is_launching)

        # When token validation returns network_error_abort, _is_launching resets to False
        dummy._is_launching = True
        dummy.action_bar = MagicMock()
        dummy.statusBar = MagicMock()
        with patch("main.QMessageBox.warning"):
            VegaLauncher._on_token_validated(
                dummy,
                {"status": "network_error_abort", "error_msg": "offline"},
                "pid1",
                {"name": "P1"},
            )
        self.assertFalse(dummy._is_launching)
        dummy.action_bar.play_btn.setEnabled.assert_called_with(True)

    def test_handle_cli_args_ignores_launch_when_already_launching_or_running(self):
        mock_window = MagicMock()
        mock_window._is_launching = True
        mock_window._is_game_running = False

        handle_cli_args(mock_window, ["--launch", "pack_a"])
        mock_window._get_profile_item.assert_not_called()

        mock_window._is_launching = False
        mock_window._is_game_running = True
        handle_cli_args(mock_window, ["--launch", "pack_a"])
        mock_window._get_profile_item.assert_not_called()

    def test_card_widget_ignores_repeat_left_click_and_right_click(self):
        data = {
            "project_id": "sodium",
            "title": "Sodium",
            "description": "Fast rendering",
            "downloads": 1000,
        }
        card = CardWidget(data)
        emitted = []
        card.clicked.connect(lambda d: emitted.append(d))

        right_press = QMouseEvent(
            QMouseEvent.MouseButtonPress,
            QPointF(5, 5),
            QPointF(5, 5),
            Qt.RightButton,
            Qt.RightButton,
            Qt.NoModifier,
        )
        card.mousePressEvent(right_press)
        self.assertEqual(len(emitted), 0)

        left_press = QMouseEvent(
            QMouseEvent.MouseButtonPress,
            QPointF(5, 5),
            QPointF(5, 5),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        card.mousePressEvent(left_press)
        self.assertEqual(len(emitted), 1)

        card.set_selected(True)
        card.mousePressEvent(left_press)
        self.assertEqual(len(emitted), 1)
        card.deleteLater()

    def test_modrinth_browser_and_detail_panel_ignore_same_card_and_project(self):
        panel = DetailPanel()
        panel.show()
        proj_data = {
            "project_id": "iris",
            "title": "Iris Shaders",
            "description": "Shaders mod",
            "project_type": "mod",
        }
        with patch("content_browser.ProjectDetailsThread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread.isRunning.return_value = False
            mock_thread_cls.return_value = mock_thread

            panel.update_info(proj_data)
            self.assertEqual(mock_thread_cls.call_count, 1)

            # Second call with identical project while open is a no-op
            panel.update_info(proj_data)
            self.assertEqual(mock_thread_cls.call_count, 1)

            # Closing drawer resets current_project so re-opening works
            panel.close_drawer()
            panel.show()
            panel.update_info(proj_data)
            self.assertEqual(mock_thread_cls.call_count, 2)
        panel.deleteLater()

        # ModrinthBrowser.on_card_clicked no-op on already selected card
        dummy_browser = MagicMock(spec=ModrinthBrowser)
        card = MagicMock()
        dummy_browser.selected_card = card
        dummy_browser.item_selected = MagicMock()
        ModrinthBrowser.on_card_clicked(dummy_browser, proj_data, card)
        dummy_browser.item_selected.emit.assert_not_called()
        card.set_selected.assert_not_called()

    def test_detail_panel_ram_and_preview_noop_when_unchanged(self):
        panel = DetailPanel()
        with patch.object(SoundManager.get_instance(), "play_click") as mock_click:
            # 6144 is the default selected RAM
            panel.set_ram(6144)
            mock_click.assert_not_called()

            panel.set_ram(8192)
            mock_click.assert_called_once()

            mock_click.reset_mock()
            panel.set_ram(8192)
            mock_click.assert_not_called()

        pix = QPixmap(32, 32)
        with patch.object(
            panel.main_gallery_preview,
            "setPixmap",
            wraps=panel.main_gallery_preview.setPixmap,
        ) as spy_set_pix:
            panel.set_main_preview(pix)
            self.assertEqual(spy_set_pix.call_count, 1)
            panel.set_main_preview(pix)
            self.assertEqual(spy_set_pix.call_count, 1)
        panel.deleteLater()

    def test_navbar_and_switch_tab_noop_on_active_tab(self):
        nav = NavBar()
        emitted = []
        nav.nav_clicked.connect(lambda k: emitted.append(k))
        with patch.object(SoundManager.get_instance(), "play_book_flip") as mock_flip:
            # "home" is already active after init
            nav.on_nav_click("home")
            self.assertEqual(emitted, [])
            mock_flip.assert_not_called()

            nav.on_nav_click("mods")
            self.assertEqual(emitted, ["mods"])
            mock_flip.assert_called_once()

            mock_flip.reset_mock()
            nav.on_nav_click("mods")
            self.assertEqual(emitted, ["mods"])
            mock_flip.assert_not_called()
        nav.deleteLater()

    def test_profile_selection_and_installed_mods_panel_guards(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mods_dir = os.path.join(tmpdir, "mods")
            os.makedirs(mods_dir, exist_ok=True)

            panel = InstalledModsPanel()
            with patch.object(panel, "refresh_list", wraps=panel.refresh_list) as spy_refresh:
                # 0-mod profile load
                panel.load_mods(mods_dir, {"name": "P1", "version": "1.20.1"}, "pid1")
                self.assertEqual(spy_refresh.call_count, 1)

                # Second call on same 0-mod profile with unchanged mtime must be a no-op
                panel.load_mods(mods_dir, {"name": "P1", "version": "1.20.1"}, "pid1")
                self.assertEqual(spy_refresh.call_count, 1)

                # Create 20 dummy jars (>15 batch threshold)
                for i in range(20):
                    with open(os.path.join(mods_dir, f"mod_{i:02d}.jar"), "wb") as f:
                        f.write(b"PK\x05\x06" + b"\x00" * 18)
                os.utime(mods_dir, (os.path.getmtime(mods_dir) + 5, os.path.getmtime(mods_dir) + 5))

                panel.load_mods(mods_dir, {"name": "P1", "version": "1.20.1"}, "pid1")
                self.assertEqual(spy_refresh.call_count, 2)
                self.assertTrue(panel._is_batch_loading)

                # Calling load_mods while batch loading is still in progress must be a no-op
                panel.load_mods(mods_dir, {"name": "P1", "version": "1.20.1"}, "pid1")
                self.assertEqual(spy_refresh.call_count, 2)
                gen1 = panel._mod_load_gen

                # Switching to WORLDS sub-tab and then loading a different profile (pid2) mid-batch-load
                mods2 = os.path.join(tmpdir, "p2_mods")
                os.makedirs(mods2, exist_ok=True)
                for i in range(3):
                    with open(os.path.join(mods2, f"m2_{i:02d}.jar"), "wb") as f:
                        f.write(b"PK\x05\x06" + b"\x00" * 18)

                panel.switch_sub_tab(1, play_sound=False)
                panel.load_mods(mods2, {"name": "P2", "version": "1.20.1"}, "pid2")
                self.assertGreater(panel._mod_load_gen, gen1)
                self.assertFalse(panel._is_batch_loading)
                self.assertEqual(panel._last_loaded_count, -1)

                # Old timer firing for gen1 must be a complete no-op
                panel._load_mod_batch(gen1)
                # Switching back to MODS sub-tab loads P2's 3 mods cleanly
                panel.switch_sub_tab(0, play_sound=False)
                self.assertEqual(panel._last_loaded_count, 3)
                self.assertEqual(panel.mod_list.count(), 3)

            # Sub-tab switch guard
            with patch.object(SoundManager.get_instance(), "play_bookshelf_insert") as mock_book:
                panel.switch_sub_tab(0, play_sound=True)
                mock_book.assert_not_called()
                panel.switch_sub_tab(1, play_sound=True)
                mock_book.assert_called_once()
                mock_book.reset_mock()
                panel.switch_sub_tab(1, play_sound=True)
                mock_book.assert_not_called()
            panel._mod_load_gen = getattr(panel, "_mod_load_gen", 0) + 1
            panel.deleteLater()
            app.processEvents()

        # VegaLauncher._on_profile_item_clicked guard
        dummy = MagicMock(spec=VegaLauncher)
        dummy._active_selected_profile_id = "pid1"
        dummy.sound_mgr = MagicMock()
        dummy.on_profile_selected = MagicMock()
        item = QListWidgetItem()
        item.setData(Qt.UserRole, "pid1")

        VegaLauncher._on_profile_item_clicked(dummy, item)
        dummy.sound_mgr.play_click.assert_not_called()
        dummy.on_profile_selected.assert_not_called()

    def test_edit_profile_dialog_preset_guards_and_server_save_guard(self):
        dlg = EditProfileDialog("TestProf", 4096, "⚔️", "nether")
        with patch.object(SoundManager.get_instance(), "play_click") as mock_click:
            dlg._select_preset_banner("nether")
            mock_click.assert_not_called()
            dlg._select_preset_banner("end")
            mock_click.assert_called_once()

            mock_click.reset_mock()
            dlg._select_preset_icon("⚔️", None)
            mock_click.assert_not_called()
            dlg._select_preset_icon("🪄", None)
            mock_click.assert_called_once()
        dlg.deleteLater()
        app.processEvents()

        with tempfile.TemporaryDirectory() as tmpdir:
            sw = MagicMock(spec=ServerWidget)
            sw.lang = "tr"
            sw.server_dir = tmpdir
            sw._last_saved_props = None
            sw.spin_max_players = MagicMock(value=MagicMock(return_value=20))
            sw.spin_view_distance = MagicMock(value=MagicMock(return_value=10))
            sw.combo_difficulty = MagicMock(currentText=MagicMock(return_value="easy"))
            sw.chk_crack = MagicMock(isChecked=MagicMock(return_value=False))
            sw.chk_pvp = MagicMock(isChecked=MagicMock(return_value=True))
            sw.line_seed = MagicMock(text=MagicMock(return_value=""))
            sw.line_level_name = MagicMock(text=MagicMock(return_value="world"))
            sw.combo_gamemode = MagicMock(currentText=MagicMock(return_value="survival"))
            sw.line_motd = MagicMock(text=MagicMock(return_value="A Minecraft Server"))
            sw.spin_spawn_protection = MagicMock(value=MagicMock(return_value=16))
            sw.spin_sim_distance = MagicMock(value=MagicMock(return_value=10))
            from server_widget import ServerInstance
            sw._get_server_instance.side_effect = lambda: ServerInstance(tmpdir)

            ServerWidget.save_server_properties(sw)
            self.assertEqual(sw.log.call_count, 1)
            # Second save with identical properties is a no-op
            ServerWidget.save_server_properties(sw)
            self.assertEqual(sw.log.call_count, 1)

    def test_sound_cooldown_safe_open_path_and_app_updater_single_flight(self):
        sm = SoundManager.get_instance()
        sm._last_sound_times.clear()
        fake_effect = MagicMock()
        with patch.object(sm, "_enabled", True), patch.dict(sm._effects, {"pop": fake_effect}):
            sm.play("pop")
            sm.play("pop")
            self.assertEqual(fake_effect.play.call_count, 1)
            sm._last_sound_times.clear()
            sm.play("pop")
            self.assertEqual(fake_effect.play.call_count, 2)
        sm._last_sound_times.clear()

        ui_components._LAST_OPEN_TIMES.clear()
        with patch("ui_components.os.startfile", create=True) as mock_startfile:
            self.assertTrue(safe_open_path("C:\\fake_dir", cooldown=1.0))
            self.assertFalse(safe_open_path("C:\\fake_dir", cooldown=1.0))
            self.assertEqual(mock_startfile.call_count, 1)

        mock_win = MagicMock()
        mock_win.settings = {"language": "tr"}
        updater = AppUpdater(mock_win, "2.0.1")
        running_thread = MagicMock()
        running_thread.isRunning.return_value = True
        updater._last_check_thread = running_thread
        self.assertFalse(updater.check(manual=True))

    def test_mod_download_invalidates_active_profile_and_cross_tab_card_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mods_dir = os.path.join(tmpdir, "mods")
            os.makedirs(mods_dir, exist_ok=True)
            dummy = MagicMock(spec=VegaLauncher)
            dummy.settings = {"language": "tr"}
            dummy._active_selected_profile_id = "pid1"
            dummy.detail_panel = MagicMock()
            dummy.dl_thread = None
            dummy.sound_mgr = MagicMock()
            dummy.statusBar = MagicMock()
            dummy.installed_mods_panel = MagicMock()
            dummy.get_selected_profile.return_value = ("pid1", {"name": "P1", "version": "1.20.1", "path": tmpdir})

            with patch("main.QMessageBox.information"):
                VegaLauncher.on_download_finished(dummy, True, "Done")
            self.assertIsNone(dummy._active_selected_profile_id)
            dummy.installed_mods_panel.load_mods.assert_called_once()

        # Cross-tab card selection mismatch clears stale selection so card can be clicked again
        dummy_tab = MagicMock(spec=VegaLauncher)
        dummy_tab._current_tab_key = "mods"
        dummy_tab.nav_bar = MagicMock()
        dummy_tab.stack = MagicMock()
        dummy_tab.isMinimized.return_value = False
        dummy_tab._is_game_running = False
        dummy_tab.particle_overlay = None
        dummy_tab.pack_browser = MagicMock()
        card_a = MagicMock()
        card_a.data = {"project_id": "pack_a"}
        dummy_tab.pack_browser.selected_card = card_a
        dummy_tab.detail_panel = MagicMock()
        dummy_tab.detail_panel.current_project = {"project_id": "mod_b"}
        dummy_tab.right_stack = MagicMock()
        dummy_tab.right_stack.isVisible.return_value = True
        dummy_tab.right_stack.currentWidget.return_value = dummy_tab.detail_panel

        VegaLauncher.switch_tab(dummy_tab, "packs")
        dummy_tab.pack_browser.clear_selection.assert_called_once()
        dummy_tab.right_stack.hide.assert_called_once()

    def test_fast_game_exit_before_1500ms_and_cli_pending_launch_guard(self):
        dummy = MagicMock(spec=VegaLauncher)
        dummy.settings = {"language": "tr"}
        dummy._is_launching = False
        dummy._is_game_running = False  # Already closed before 1500ms timer fired
        dummy.action_bar = MagicMock()
        VegaLauncher.on_game_started(dummy)
        self.assertFalse(dummy._is_game_running)
        dummy.action_bar.play_btn.setText.assert_not_called()

        # handle_cli_args blocks second --launch while _cli_launch_pending is True
        mock_win = MagicMock()
        mock_win._is_launching = False
        mock_win._is_game_running = False
        mock_win._cli_launch_pending = False
        mock_win._get_profile_item.return_value = MagicMock()
        with patch("main.QTimer.singleShot") as mock_timer:
            handle_cli_args(mock_win, ["--launch", "pack_a"])
            self.assertTrue(mock_win._cli_launch_pending)
            handle_cli_args(mock_win, ["--launch", "pack_b"])
            self.assertEqual(mock_timer.call_count, 1)


if __name__ == "__main__":
    unittest.main()

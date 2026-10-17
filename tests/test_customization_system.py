import unittest
import os
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QWidget

# Ensure single QApplication instance for Qt widgets
app = QApplication.instance()
if not app:
    app = QApplication([])

import theme_manager
from sound_manager import (
    SoundManager,
    generate_click_wav,
    generate_launch_wav,
    generate_levelup_wav,
    generate_error_wav,
    generate_door_open_wav,
    generate_door_close_wav,
    generate_lever_on_wav,
    generate_lever_off_wav
)
from particle_overlay import ParticleOverlay
from card_widget import CardWidget
from ui_components import InstalledModsPanel, NavBar, ActionBar
from server_widget import ServerWidget
from PySide6.QtCore import QEvent
from PySide6.QtGui import QShowEvent


class TestCustomizationSystem(unittest.TestCase):
    def tearDown(self):
        app.processEvents()

    # ==================== THEME MANAGER TESTS ====================

    def test_themes_definition_and_completeness(self):
        expected_themes = [
            "electric_amethyst",
            "ender_pearl",
            "nether_crimson",
            "emerald_lush",
            "sculk_dark"
        ]
        for theme_key in expected_themes:
            self.assertIn(theme_key, theme_manager.THEMES)
            theme = theme_manager.get_theme(theme_key)
            self.assertIsNotNone(theme)
            self.assertIn("name_tr", theme)
            self.assertIn("name_en", theme)
            self.assertIn("primary", theme)
            self.assertIn("primary_light", theme)
            self.assertIn("glow", theme)
            self.assertIn("gradient_start", theme)
            self.assertIn("pressed", theme)
            self.assertIn("secondary", theme)
            self.assertIn("secondary_light", theme)
            self.assertIn("text_tint", theme)
            self.assertIn("particles", theme)
            self.assertIn("rgb", theme)
            self.assertIn("grad_start_rgb", theme)
            self.assertIn("glow_rgb", theme)
            self.assertIn("secondary_rgb", theme)
            self.assertIsInstance(theme["particles"], list)
            self.assertTrue(len(theme["particles"]) >= 2)

    def test_theme_fallback(self):
        fallback = theme_manager.get_theme("non_existent_theme_xyz")
        default = theme_manager.get_theme("electric_amethyst")
        self.assertEqual(fallback["name_tr"], default["name_tr"])
        self.assertEqual(fallback["primary"], default["primary"])

    def test_banner_presets_completeness(self):
        expected_presets = [
            "end_void",
            "nether_fortress",
            "lush_caves",
            "deep_dark",
            "cyber_void"
        ]
        for preset_key in expected_presets:
            self.assertIn(preset_key, theme_manager.BANNER_PRESETS)
            preset = theme_manager.get_banner_preset(preset_key)
            self.assertIn("name_tr", preset)
            self.assertIn("name_en", preset)
            self.assertIn("gradient", preset)
            self.assertIn("accent", preset)

        # Fallback test
        fallback = theme_manager.get_banner_preset("unknown_preset")
        self.assertEqual(fallback["accent"], theme_manager.BANNER_PRESETS["end_void"]["accent"])

    def test_generate_theme_qss_replacement(self):
        raw_qss = (
            "QPushButton { background: #8B5CF6; border-color: #A855F7; color: #E9D5FF; }\n"
            "QProgressBar::chunk { background: qlineargradient(stop:0 #8B5CF6, stop:1 #06B6D4); }\n"
            "QFrame { background: rgba(139, 92, 246, 0.15); border: 1px solid rgba(6, 182, 212, 0.3); }"
        )
        # Transform to Ender Pearl
        transformed = theme_manager.generate_theme_qss(raw_qss, "ender_pearl")
        theme = theme_manager.get_theme("ender_pearl")
        
        # Primary of ender pearl is #06B6D4
        self.assertIn(theme["primary"], transformed)
        self.assertIn(theme["primary_light"], transformed)
        self.assertIn(theme["secondary"], transformed)
        self.assertIn(f"rgba({theme['rgb'][0]}, {theme['rgb'][1]}, {theme['rgb'][2]},", transformed)
        self.assertIn(f"rgba({theme['secondary_rgb'][0]}, {theme['secondary_rgb'][1]}, {theme['secondary_rgb'][2]},", transformed)

    def test_two_phase_placeholder_collision_safety(self):
        # Ender Pearl primary is #06B6D4, which is Electric Amethyst's secondary (#06B6D4).
        # Electric Amethyst primary is #8B5CF6, which is Ender Pearl's secondary (#8B5CF6).
        # A naive direct string replace of #8B5CF6 -> #06B6D4 followed by #06B6D4 -> #8B5CF6
        # would clobber both back into #8B5CF6!
        # With two-phase placeholder substitution, former #8B5CF6 becomes #06B6D4 and former #06B6D4 becomes #8B5CF6.
        raw_qss = "color_one: #8B5CF6; color_two: #06B6D4;"
        transformed = theme_manager.generate_theme_qss(raw_qss, "ender_pearl")
        self.assertIn("color_one: #06B6D4;", transformed)
        self.assertIn("color_two: #8B5CF6;", transformed)

    def test_get_theme_names(self):
        names_tr = theme_manager.get_theme_names("tr")
        names_en = theme_manager.get_theme_names("en")
        self.assertEqual(len(names_tr), 5)
        self.assertEqual(len(names_en), 5)
        self.assertEqual(names_tr[0][0], "electric_amethyst")
        self.assertIn("Elektrik", names_tr[0][1])
        self.assertIn("Electric", names_en[0][1])

    # ==================== SOUND MANAGER TESTS ====================

    def test_sound_manager_init_and_toggle(self):
        sm = SoundManager()
        self.assertTrue(sm.is_enabled())
        sm.set_enabled(False)
        self.assertFalse(sm.is_enabled())
        sm.set_volume(85)
        self.assertEqual(sm.get_volume(), 85)

    def test_sound_manager_playback_safety(self):
        sm = SoundManager()
        sm.set_enabled(False)
        try:
            sm.play_click()
            sm.play_launch()
            sm.play_levelup()
            sm.play_error()
            sm.play_door_open()
            sm.play_door_close()
            sm.play_teleport()
            sm.play_lever_on()
            sm.play_lever_off()
            sm.play_lever(True)
            sm.play_lever(False)
        except Exception as e:
            self.fail(f"SoundManager playback raised exception when disabled: {e}")

        sm.set_enabled(True)
        try:
            sm.play_click()
            sm.play_launch()
            sm.play_levelup()
            sm.play_error()
            sm.play_door_open()
            sm.play_door_close()
            sm.play_teleport()
            sm.play_lever_on()
            sm.play_lever_off()
            sm.play_lever(True)
            sm.play_lever(False)
        except Exception as e:
            self.fail(f"SoundManager playback raised exception when enabled: {e}")

    def test_sound_generators_produce_valid_wavs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            click_path = os.path.join(tmpdir, "test_click.wav")
            launch_path = os.path.join(tmpdir, "test_launch.wav")
            levelup_path = os.path.join(tmpdir, "test_levelup.wav")
            error_path = os.path.join(tmpdir, "test_error.wav")
            door_open_path = os.path.join(tmpdir, "test_door_open.wav")
            door_close_path = os.path.join(tmpdir, "test_door_close.wav")
            lever_on_path = os.path.join(tmpdir, "test_lever_on.wav")
            lever_off_path = os.path.join(tmpdir, "test_lever_off.wav")

            generate_click_wav(click_path)
            generate_launch_wav(launch_path)
            generate_levelup_wav(levelup_path)
            generate_error_wav(error_path)
            generate_door_open_wav(door_open_path)
            generate_door_close_wav(door_close_path)
            generate_lever_on_wav(lever_on_path)
            generate_lever_off_wav(lever_off_path)

            for path in [click_path, launch_path, levelup_path, error_path, door_open_path, door_close_path, lever_on_path, lever_off_path]:
                self.assertTrue(os.path.exists(path))
                self.assertTrue(os.path.getsize(path) > 44)
                with wave.open(path, "rb") as wf:
                    self.assertEqual(wf.getnchannels(), 1)
                    self.assertEqual(wf.getsampwidth(), 2)
                    self.assertEqual(wf.getframerate(), 44100)
                    self.assertTrue(wf.getnframes() > 0)

    # ==================== PARTICLE OVERLAY TESTS ====================

    def test_particle_overlay_lifecycle_and_pause_resume(self):
        parent = QWidget()
        overlay = ParticleOverlay(parent)
        self.assertFalse(overlay._is_paused)
        self.assertTrue(overlay.timer.isActive())

        # Test pause (Smart Performance Mode)
        overlay.pause()
        self.assertTrue(overlay._is_paused)
        self.assertFalse(overlay.timer.isActive(), "Timer must be stopped when paused to guarantee 0% CPU")

        # Test resume
        overlay.resume()
        self.assertFalse(overlay._is_paused)
        self.assertTrue(overlay.timer.isActive())

        # Test disable
        overlay.set_enabled(False)
        self.assertFalse(overlay.timer.isActive())
        self.assertFalse(overlay.is_enabled())

        overlay.set_enabled(True)
        self.assertTrue(overlay.timer.isActive())
        self.assertTrue(overlay.is_enabled())

    def test_particle_overlay_theme_palette(self):
        parent = QWidget()
        overlay = ParticleOverlay(parent)
        ender_theme = theme_manager.get_theme("ender_pearl")
        overlay.set_palette(ender_theme["particles"])
        self.assertEqual(len(overlay.palette), len(ender_theme["particles"]))

    # ==================== COMPONENT THEMING TESTS ====================

    def test_card_widget_theming(self):
        data = {
            "title": "All The Mods 9",
            "author": "ATM Team",
            "description": "Heavy modpack with lots of tech and magic.",
            "downloads": 5400000,
            "follows": 12000,
            "updated": "2026-03-01T12:00:00Z",
            "versions": ["1.20.1"],
            "loaders": ["forge"],
            "categories": ["Tech", "Magic"],
            "client_side": "required",
            "server_side": "required",
            "project_type": "modpack",
            "icon_url": ""
        }
        card = CardWidget(data)
        
        # Test default theme (Electric Amethyst)
        card.set_selected(True)
        self.assertIn("#C084FC", card.styleSheet())

        # Test switching to Nether Crimson
        card.set_theme("nether_crimson")
        nether = theme_manager.get_theme("nether_crimson")
        self.assertIn(nether["glow"], card.styleSheet())
        self.assertEqual(card._active_theme, "nether_crimson")

        # Test switching to Sculk Dark
        card.set_theme("sculk_dark")
        sculk = theme_manager.get_theme("sculk_dark")
        self.assertIn(sculk["glow"], card.styleSheet())
        self.assertEqual(card._active_theme, "sculk_dark")

    def test_installed_mods_panel_theming(self):
        panel = InstalledModsPanel()
        panel.set_theme("emerald_lush")
        self.assertEqual(panel._active_theme, "emerald_lush")
        emerald = theme_manager.get_theme("emerald_lush")
        # Active sub-tab button has emerald theme colors
        active_btn = panel.sub_tab_btns[panel.sub_stack.currentIndex()]
        self.assertIn(emerald["primary_light"], active_btn.styleSheet())

    def test_navbar_theming(self):
        navbar = NavBar()
        navbar.set_theme("sculk_dark")
        self.assertEqual(navbar._active_theme, "sculk_dark")
        sculk = theme_manager.get_theme("sculk_dark")
        self.assertIn(sculk["primary_light"], navbar.game_selector.styleSheet())

    def test_action_bar_theming(self):
        action_bar = ActionBar()
        action_bar.set_theme("ender_pearl")
        self.assertEqual(action_bar._active_theme, "ender_pearl")
        ender = theme_manager.get_theme("ender_pearl")
        self.assertIn(ender["glow"], action_bar.badge_ver.styleSheet())

        action_bar.set_theme("nether_crimson")
        self.assertEqual(action_bar._active_theme, "nether_crimson")
        nether = theme_manager.get_theme("nether_crimson")
        self.assertIn(nether["glow"], action_bar.badge_ver.styleSheet())

    def test_server_widget_theming(self):
        server_widget = ServerWidget()
        server_widget.set_theme("emerald_lush")
        self.assertEqual(server_widget._active_theme, "emerald_lush")
        emerald = theme_manager.get_theme("emerald_lush")
        for sub_lbl in server_widget.summary_card_subs:
            self.assertIn(emerald["glow"], sub_lbl.styleSheet())

    def test_sound_manager_singleton_and_cross_module(self):
        sm1 = SoundManager.get_instance()
        sm2 = SoundManager.get_instance()
        self.assertIs(sm1, sm2)

        import server_widget as sw
        import server_downloader as sd
        self.assertIs(sw.SoundManager.get_instance(), sm1)
        self.assertIs(sd.SoundManager.get_instance(), sm1)

    def test_vega_launcher_smart_performance_and_theme_propagation(self):
        import unittest.mock as mock
        from main import VegaLauncher
        with tempfile.TemporaryDirectory() as tmp_dir, \
             mock.patch("main.ProjectDetailsThread"), \
             mock.patch("main.ModrinthSearchThread"):
            launcher = VegaLauncher(data_dir=tmp_dir)
            self.assertFalse(launcher._is_game_running)
            # Before show(), window is hidden, so overlay pauses automatically (0% CPU)
            self.assertFalse(launcher.particle_overlay.timer.isActive())

            launcher.show()
            self.assertTrue(launcher.particle_overlay.timer.isActive())

            # Smart Performance: game running lock
            launcher._is_game_running = True
            launcher.particle_overlay.pause()
            self.assertFalse(launcher.particle_overlay.timer.isActive())

            # Unminimize or focus events while game running MUST NOT restart particles
            launcher.changeEvent(QEvent(QEvent.Type.ActivationChange))
            self.assertFalse(launcher.particle_overlay.timer.isActive(), "Particles must remain stopped while game is running")
            launcher.showEvent(QShowEvent())
            self.assertFalse(launcher.particle_overlay.timer.isActive(), "Particles must remain stopped while game is running")

            # Game ends
            launcher._is_game_running = False
            launcher.changeEvent(QEvent(QEvent.Type.ActivationChange))
            self.assertTrue(launcher.particle_overlay.timer.isActive(), "Particles should resume once game is closed and window is active")

            # Dynamic theme propagation across all launcher components
            launcher.apply_theme("sculk_dark")
            self.assertEqual(launcher.action_bar._active_theme, "sculk_dark")
            self.assertEqual(launcher.server_page._active_theme, "sculk_dark")
            self.assertEqual(launcher.nav_bar._active_theme, "sculk_dark")
            self.assertEqual(launcher.installed_mods_panel._active_theme, "sculk_dark")

            launcher.close()

    def test_authentic_minecraft_particle_presets(self):
        parent = QWidget()
        overlay = ParticleOverlay(parent)
        for preset in ParticleOverlay.PRESETS:
            overlay.set_preset(preset)
            self.assertEqual(overlay.get_preset(), preset)
            self.assertTrue(len(overlay._active_sprites) > 0, f"Preset {preset} should have loaded sprites")

    def test_settings_persistence_and_defaults(self):
        import unittest.mock as mock
        from main import VegaLauncher, DEFAULT_SETTINGS
        with tempfile.TemporaryDirectory() as tmp_dir, \
             mock.patch("main.ProjectDetailsThread"), \
             mock.patch("main.ModrinthSearchThread"):
            launcher = VegaLauncher(data_dir=tmp_dir)
            # Verify DEFAULT_SETTINGS has all keys
            required_keys = [
                "language", "window_size", "on_launch", "default_ram",
                "java_path", "jvm_args", "theme", "particles_enabled",
                "particle_preset", "particle_opacity", "sound_enabled", "sound_volume"
            ]
            for rk in required_keys:
                self.assertIn(rk, DEFAULT_SETTINGS)
                self.assertIn(rk, launcher.settings)

            # Change particle preset in UI
            idx = launcher.combo_particle_preset.findData("runes")
            self.assertTrue(idx >= 0)
            launcher.combo_particle_preset.setCurrentIndex(idx)
            self.assertEqual(launcher.settings.get("particle_preset"), "runes")
            self.assertEqual(launcher.particle_overlay.get_preset(), "runes")

            # Change particle opacity in UI
            launcher.slider_particle_opacity.setValue(35)
            self.assertEqual(launcher.settings.get("particle_opacity"), 35)
            self.assertEqual(launcher.particle_overlay.get_opacity_percent(), 35)

            # Change sound toggle
            launcher.check_sounds.setChecked(False)
            self.assertEqual(launcher.settings.get("sound_enabled"), False)

            # Change sound volume
            launcher.slider_volume.setValue(85)
            self.assertEqual(launcher.settings.get("sound_volume"), 85)

            # Verify settings are saved in config file
            with open(launcher.config_file, "r", encoding="utf-8") as f:
                import json
                saved_cfg = json.load(f)
            saved_settings = saved_cfg.get("settings", {})
            self.assertEqual(saved_settings.get("particle_preset"), "runes")
            self.assertEqual(saved_settings.get("particle_opacity"), 35)
            self.assertEqual(saved_settings.get("sound_enabled"), False)
            self.assertEqual(saved_settings.get("sound_volume"), 85)

            launcher.close()

    def test_sound_enabled_remembers_across_restarts_and_translations(self):
        import unittest.mock as mock
        from main import VegaLauncher
        with tempfile.TemporaryDirectory() as tmp_dir, \
             mock.patch("main.ProjectDetailsThread"), \
             mock.patch("main.ModrinthSearchThread"):
            # Launch 1: Default state is True
            launcher1 = VegaLauncher(data_dir=tmp_dir)
            self.assertTrue(launcher1.check_sounds.isChecked())
            self.assertTrue(launcher1.settings.get("sound_enabled"))

            # Switch language to English and ensure checkbox remains checked
            launcher1.apply_language("en")
            self.assertTrue(launcher1.check_sounds.isChecked())
            self.assertEqual(launcher1.check_sounds.text(), "UI & Alert Sound Effects")

            # Trigger general settings change and verify state persists
            launcher1._on_settings_changed()
            self.assertTrue(launcher1.settings.get("sound_enabled"))
            launcher1.close()

            # Launch 2: Verify state remembered as True across fresh startup
            launcher2 = VegaLauncher(data_dir=tmp_dir)
            self.assertTrue(launcher2.settings.get("sound_enabled"))
            self.assertTrue(launcher2.check_sounds.isChecked())

            # Turn off sounds explicitly
            launcher2.check_sounds.setChecked(False)
            self.assertFalse(launcher2.settings.get("sound_enabled"))
            self.assertFalse(launcher2.check_sounds.isChecked())
            launcher2.close()

            # Launch 3: Verify turned-off state remembered across fresh startup
            launcher3 = VegaLauncher(data_dir=tmp_dir)
            self.assertFalse(launcher3.settings.get("sound_enabled"))
            self.assertFalse(launcher3.check_sounds.isChecked())
            launcher3.close()

    # ==================== ANTI-SLOP & UI MODERNIZATION TESTS ====================

    def test_mod_display_name_formatting(self):
        from ui_components import _format_mod_display_name
        test_cases = [
            ("AmbientSounds_FABRIC_v6.1.4_mc1.20.1.jar", "Ambient Sounds", "Fabric", "1.20.1"),
            ("sodium-fabric-0.5.11+mc1.20.1.jar", "Sodium", "Fabric", "1.20.1"),
            ("iris-1.7.0+mc1.20.1.jar", "Iris", "", "1.20.1"),
            ("fabric-api-0.92.2+1.20.1.jar", "Fabric API", "", "1.20.1"),
            ("RoughlyEnoughItems-12.0.684-fabric.jar", "Roughly Enough Items", "Fabric", ""),
            ("appleskin-fabric-mc1.20.1-2.5.1.jar", "Appleskin", "Fabric", "1.20.1"),
            ("dungeons_pack.pak", "Dungeons Pack", "", ""),
            ("simplemod.jar", "Simplemod", "", ""),
        ]
        for filename, exp_title, exp_loader, exp_mc in test_cases:
            title, subtitle = _format_mod_display_name(filename)
            self.assertEqual(title, exp_title, f"Failed for {filename}")
            if exp_loader:
                self.assertIn(exp_loader, subtitle, f"Loader {exp_loader} not in {subtitle}")
            if exp_mc:
                self.assertIn(exp_mc, subtitle, f"MC version {exp_mc} not in {subtitle}")

    def test_mod_item_widget_clean_layout_and_toggle(self):
        from ui_components import ModItemWidget
        with tempfile.TemporaryDirectory() as tmp_dir:
            mod_file = os.path.join(tmp_dir, "sodium-fabric-0.5.11+mc1.20.1.jar")
            with open(mod_file, "w") as f:
                f.write("dummy")

            widget = ModItemWidget(mod_file, parent_list=None, lang="tr")
            self.assertEqual(widget.name_lbl.text(), "Sodium")
            self.assertIn("Fabric", widget.sub_lbl.text())
            self.assertIn(widget.toggle_btn.text(), ("AÇIK", "Açık", "● Açık"))
            self.assertFalse(widget.is_disabled)

            # Toggle off
            widget.toggle_mod()
            self.assertTrue(widget.is_disabled)
            self.assertIn(widget.toggle_btn.text(), ("KAPALI", "Kapalı", "○ Kapalı"))
            self.assertTrue(widget.filepath.endswith(".disabled"))

            # Toggle back on
            widget.toggle_mod()
            self.assertFalse(widget.is_disabled)
            self.assertIn(widget.toggle_btn.text(), ("AÇIK", "Açık", "● Açık"))
            self.assertFalse(widget.filepath.endswith(".disabled"))

    def test_profile_widget_clean_typography(self):
        from main import ProfileWidget
        pw = ProfileWidget("My Profile", "1.20.1", 4096, "prof_123", icon="🎮", lang="tr")
        self.assertIsNotNone(pw)
        self.assertEqual(pw.profile_id, "prof_123")
        pw.set_language("en")
        self.assertEqual(pw.update_btn.text(), "Update")

    def test_action_bar_badge_separators(self):
        from ui_components import ActionBar
        ab = ActionBar()
        ab.set_profile_badges("1.20.1", "fabric", 4096)
        self.assertFalse(ab.badge_ver.isHidden())
        self.assertFalse(ab.badge_loader.isHidden())
        self.assertFalse(ab.badge_ram.isHidden())
        self.assertFalse(ab.badge_sep1.isHidden())
        self.assertFalse(ab.badge_sep2.isHidden())

        # When cleared / no profile
        ab.set_profile_badges("", "", "")
        self.assertTrue(ab.badge_ver.isHidden())
        self.assertTrue(ab.badge_sep1.isHidden())


if __name__ == "__main__":
    unittest.main()


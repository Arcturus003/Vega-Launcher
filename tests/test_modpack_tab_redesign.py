import unittest
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

# Ensure single QApplication instance for Qt widgets
app = QApplication.instance()
if not app:
    app = QApplication([])

from card_widget import CardWidget, format_number
from mod_manager import ModrinthAPI
from main import DetailPanel, ModrinthBrowser, EndermanInstallModal


class TestModpackTabRedesign(unittest.TestCase):
    def tearDown(self):
        app.processEvents()

    def test_format_number(self):
        self.assertEqual(format_number(0), "0")
        self.assertEqual(format_number(None), "0")
        self.assertEqual(format_number(""), "0")
        self.assertEqual(format_number(420), "420")
        self.assertEqual(format_number(1000), "1.0K")
        self.assertEqual(format_number(12500), "12.5K")
        self.assertEqual(format_number(4200000), "4.2M")

    def test_card_widget_rich_display_and_selection(self):
        data = {
            "title": "Fabulously Optimized",
            "author": "Robotkoer",
            "description": "Simple pack focusing on FPS and performance.",
            "downloads": 4250000,
            "follows": 15800,
            "categories": ["fabric", "optimization", "shaders"],
            "versions": ["1.20.1", "1.20.4", "1.21.1"]
        }
        card = CardWidget(data)
        self.assertEqual(card.title.text(), "Fabulously Optimized")
        self.assertEqual(card.author_lbl.text(), "by Robotkoer")
        self.assertFalse(card.author_lbl.isHidden())
        self.assertEqual(card.downloads_lbl.text(), "4.2M")
        self.assertEqual(card.follows_lbl.text(), "15.8K")
        self.assertIn("v 1.21.1", card.version.text())
        
        # Test selection toggle
        self.assertFalse(card.is_selected)
        card.set_selected(True)
        self.assertTrue(card.is_selected)
        self.assertIn("#C084FC", card.styleSheet())
        
        card.set_selected(False)
        self.assertFalse(card.is_selected)
        self.assertNotIn("#C084FC", card.styleSheet())
        self.assertIn("#1A1A1E", card.styleSheet())

        # Test hover state
        from PySide6.QtCore import QEvent
        card.enterEvent(QEvent(QEvent.Enter))
        self.assertTrue(card.is_hovered)
        self.assertIn("#212128", card.styleSheet())
        card.leaveEvent(QEvent(QEvent.Leave))
        self.assertFalse(card.is_hovered)
        self.assertIn("#1A1A1E", card.styleSheet())

    def test_detail_panel_ram_presets_and_signals(self):
        panel = DetailPanel()
        
        # Default RAM
        self.assertEqual(panel.selected_ram, 6144)
        
        # Change RAM
        panel.set_ram(4096)
        self.assertEqual(panel.selected_ram, 4096)
        
        panel.set_ram(8192)
        self.assertEqual(panel.selected_ram, 8192)
        
        # Test drawer_closed signal
        closed_emitted = []
        panel.drawer_closed.connect(lambda: closed_emitted.append(True))
        panel.close_drawer()
        self.assertTrue(closed_emitted)
        self.assertFalse(panel.isVisible())

    def test_detail_panel_update_and_download_payload(self):
        panel = DetailPanel()
        panel.set_ram(8192)
        mock_data = {
            "project_id": "test_pack",
            "project_type": "modpack",
            "title": "Test Modpack",
            "author": "Tester",
            "description": "Test description",
            "downloads": 5000,
            "follows": 200,
            "categories": ["fabric"]
        }
        import unittest.mock as mock
        with mock.patch("main.ProjectDetailsThread") as mock_thread_cls:
            mock_thread = mock.MagicMock()
            mock_thread.isRunning.return_value = False
            mock_thread_cls.return_value = mock_thread
            panel.update_info(mock_data)
        self.assertEqual(panel.title.text(), "Test Modpack")
        self.assertEqual(panel.author_lbl.text(), "by Tester")
        
        # Simulate versions loaded
        details_with_versions = {
            "title": "Test Modpack",
            "description": "Full description",
            "versions_list": [
                {
                    "id": "ver_1",
                    "name": "1.0.0",
                    "version_number": "1.0.0",
                    "game_versions": ["1.20.1"],
                    "loaders": ["fabric"],
                    "files": [{"url": "http://example.com/pack.mrpack", "primary": True}]
                }
            ]
        }
        panel.on_details_loaded(details_with_versions)
        self.assertEqual(panel.version_combo.count(), 1)
        self.assertIn("1.0.0", panel.version_combo.itemText(0))
        
        # Test download requested emission contains selected_ram and selected_version_obj
        emitted_payloads = []
        panel.download_requested.connect(lambda p: emitted_payloads.append(p))
        panel.on_download_click()
        
        self.assertEqual(len(emitted_payloads), 1)
        payload = emitted_payloads[0]
        self.assertEqual(payload["selected_ram"], 8192)
        self.assertIsNotNone(payload.get("selected_version_obj"))
        self.assertEqual(payload["selected_version_obj"]["id"], "ver_1")

    def test_modrinth_browser_columns_and_chips(self):
        browser = ModrinthBrowser("modpack")
        
        # Initial columns and layout
        self.assertEqual(browser.columns, 4)
        self.assertFalse(hasattr(browser, "install_local_btn"))
        self.assertEqual(browser.grid_layout.columnStretch(0), 1)
        self.assertEqual(browser.grid_layout.columnStretch(3), 1)
        self.assertTrue(hasattr(browser, "category_chips"))
        
        # Test column switching
        browser.set_columns(3)
        self.assertEqual(browser.columns, 3)
        browser.set_columns(4)
        self.assertEqual(browser.columns, 4)
        
        # Test category chip selection
        # Default category is None
        self.assertIsNone(browser.current_category)
        
        import unittest.mock as mock
        with mock.patch("main.ModrinthSearchThread") as mock_search_cls:
            mock_st = mock.MagicMock()
            mock_st.isRunning.return_value = False
            mock_search_cls.return_value = mock_st
            
            # Find optimization chip
            opt_chip = next(b for c, b in browser.category_chips if c == "optimization")
            browser.on_category_chip_clicked("optimization", opt_chip)
            self.assertEqual(browser.current_category, "optimization")
            
            # Clear category
            all_chip = next(b for c, b in browser.category_chips if c is None)
            browser.on_category_chip_clicked(None, all_chip)
            self.assertIsNone(browser.current_category)

    def test_enderman_install_modal(self):
        modal = EndermanInstallModal("RLCraft", None)
        self.assertEqual(modal.pack_lbl.text(), "RLCraft")
        
        # Test status update
        modal.set_status("Sodium indiriliyor...")
        self.assertEqual(modal.status_lbl.text(), "Sodium indiriliyor...")
        
        # Test progress update
        modal.set_progress(10, 50)
        self.assertEqual(modal.progress_bar.maximum(), 50)
        self.assertEqual(modal.progress_bar.value(), 10)
        self.assertIn("10 / 50 Mod (%20)", modal.counter_lbl.text())
        
        # Test indeterminate progress
        modal.set_progress(0, 0)
        self.assertEqual(modal.progress_bar.maximum(), 0)
        self.assertEqual(modal.counter_lbl.text(), "Hazırlanıyor...")

    def test_modrinth_api_search_facets_with_category(self):
        import unittest.mock as mock
        with mock.patch("requests.get") as mock_get:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = {"hits": []}
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            
            ModrinthAPI.search_projects("test", project_type="modpack", category="optimization")
            
            call_params = mock_get.call_args[1]["params"]
            facets = json.loads(call_params["facets"])
            self.assertIn(["project_type:modpack"], facets)
            self.assertIn(["categories:optimization"], facets)


    def test_card_widget_with_null_and_boundary_data(self):
        # API hit with None values should not raise TypeError
        data = {
            "title": "Edge Case Pack",
            "author": None,
            "description": None,
            "downloads": None,
            "follows": None,
            "categories": None,
            "versions": None
        }
        card = CardWidget(data)
        self.assertEqual(card.downloads_lbl.text(), "0")
        self.assertEqual(card.follows_lbl.text(), "0")
        self.assertEqual(card.version.text(), "v Unknown")
        self.assertTrue(card.author_lbl.isHidden())

    def test_card_widget_selection_hover_style(self):
        card = CardWidget({"title": "Test Pack"})
        card.set_selected(True)
        # Ensure :hover state is defined inside the selected styleSheet to prevent override
        self.assertIn("#ModpackCard:hover", card.styleSheet())
        self.assertIn("border: 2px solid #C084FC", card.styleSheet())

    def test_detail_panel_stale_response_discarded(self):
        panel = DetailPanel()
        panel.current_project = {"project_id": "proj_B", "slug": "pack-b", "title": "Pack B"}
        
        # Simulate stale response from previously clicked Pack A
        stale_details = {
            "id": "proj_A",
            "slug": "pack-a",
            "title": "Pack A",
            "description": "Pack A description",
            "versions_list": [{"id": "ver_A"}]
        }
        panel.on_details_loaded(stale_details)
        
        # DetailPanel should discard stale response and NOT overwrite Pack B
        self.assertNotEqual(panel.title.text(), "Pack A")
        self.assertEqual(panel.version_combo.count(), 0)

    def test_detail_panel_stale_gallery_image_discarded(self):
        panel = DetailPanel()
        panel.current_project = {"project_id": "proj_B", "slug": "pack-b"}
        panel._current_gallery_urls = {"http://example.com/b1.jpg"}
        
        # Stale image from Pack A
        from PySide6.QtGui import QPixmap, QImage
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
        img = QImage(32, 32, QImage.Format_RGB32)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        
        panel.on_image_loaded("http://example.com/a_old.jpg", ba.data())
        self.assertEqual(panel.thumb_layout.count(), 0)
        
        # Valid image for Pack B
        panel.on_image_loaded("http://example.com/b1.jpg", ba.data())
        self.assertEqual(panel.thumb_layout.count(), 1)

    def test_modrinth_browser_selection_cleared_on_grid_clear(self):
        browser = ModrinthBrowser("modpack")
        browser.set_columns(3)
        mock_card = CardWidget({"title": "Card 1"})
        browser.cards = [mock_card]
        browser.selected_card = mock_card
        
        cleared_emitted = []
        browser.selection_cleared.connect(lambda: cleared_emitted.append(True))
        
        browser.clear_grid()
        self.assertTrue(cleared_emitted)
        self.assertEqual(browser.columns, 4)
        self.assertIsNone(browser.selected_card)

    def test_modrinth_api_get_project_versions_filters(self):
        import unittest.mock as mock
        with mock.patch("requests.get") as mock_get:
            mock_resp = mock.MagicMock()
            mock_resp.json.return_value = [{"id": "v1"}]
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            
            res = ModrinthAPI.get_project_versions("test_pack", game_version="1.20.1", loader="fabric")
            self.assertEqual(len(res), 1)
            params = mock_get.call_args[1]["params"]
            self.assertIn("1.20.1", params["game_versions"])
            self.assertIn("fabric", params["loaders"])

    def test_local_modpack_archive_name_preserves_dots(self):
        test_path = "C:/Downloads/All.The.Mods.9-v1.0.4.mrpack"
        base_name = os.path.splitext(os.path.basename(test_path))[0]
        self.assertEqual(base_name, "All.The.Mods.9-v1.0.4")

    def test_vega_launcher_drawer_reflow_integration(self):
        import tempfile
        from main import VegaLauncher
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as tmp_dir, \
             mock.patch("main.ProjectDetailsThread") as mock_dt, \
             mock.patch("main.ModrinthSearchThread") as mock_st:
            launcher = VegaLauncher(data_dir=tmp_dir)
            launcher.switch_tab("packs")
            self.assertEqual(launcher.pack_browser.columns, 4)
            self.assertTrue(launcher.right_stack.isHidden())

            # Select a card
            data = {"project_id": "test_proj", "title": "Test Pack", "author": "Tester"}
            launcher.on_browser_item_selected(data)
            self.assertEqual(launcher.pack_browser.columns, 3)
            self.assertFalse(launcher.right_stack.isHidden())

            # Close drawer
            launcher.detail_panel.close_drawer()
            self.assertEqual(launcher.pack_browser.columns, 4)
            self.assertTrue(launcher.right_stack.isHidden())
            launcher.close()

    def test_combobox_and_cards_are_not_top_level_windows(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget
        browser = ModrinthBrowser("modpack")
        # Ensure comboboxes and category chips are not top-level windows
        for cb in (browser.sort_combo, browser.version_combo, browser.loader_combo):
            self.assertFalse(cb.isWindow())
            self.assertEqual(cb.parent(), browser)
        for _, chip in browser.category_chips:
            self.assertFalse(chip.isWindow())
            self.assertEqual(chip.parent(), browser)

        # Ensure populated CardWidget and all child elements (tags, badges, etc.) are not top-level windows
        sample_data = [{"title": "P1", "author": "A1", "categories": ["adventure", "fps"]}, {"title": "P2", "author": "A2", "categories": ["magic"]}]
        browser.populate(sample_data)
        self.assertEqual(len(browser.cards), 2)
        for card in browser.cards:
            self.assertFalse(card.isWindow())
            self.assertEqual(card.parent(), browser.grid_container)
            for child in card.findChildren(QWidget):
                self.assertFalse(child.isWindow())


if __name__ == "__main__":
    unittest.main()

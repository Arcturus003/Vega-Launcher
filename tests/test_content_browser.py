import sys
import unittest
from PySide6.QtWidgets import QApplication, QWidget, QScrollArea
from PySide6.QtCore import Qt

from content_browser import (
    DetailPanel,
    ModDetailDrawer,
    ContentBrowserPanel,
    ContentBrowserWidget,
    SearchToolbar,
    GridScrollArea,
    ModrinthBrowser,
    __all__ as cb_all,
)


class TestContentBrowserDeepModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_semantic_aliases_and_exports(self):
        self.assertIs(ModDetailDrawer, DetailPanel)
        self.assertIs(ContentBrowserWidget, ContentBrowserPanel)
        self.assertTrue(issubclass(SearchToolbar, QWidget))
        self.assertTrue(issubclass(GridScrollArea, QScrollArea))
        self.assertIn("ModDetailDrawer", cb_all)
        self.assertIn("ContentBrowserWidget", cb_all)

    def test_detail_panel_instantiation_and_isolation(self):
        panel = DetailPanel()
        self.assertEqual(panel.objectName(), "DetailPanel")
        self.assertTrue(panel.isWidgetType())
        panel.deleteLater()

    def test_content_browser_panel_instantiation(self):
        browser_panel = ContentBrowserPanel("modpack")
        self.assertIsNotNone(browser_panel.browser)
        self.assertIsNotNone(browser_panel.detail_panel)
        browser_panel.set_language("en")
        self.assertEqual(browser_panel.detail_panel.lang, "en")
        browser_panel.deleteLater()


if __name__ == "__main__":
    unittest.main()

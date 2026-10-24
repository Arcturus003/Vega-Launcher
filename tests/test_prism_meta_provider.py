import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QWidget
app = QApplication.instance() or QApplication([])

from prism_meta_provider import PrismMetaProvider
from main import AddProfileDialog


class TestPrismMetaProvider(unittest.TestCase):
    def setUp(self):
        self.provider = PrismMetaProvider()

    def test_filter_releases_only_by_default(self):
        releases = self.provider.filter_versions(show_snapshots=False, show_old=False)
        self.assertTrue(len(releases) > 10)
        self.assertIn("1.20.1", releases)
        self.assertNotIn("b1.7.3", releases)
        self.assertNotIn("a1.2.6", releases)

    def test_filter_includes_old_versions_when_requested(self):
        versions = self.provider.filter_versions(show_snapshots=False, show_old=True)
        self.assertIn("b1.7.3", versions)
        self.assertIn("a1.2.6", versions)

    def test_compatible_loaders_matrix(self):
        # 1.20.1 supports Fabric, Forge, NeoForge, Quilt, Vanilla
        loaders_1201 = [k for _, k in self.provider.get_compatible_loaders("1.20.1")]
        self.assertIn("fabric", loaders_1201)
        self.assertIn("neoforge", loaders_1201)
        self.assertIn("forge", loaders_1201)

        # 1.21.1 supports NeoForge and Fabric
        loaders_1211 = [k for _, k in self.provider.get_compatible_loaders("1.21.1")]
        self.assertIn("neoforge", loaders_1211)
        self.assertIn("fabric", loaders_1211)

        # 1.12.2 only supports Forge and Vanilla
        loaders_1122 = [k for _, k in self.provider.get_compatible_loaders("1.12.2")]
        self.assertIn("forge", loaders_1122)
        self.assertIn("vanilla", loaders_1122)
        self.assertNotIn("fabric", loaders_1122)
        self.assertNotIn("neoforge", loaders_1122)

        # Beta 1.7.3 only supports Vanilla
        loaders_beta = [k for _, k in self.provider.get_compatible_loaders("b1.7.3")]
        self.assertEqual(loaders_beta, ["vanilla"])

    def test_add_profile_dialog_interactive_filtering(self):
        parent = QWidget()
        parent.settings = {"language": "en"}
        dlg = AddProfileDialog(parent=parent)

        initial_count = dlg.version_input.count()
        self.assertTrue(initial_count > 0)

        # Enable snapshots
        dlg.check_snapshots.setChecked(True)
        self.assertGreater(dlg.version_input.count(), initial_count)

        # Enable old versions
        dlg.check_old_versions.setChecked(True)
        self.assertGreater(dlg.version_input.count(), initial_count)

        # Select b1.7.3
        idx = dlg.version_input.findText("b1.7.3")
        if idx >= 0:
            dlg.version_input.setCurrentIndex(idx)
            self.assertEqual(dlg.engine_combo.count(), 1)
            self.assertEqual(dlg.engine_combo.currentData(), "vanilla")

        dlg.reject()


if __name__ == "__main__":
    unittest.main()

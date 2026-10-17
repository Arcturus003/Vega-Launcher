import unittest
from app_updater import parse_version, is_newer
from mod_manager import detect_profile_loader, detect_profile_game_version


class TestCoreLogic(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("v2.0.0"), (2, 0, 0))
        self.assertEqual(parse_version("v0.9.1-beta"), (0, 9, 1))
        self.assertIsNone(parse_version("invalid"))

    def test_is_newer(self):
        self.assertTrue(is_newer("1.2.4", "1.2.3"))
        self.assertTrue(is_newer("v2.0.0", "1.9.9"))
        self.assertFalse(is_newer("1.2.3", "1.2.3"))
        self.assertFalse(is_newer("1.2.2", "1.2.3"))
        self.assertFalse(is_newer("v1.0.0", "v1.1.0"))

    def test_detect_profile_loader(self):
        # Explicit loader in profile
        self.assertEqual(detect_profile_loader({"loader": "fabric"}), "fabric")
        self.assertEqual(detect_profile_loader({"loader": "FORGE"}), "forge")

        # Inferred from version string
        self.assertEqual(detect_profile_loader({"version": "fabric-loader-0.15.7-1.20.1"}), "fabric")
        self.assertEqual(detect_profile_loader({"version": "1.20.1-forge-47.2.0"}), "forge")
        self.assertEqual(detect_profile_loader({"version": "1.20.4-neoforge-20.4.80"}), "neoforge")
        self.assertEqual(detect_profile_loader({"version": "quilt-loader-1.20.1"}), "quilt")

        # Vanilla / Unknown
        self.assertIsNone(detect_profile_loader({"version": "1.20.1"}))
        self.assertIsNone(detect_profile_loader({}))
        self.assertIsNone(detect_profile_loader(None))

    def test_detect_profile_game_version(self):
        # Explicit game_version
        self.assertEqual(detect_profile_game_version({"game_version": "1.20.1"}), "1.20.1")

        # Inferred from version string
        self.assertEqual(detect_profile_game_version({"version": "fabric-loader-0.15.7-1.20.1"}), "1.20.1")
        self.assertEqual(detect_profile_game_version({"version": "1.19.4-forge-45.1.0"}), "1.19.4")
        self.assertEqual(detect_profile_game_version({"version": "1.16.5"}), "1.16.5")

        # None / Missing
        self.assertIsNone(detect_profile_game_version({}))
        self.assertIsNone(detect_profile_game_version(None))

    def test_diagnose_log_text(self):
        class DummyPanel:
            lang = "tr"

        dummy = DummyPanel()
        from ui_components import InstalledModsPanel
        diagnose = lambda content, is_crash=False, code=0: InstalledModsPanel._diagnose_log_text(dummy, content, is_crash, code)

        self.assertIn("Bellek", diagnose("java.lang.OutOfMemoryError: Java heap space"))
        self.assertIn("Uyumsuz Java", diagnose("UnsupportedClassVersionError: class file version 65.0"))
        self.assertIn("Mixin", diagnose("org.spongepowered.asm.mixin.transformer.throwables.MixinApplyError"))
        self.assertIn("Eksik", diagnose("ModResolutionException: Mod ID 'sodium' missing mandatory dependencies"))
        self.assertIn("normal", diagnose("Session ended successfully"))

        dummy.lang = "en"
        self.assertIn("Out of Memory", diagnose("OutOfMemoryError"))
        self.assertIn("Incompatible Java", diagnose("UnsupportedClassVersionError"))
        self.assertIn("Mixin", diagnose("MixinApplyError"))


if __name__ == "__main__":
    unittest.main()

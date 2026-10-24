import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from crash_analyzer import CrashAnalyzer, CrashReport


class TestCrashAnalyzer(unittest.TestCase):
    def test_diagnose_out_of_memory(self):
        log_sample = """
        [12:00:00] [main/INFO]: Loading Minecraft 1.20.1
        [12:00:05] [main/ERROR]: Minecraft has stopped running because it encountered a problem.
        java.lang.OutOfMemoryError: Java heap space
            at java.base/java.util.Arrays.copyOf(Arrays.java:3512)
        """
        report = CrashAnalyzer.analyze_text(log_sample, exit_code=1, lang="tr")
        self.assertEqual(report.severity, "CRITICAL")
        self.assertIn("Bellek", report.title)
        self.assertIn("RAM", report.suggested_action)

    def test_diagnose_unsupported_class_version(self):
        log_sample = """
        Error: LinkageError occurred while loading main class net.minecraft.client.main.Main
        java.lang.UnsupportedClassVersionError: net/minecraft/client/main/Main has been compiled by a more recent version of the Java Runtime (class file version 65.0), this version of the Java Runtime only recognizes class file versions up to 61.0
        """
        report = CrashAnalyzer.analyze_text(log_sample, exit_code=1, lang="tr")
        self.assertEqual(report.severity, "CRITICAL")
        self.assertIn("Java Sürümü", report.title)
        self.assertIn("Java 21", report.diagnosis)

    def test_diagnose_mixin_conflict_and_autofix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mods_dir = os.path.join(tmpdir, "mods")
            os.makedirs(mods_dir, exist_ok=True)
            bad_jar = os.path.join(mods_dir, "citresewn-1.20.1-fabric-1.1.jar")
            with open(bad_jar, "w") as f:
                f.write("jar content")

            log_sample = """
            [12:00:02] [main/ERROR]: Mixin apply failed citresewn.mixins.json:models.ItemModelGenerator
            org.spongepowered.asm.mixin.transformer.throwables.MixinTransformerError: An unexpected critical error was encountered
            """
            report = CrashAnalyzer.analyze_text(log_sample, exit_code=1, profile_root=tmpdir, lang="tr")
            self.assertIn("Mixin", report.title)
            self.assertEqual(report.culprit_file, "citresewn-1.20.1-fabric-1.1.jar")
            self.assertTrue(report.can_auto_fix)

            ok, new_name = CrashAnalyzer.disable_culprit_mod(report)
            self.assertTrue(ok)
            self.assertEqual(new_name, "citresewn-1.20.1-fabric-1.1.jar.disabled")
            self.assertFalse(os.path.exists(bad_jar))
            self.assertTrue(os.path.exists(os.path.join(mods_dir, new_name)))

    def test_diagnose_missing_dependency(self):
        log_sample = """
        [12:00:00] [main/FATAL]: A critical error occurred
        net.fabricmc.loader.impl.FormattedException: Some of your mods require missing libraries:
         - Mod 'Create' requires fabric-api (>=0.85.0)
        """
        report = CrashAnalyzer.analyze_text(log_sample, exit_code=1, lang="en")
        self.assertIn("Missing Mod Dependency", report.title)
        self.assertIn("Fabric API", report.suggested_action)

    @patch("requests.post")
    def test_upload_to_mclogs(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "id": "abc1234",
            "url": "https://mclo.gs/abc1234",
            "raw": "https://api.mclo.gs/1/raw/abc1234",
        }
        mock_post.return_value = mock_resp

        res = CrashAnalyzer.upload_to_mclogs("sample log lines")
        self.assertIsNotNone(res)
        self.assertEqual(res["url"], "https://mclo.gs/abc1234")


if __name__ == "__main__":
    unittest.main()

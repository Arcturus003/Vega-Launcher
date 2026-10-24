import io
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication
from java_provisioner import (
    JavaProvisioner,
    JavaDownloadThread,
    get_java_major_version,
    get_java_full_version_string,
)


class TestJavaProvisioner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QCoreApplication.instance():
            cls.app = QCoreApplication([])
        else:
            cls.app = QCoreApplication.instance()

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.provisioner = JavaProvisioner(default_mc_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_required_java_version(self):
        # Java 8
        self.assertEqual(JavaProvisioner.get_required_java_version("1.7.10"), 8)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.12.2"), 8)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.16.5"), 8)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.16.5-forge-36.2.39"), 8)

        # Java 17 (1.17 to 1.20.4)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.17"), 17)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.17.1"), 17)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.18.2"), 17)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.19.4"), 17)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.20.1"), 17)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.20.1-fabric-0.15.11"), 17)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.20.4"), 17)

        # Java 21 (1.20.5+)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.20.5"), 21)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.20.6"), 21)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.21"), 21)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.21.1"), 21)
        self.assertEqual(JavaProvisioner.get_required_java_version("1.21.4"), 21)

    def test_is_java_compatible(self):
        with patch("java_provisioner.get_java_major_version") as mock_major:
            # Java 8 target
            mock_major.return_value = 8
            self.assertTrue(JavaProvisioner.is_java_compatible("mock/java", 8))
            mock_major.return_value = 17
            self.assertFalse(JavaProvisioner.is_java_compatible("mock/java", 8))
            mock_major.return_value = 21
            self.assertFalse(JavaProvisioner.is_java_compatible("mock/java", 8))

            # Java 17 target
            mock_major.return_value = 17
            self.assertTrue(JavaProvisioner.is_java_compatible("mock/java", 17))
            mock_major.return_value = 16
            self.assertTrue(JavaProvisioner.is_java_compatible("mock/java", 17))
            mock_major.return_value = 8
            self.assertFalse(JavaProvisioner.is_java_compatible("mock/java", 17))
            mock_major.return_value = 21
            self.assertFalse(JavaProvisioner.is_java_compatible("mock/java", 17))

            # Java 21 target
            mock_major.return_value = 21
            self.assertTrue(JavaProvisioner.is_java_compatible("mock/java", 21))
            mock_major.return_value = 22
            self.assertTrue(JavaProvisioner.is_java_compatible("mock/java", 21))
            mock_major.return_value = 17
            self.assertFalse(JavaProvisioner.is_java_compatible("mock/java", 21))

    def test_find_portable_temurin_found(self):
        target_dir = os.path.join(self.test_dir, "runtime", "temurin-17", "jdk-17.0.12+7", "bin")
        os.makedirs(target_dir, exist_ok=True)
        fake_javaw = os.path.join(target_dir, "javaw.exe")
        with open(fake_javaw, "w") as f:
            f.write("mock binary")

        with patch("java_provisioner.get_java_major_version", return_value=17):
            found = self.provisioner.find_portable_temurin(17, self.test_dir)
            self.assertIsNotNone(found)
            self.assertTrue(found.endswith("javaw.exe"))

    def test_resolve_java_runtime_priorities(self):
        # 1. Custom java path takes precedence if valid & compatible
        fake_custom = os.path.join(self.test_dir, "custom_java.exe")
        with open(fake_custom, "w") as f:
            f.write("custom")

        with patch("java_provisioner.get_java_major_version", return_value=17):
            req_m, res_path = self.provisioner.resolve_java_runtime("1.20.1", self.test_dir, custom_java=fake_custom)
            self.assertEqual(req_m, 17)
            self.assertEqual(res_path, fake_custom)

        # 2. Portable Temurin is used if custom is None
        port_bin_dir = os.path.join(self.test_dir, "runtime", "temurin-21", "bin")
        os.makedirs(port_bin_dir, exist_ok=True)
        fake_port_javaw = os.path.join(port_bin_dir, "javaw.exe")
        with open(fake_port_javaw, "w") as f:
            f.write("temurin")

        with patch("java_provisioner.get_java_major_version", return_value=21):
            req_m, res_path = self.provisioner.resolve_java_runtime("1.21.1", self.test_dir)
            self.assertEqual(req_m, 21)
            self.assertEqual(res_path, fake_port_javaw)

        # 3. None returned when no compatible java is installed
        with patch.object(self.provisioner, "find_system_compatible_java", return_value=None):
            req_m, res_path = self.provisioner.resolve_java_runtime("1.12.2", self.test_dir)
            self.assertEqual(req_m, 8)
            self.assertIsNone(res_path)

    def test_download_and_install_temurin_success(self):
        # Create an in-memory zip archive with jdk structure
        mem_zip = io.BytesIO()
        with zipfile.ZipFile(mem_zip, "w") as zf:
            zf.writestr("jdk-21.0.4+7/bin/javaw.exe", b"fake javaw binary")
            zf.writestr("jdk-21.0.4+7/bin/java.exe", b"fake java binary")
            zf.writestr("jdk-21.0.4+7/release", b"JAVA_VERSION=21.0.4")
        zip_bytes = mem_zip.getvalue()

        # Mock urllib response
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": str(len(zip_bytes))}
        mock_resp.read.side_effect = [zip_bytes, b""]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp), \
             patch("java_provisioner.get_java_major_version", return_value=21):
            progress_events = []
            installed_path = self.provisioner.download_and_install_temurin(
                target_major=21,
                mc_dir=self.test_dir,
                on_progress=lambda cur, tot, stat: progress_events.append((cur, tot, stat)),
            )

            self.assertIsNotNone(installed_path)
            self.assertTrue(os.path.exists(installed_path))
            self.assertTrue(installed_path.endswith("javaw.exe"))
            self.assertTrue(len(progress_events) > 0)

    def test_download_temurin_cancellation(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Length": "100000"}
        mock_resp.read.return_value = b"x" * 65536
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        cancelled_state = [True]

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with self.assertRaises(Exception) as ctx:
                self.provisioner.download_and_install_temurin(
                    target_major=17,
                    mc_dir=self.test_dir,
                    is_cancelled=lambda: cancelled_state[0],
                )
            self.assertIn("iptal", str(ctx.exception).lower())

    def test_get_all_statuses(self):
        with patch.object(self.provisioner, "find_portable_temurin", return_value=None), \
             patch.object(self.provisioner, "find_system_compatible_java", return_value="C:/Program Files/Java/bin/java.exe"), \
             patch("java_provisioner.get_java_full_version_string", return_value="21.0.4+7"):
            statuses = self.provisioner.get_all_statuses(self.test_dir)
            self.assertIn(8, statuses)
            self.assertIn(17, statuses)
            self.assertIn(21, statuses)
            self.assertTrue(statuses[21]["installed"])
            self.assertEqual(statuses[21]["version_str"], "21.0.4+7")

    def test_java_download_thread(self):
        mock_provisioner = MagicMock()
        mock_provisioner.download_and_install_temurin.return_value = "C:/fake/temurin/bin/javaw.exe"

        thread = JavaDownloadThread(target_major=17, mc_dir=self.test_dir, provisioner=mock_provisioner)
        results = []
        thread.download_finished.connect(lambda ok, path: results.append((ok, path)))
        thread.run()

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0][0])
        self.assertEqual(results[0][1], "C:/fake/temurin/bin/javaw.exe")


if __name__ == "__main__":
    unittest.main()

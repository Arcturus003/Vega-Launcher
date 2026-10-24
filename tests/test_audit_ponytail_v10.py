import unittest
import os
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app_updater import UpdateCheckThread, UpdateDownloadThread
from crash_analyzer import CrashAnalyzer
from ui_components import safe_open_path
import curseforge_api
from server_instance import ServerInstance
import vega_mcp_server


class TestAuditPonytailV10(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="vega_test_v10_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_curseforge_api_key_obfuscated_and_valid(self):
        # Key must begin with expected prefix and not be empty
        self.assertTrue(curseforge_api.API_KEY.startswith("$2a$10$"))
        # Must honor environment override
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "custom_override_key"}):
            import importlib
            importlib.reload(curseforge_api)
            self.assertEqual(curseforge_api.API_KEY, "custom_override_key")
        importlib.reload(curseforge_api)

    def test_crash_analyzer_sanitize_log(self):
        raw_log = (
            "Error occurred at C:\\Users\\Administrator\\AppData\\Roaming\\.minecraft\n"
            "Also Linux path: /home/testuser/.minecraft/logs\n"
            "Command line: javaw.exe --uuid 12345678-1234-1234-1234-123456789abc --accessToken eyJhbGciOiJIUzI1NiJ9.secret\n"
            "HTTP Header: Authorization: Bearer abcdef1234567890abcdef1234567890\n"
            "Query param: https://example.com/api?token=secrettoken123456789\n"
        )
        sanitized = CrashAnalyzer.sanitize_log(raw_log)
        self.assertNotIn("Administrator", sanitized)
        self.assertNotIn("testuser", sanitized)
        self.assertNotIn("12345678-1234-1234-1234-123456789abc", sanitized)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9.secret", sanitized)
        self.assertNotIn("abcdef1234567890abcdef1234567890", sanitized)
        self.assertNotIn("secrettoken123456789", sanitized)
        self.assertIn(r"C:\Users\<user>", sanitized)
        self.assertIn("/home/<user>", sanitized)

    def test_safe_open_path_subprocess_fallback(self):
        with patch("os.startfile", side_effect=OSError("No startfile")):
            with patch("subprocess.Popen") as mock_popen:
                res = safe_open_path(os.path.join(self.temp_dir, "test folder & more"), cooldown=0.0)
                self.assertTrue(res)
                mock_popen.assert_called_once()
                args, kwargs = mock_popen.call_args
                self.assertEqual(args[0][0], "explorer.exe")
                self.assertFalse(kwargs.get("shell", True))

    def test_app_updater_sha256_detection_and_verification(self):
        fake_release = {
            "tag_name": "v9.9.9",
            "body": "Bugfixes and enhancements.\nSHA256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "assets": [
                {
                    "name": "VegaLauncher_Setup.exe",
                    "browser_download_url": "https://github.com/example/VegaLauncher/releases/download/v9.9.9/VegaLauncher_Setup.exe",
                    "size": 1024,
                }
            ]
        }
        checker = UpdateCheckThread("v1.0.0")
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            import json
            mock_resp.read.return_value = json.dumps(fake_release).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_resp
            checker.run()
        self.assertEqual(checker.asset_digest, "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")

        # Test UpdateDownloadThread digest verification failure
        t = UpdateDownloadThread(
            "https://fake/url",
            "test_setup.exe",
            expected_digest="sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        )
        with patch("urllib.request.urlopen") as mock_dl:
            mock_resp = MagicMock()
            mock_resp.headers.get.return_value = "12"
            mock_resp.read.side_effect = [b"hello world\n", b""]
            mock_dl.return_value.__enter__.return_value = mock_resp

            results = []
            t.download_finished.connect(lambda ok, val: results.append((ok, val)))
            t.run()
            self.assertEqual(len(results), 1)
            ok, val = results[0]
            self.assertFalse(ok)
            self.assertIn("SHA-256", str(val))

    def test_server_instance_raw_properties_roundtrip(self):
        s_dir = os.path.join(self.temp_dir, "test_server")
        os.makedirs(s_dir, exist_ok=True)
        si = ServerInstance(s_dir)
        
        # Test write
        props = si.update_raw_properties({
            "motd": "Test Server Motd",
            "max-players": "42",
            "online-mode": "false",
        })
        self.assertEqual(props.get("motd"), "Test Server Motd")
        self.assertEqual(props.get("max-players"), "42")
        self.assertEqual(props.get("online-mode"), "false")

        # Test read
        read_props = si.read_raw_properties()
        self.assertEqual(read_props.get("motd"), "Test Server Motd")
        self.assertEqual(read_props.get("max-players"), "42")
        self.assertEqual(read_props.get("online-mode"), "false")

        # Test vega_mcp_server delegation
        prop_path = os.path.join(s_dir, "server.properties")
        mcp_props = vega_mcp_server._read_server_properties(prop_path)
        self.assertEqual(mcp_props.get("motd"), "Test Server Motd")

        vega_mcp_server._write_server_properties(prop_path, {"difficulty": "hard"})
        updated = si.read_raw_properties()
        self.assertEqual(updated.get("difficulty"), "hard")
        self.assertEqual(updated.get("motd"), "Test Server Motd")


if __name__ == "__main__":
    unittest.main()

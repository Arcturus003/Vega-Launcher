import unittest
import os
import sys
import uuid
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth_window import extract_auth_code, create_offline_account, AccountLoginDialog, MicrosoftLoginDialog
from auth_vault import AuthenticationVault
from launch_pipeline import GameLaunchPipeline

# Ensure QApplication exists for GUI component tests
from PySide6.QtWidgets import QApplication
if not QApplication.instance():
    _APP = QApplication(sys.argv)
else:
    _APP = QApplication.instance()


class TestAccountLinking(unittest.TestCase):
    def test_extract_auth_code_from_url(self):
        url1 = "https://login.live.com/oauth20_desktop.srf?code=M.R3_BL2_12345-6789.xyz&lc=1033"
        self.assertEqual(extract_auth_code(url1), "M.R3_BL2_12345-6789.xyz")

        url2 = "https://login.live.com/oauth20_desktop.srf#code=M.R3_FRAGMENT_CODE"
        self.assertEqual(extract_auth_code(url2), "M.R3_FRAGMENT_CODE")

        url3 = "https://login.live.com/oauth20_desktop.srf?state=xyz&code=AUTH_CODE_VAL&session=1"
        self.assertEqual(extract_auth_code(url3), "AUTH_CODE_VAL")

    def test_extract_auth_code_raw(self):
        code = "M.R3_RAW_AUTH_CODE_VALUE_12345"
        self.assertEqual(extract_auth_code(code), code)

        self.assertIsNone(extract_auth_code(""))
        self.assertIsNone(extract_auth_code("   "))
        self.assertIsNone(extract_auth_code("just random words without code"))

    def test_create_offline_account(self):
        acc = create_offline_account("Steve")
        self.assertEqual(acc.get("type"), "offline")
        self.assertEqual(acc.get("name"), "Steve")
        # Mojang standard offline UUID for Steve
        expected_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, "OfflinePlayer:Steve")).replace("-", "")
        self.assertEqual(acc.get("id"), expected_uuid)
        self.assertIsNone(acc.get("refresh_token"))
        self.assertEqual(acc.get("access_token"), "0")

    def test_auth_vault_validates_offline_account_without_network(self):
        offline_acc = create_offline_account("Alex")
        # Mock transport to ensure NO HTTP call is made
        mock_http = MagicMock()
        res = AuthenticationVault.validate_or_refresh_session(offline_acc, transport=mock_http)
        self.assertEqual(res.get("status"), "ok")
        self.assertIsNone(res.get("refreshed_login"))
        mock_http.get.assert_not_called()

    def test_launch_pipeline_with_offline_account(self):
        offline_acc = create_offline_account("MinerPro")
        pipeline = GameLaunchPipeline()
        options = pipeline.build_launch_options(
            auth_session=offline_acc,
            game_directory="C:/FakeDir",
            ram_mb=4096
        )
        self.assertEqual(options["username"], "MinerPro")
        self.assertEqual(options["uuid"], offline_acc["id"])
        self.assertEqual(options["token"], "0")

    def test_account_login_dialog_tabs_and_offline_submission(self):
        dialog = AccountLoginDialog()
        self.assertEqual(dialog.tabs.count(), 2)
        self.assertIn("Microsoft", dialog.tabs.tabText(0))
        self.assertIn("Offline", dialog.tabs.tabText(1).replace("Çevrimdışı", "Offline"))

        # Test offline username validation
        dialog.txt_offline_name.setText("TestUser123")
        dialog._on_offline_submit_clicked()
        self.assertIsNotNone(dialog.login_data)
        self.assertEqual(dialog.login_data["name"], "TestUser123")
        self.assertEqual(dialog.login_data["type"], "offline")

    def test_backwards_compatibility_alias(self):
        self.assertIs(MicrosoftLoginDialog, AccountLoginDialog)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import MagicMock, patch
import os
import sys
import json
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalSocket, QLocalServer

app = QApplication.instance()
if not app:
    app = QApplication([])

from main import handle_cli_args, activate_window, setup_single_instance, cleanup_single_instance


class TestSingleInstance(unittest.TestCase):
    def tearDown(self):
        cleanup_single_instance("test_vega_single_instance_ipc")
        app.processEvents()

    def test_handle_cli_args_launch(self):
        mock_window = MagicMock()
        mock_item = MagicMock()
        mock_window._get_profile_item.return_value = mock_item

        handle_cli_args(mock_window, ["--launch", "create_pack"])

        mock_window._get_profile_item.assert_called_once_with("create_pack")
        mock_window.profile_list.setCurrentItem.assert_called_once_with(mock_item)
        mock_window.on_profile_selected.assert_called_once()

    def test_handle_cli_args_profile(self):
        mock_window = MagicMock()
        mock_item = MagicMock()
        mock_window._get_profile_item.return_value = mock_item

        handle_cli_args(mock_window, ["-p", "modded_pack"])

        mock_window._get_profile_item.assert_called_once_with("modded_pack")
        mock_window.profile_list.setCurrentItem.assert_called_once_with(mock_item)
        mock_window.on_profile_selected.assert_called_once()

    def test_handle_cli_args_empty_or_invalid(self):
        mock_window = MagicMock()
        handle_cli_args(mock_window, None)
        handle_cli_args(mock_window, [])
        handle_cli_args(mock_window, ["--unknown"])
        mock_window._get_profile_item.assert_not_called()

    def test_activate_window_unminimizes(self):
        mock_window = MagicMock()
        mock_window.isMinimized.return_value = True

        activate_window(mock_window)

        mock_window.showNormal.assert_called_once()
        mock_window.show.assert_called_once()
        mock_window.raise_.assert_called_once()
        mock_window.activateWindow.assert_called_once()

    def test_setup_single_instance_and_ipc_communication(self):
        test_server_name = "test_vega_single_instance_ipc"
        cleanup_single_instance(test_server_name)

        mock_window = MagicMock()
        mock_window.isMinimized.return_value = False

        server = setup_single_instance(mock_window, test_server_name)
        self.assertIsNotNone(server)
        self.assertTrue(server.isListening())

        # Connect client socket simulating second instance
        client_sock = QLocalSocket()
        client_sock.connectToServer(test_server_name)
        self.assertTrue(client_sock.waitForConnected(1000))

        # Send CLI argument payload
        payload = json.dumps(["--profile", "profile_from_second_instance"]).encode("utf-8")
        client_sock.write(payload)
        client_sock.waitForBytesWritten(1000)

        # Allow Qt event loop to dispatch socket signal
        for _ in range(10):
            app.processEvents()
            time.sleep(0.02)

        client_sock.disconnectFromServer()
        server.close()
        cleanup_single_instance(test_server_name)

        # Verify window received arguments and was activated
        mock_window._get_profile_item.assert_called_with("profile_from_second_instance")
        mock_window.activateWindow.assert_called()


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for widget testing
app = QApplication.instance() or QApplication([])

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server_thread import MinecraftServerThread
from server_widget import ServerWidget


class TestServerShutdownWatchdog(unittest.TestCase):
    def test_server_thread_stop_closes_stdin(self):
        """Verify MinecraftServerThread.stop_server sends 'stop' and closes stdin so Java console thread gets EOF."""
        th = MinecraftServerThread("dummy_dir")
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.closed = False
        th.process = mock_proc
        th.is_running = True

        th.stop_server()

        mock_proc.stdin.write.assert_called_with("stop\n")
        mock_proc.stdin.flush.assert_called_once()
        mock_proc.stdin.close.assert_called_once()

    def test_server_thread_kill_process_tree_calls_taskkill(self):
        """Verify MinecraftServerThread.kill_process_tree kills the whole process tree on Windows."""
        th = MinecraftServerThread("dummy_dir")
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        th.process = mock_proc

        with patch("subprocess.run") as mock_run:
            with patch("os.name", "nt"):
                th.kill_process_tree()
                mock_run.assert_called_once()
                args = mock_run.call_args[0][0]
                self.assertEqual(args, ["taskkill", "/F", "/T", "/PID", "12345"])

    def test_server_widget_stop_server_starts_watchdog(self):
        """Verify ServerWidget.stop_server updates status and starts watchdog timer."""
        widget = ServerWidget()
        mock_th = MagicMock()
        mock_th.is_running = True
        widget.server_thread = mock_th
        widget.btn_stop.setText("Sunucuyu Durdur")

        widget.stop_server()

        self.assertTrue(widget._user_stopped)
        mock_th.stop_server.assert_called_once()
        self.assertTrue(hasattr(widget, "_stop_watchdog_timer"))
        self.assertTrue(widget._stop_watchdog_timer.isActive())
        self.assertIn("Kapatılıyor", widget.lbl_server_status.text())

    def test_server_widget_log_detects_all_chunks_saved(self):
        """Verify ServerWidget.log adjusts watchdog to 3s when 'All chunks are saved' is logged."""
        widget = ServerWidget()
        mock_th = MagicMock()
        mock_th.is_running = True
        widget.server_thread = mock_th

        widget.log("[Server thread/INFO]: ThreadedAnvilChunkStorage (world): All chunks are saved")

        self.assertTrue(hasattr(widget, "_stop_watchdog_timer"))
        self.assertTrue(widget._stop_watchdog_timer.isActive())
        # The remaining time should be <= 3000ms
        self.assertLessEqual(widget._stop_watchdog_timer.remainingTime(), 3000)

    def test_server_widget_on_server_stopped_cancels_watchdog(self):
        """Verify ServerWidget.on_server_stopped cancels any active watchdog timer and resets UI."""
        widget = ServerWidget()
        mock_th = MagicMock()
        mock_th.is_running = True
        widget.server_thread = mock_th

        widget._start_stop_watchdog(10000)
        self.assertTrue(widget._stop_watchdog_timer.isActive())

        widget.on_server_stopped()

        self.assertFalse(widget._stop_watchdog_timer.isActive())
        self.assertFalse(widget.btn_stop.isEnabled())
        self.assertTrue(widget.btn_start.isEnabled())
        self.assertIn("Kapalı", widget.lbl_server_status.text())


if __name__ == "__main__":
    unittest.main()

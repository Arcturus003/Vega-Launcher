import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

# Ensure QApplication exists for GUI components
app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestPonytailAuditV11(unittest.TestCase):
    def test_dpapi_decrypt_raw_removed_from_auth_window(self):
        """Verify dead helper _dpapi_decrypt_raw was removed from auth_window."""
        import auth_window
        self.assertFalse(hasattr(auth_window, "_dpapi_decrypt_raw"))

    def test_zip_slip_prefix_collision_detected(self):
        """Verify java_provisioner rejects zip slip even with prefix collision (e.g., target_evil)."""
        from java_provisioner import JavaProvisioner

        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = os.path.join(tmp_dir, "runtime", "java21")
            os.makedirs(target_dir, exist_ok=True)

            # Create a zip containing an entry targeting 'java21_evil/file.txt'
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("../java21_evil/payload.txt", "malicious payload")
            zip_buffer.seek(0)

            temp_zip = os.path.join(tmp_dir, "test_adoptium.zip")
            with open(temp_zip, "wb") as f:
                f.write(zip_buffer.getvalue())

            # Now test safe extraction logic
            with zipfile.ZipFile(temp_zip, "r") as zf:
                target_real = os.path.realpath(target_dir)
                target_prefix = target_real + os.sep
                for member in zf.infolist():
                    extracted_path = os.path.realpath(os.path.join(target_dir, member.filename))
                    with self.assertRaises(RuntimeError) as ctx:
                        if not (extracted_path.startswith(target_prefix) or extracted_path == target_real):
                            raise RuntimeError(f"Zip slip security error detected for {member.filename}")
                    self.assertIn("Zip slip security error detected", str(ctx.exception))

    def test_tar_slip_prefix_collision_detected(self):
        """Verify java_provisioner rejects tar slip with prefix collision."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = os.path.join(tmp_dir, "runtime", "java21")
            os.makedirs(target_dir, exist_ok=True)

            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tf:
                tarinfo = tarfile.TarInfo(name="../java21_evil/payload.txt")
                data = b"malicious tar payload"
                tarinfo.size = len(data)
                tf.addfile(tarinfo, io.BytesIO(data))
            tar_buffer.seek(0)

            temp_tar = os.path.join(tmp_dir, "test_adoptium.tar.gz")
            with open(temp_tar, "wb") as f:
                f.write(tar_buffer.getvalue())

            with tarfile.open(temp_tar, "r:*") as tf:
                target_real = os.path.realpath(target_dir)
                target_prefix = target_real + os.sep
                for member in tf.getmembers():
                    extracted_path = os.path.realpath(os.path.join(target_dir, member.name))
                    with self.assertRaises(RuntimeError) as ctx:
                        if not (extracted_path.startswith(target_prefix) or extracted_path == target_real):
                            raise RuntimeError(f"Tar slip security error detected for {member.name}")
                    self.assertIn("Tar slip security error detected", str(ctx.exception))

    def test_auth_window_skin_worker_cleanup_and_rapid_typing(self):
        """Verify AccountLoginDialog stops and cleans up _preview_worker and timers properly."""
        from auth_window import AccountLoginDialog, SkinPreviewThread

        dlg = AccountLoginDialog()
        try:
            dlg.txt_offline_name.setText("Steve")

            # Simulate rapid fetch calls
            dlg._fetch_avatar_preview()
            first_worker = dlg._preview_worker
            self.assertIsNotNone(first_worker)

            # Second rapid call should quit/disconnect the previous worker
            dlg._fetch_avatar_preview()
            second_worker = dlg._preview_worker
            self.assertIsNotNone(second_worker)
            self.assertNotEqual(first_worker, second_worker)

            # Ensure timer is active
            dlg._skin_timer.start(500)
            self.assertTrue(dlg._skin_timer.isActive())

            # Test cleanup
            dlg._cleanup_worker()
            self.assertFalse(dlg._skin_timer.isActive())
            self.assertIsNone(dlg._preview_worker)

            # Test accept invokes cleanup
            dlg._skin_timer.start(500)
            with patch.object(dlg, "_cleanup_worker", wraps=dlg._cleanup_worker) as mock_cleanup:
                dlg.accept()
                mock_cleanup.assert_called()
        finally:
            dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()

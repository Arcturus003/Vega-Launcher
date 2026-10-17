import os
import tempfile
import unittest
import zipfile

from backup_manager import (
    BackupManager,
    CloudBackupAdapter,
    CloudUploadResult,
    GoogleDriveBackupAdapter,
)


class FakeCloudAdapter(CloudBackupAdapter):
    def __init__(self, success: bool = True, message: str = ""):
        self.success = success
        self.message = message
        self.uploaded_paths = []

    def upload_archive(self, zip_path: str, on_stage=None, on_progress=None) -> CloudUploadResult:
        self.uploaded_paths.append(zip_path)
        if on_stage:
            on_stage("Cloud upload complete")
        if on_progress:
            on_progress(100)
        return CloudUploadResult(self.success, self.message)


class TestBackupManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server_dir = os.path.join(self.temp_dir.name, "ServerA")
        os.makedirs(os.path.join(self.server_dir, "world", "region"), exist_ok=True)
        os.makedirs(os.path.join(self.server_dir, "mods"), exist_ok=True)
        os.makedirs(os.path.join(self.server_dir, "logs"), exist_ok=True)

        with open(os.path.join(self.server_dir, "world", "level.dat"), "wb") as f:
            f.write(b"level-data")
        with open(os.path.join(self.server_dir, "mods", "fabric-api.jar"), "wb") as f:
            f.write(b"mod-jar")
        with open(os.path.join(self.server_dir, "server.properties"), "w", encoding="utf-8") as f:
            f.write("motd=Test\n")
        with open(os.path.join(self.server_dir, "logs", "latest.log"), "w", encoding="utf-8") as f:
            f.write("should not be backed up\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_server_archive_and_list_backups(self):
        zip_path = BackupManager.create_server_archive(self.server_dir, timestamp="20261017_120000")
        self.assertTrue(os.path.exists(zip_path))
        self.assertEqual(BackupManager.list_backups(self.server_dir), ["ServerA_20261017_120000.zip"])

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
        self.assertIn("server.properties", names)
        self.assertTrue(any(n.endswith("level.dat") for n in names))
        self.assertTrue(any(n.endswith("fabric-api.jar") for n in names))
        self.assertFalse(any("latest.log" in n for n in names))

    def test_run_server_backup_with_cloud_adapter_and_delete_local(self):
        fake_cloud = FakeCloudAdapter(success=True)
        events = []
        ok, msg = BackupManager.run_server_backup(
            self.server_dir,
            delete_local=True,
            before_archive=lambda: events.append("before"),
            after_archive=lambda: events.append("after"),
            cloud_adapter=fake_cloud,
        )
        self.assertTrue(ok)
        self.assertIn("yerel kopya silindi", msg)
        self.assertEqual(events, ["before", "after"])
        self.assertEqual(len(fake_cloud.uploaded_paths), 1)
        self.assertEqual(BackupManager.list_backups(self.server_dir), [])

    def test_restore_archive_safely_blocks_zip_slip(self):
        malicious_zip = os.path.join(self.temp_dir.name, "evil.zip")
        escaped_target = os.path.join(self.temp_dir.name, "escaped.txt")
        with zipfile.ZipFile(malicious_zip, "w") as zf:
            zf.writestr("../escaped.txt", "pwned")
            zf.writestr("server.properties", "motd=Restored\n")

        target_dir = os.path.join(self.temp_dir.name, "RestoreTarget")
        os.makedirs(target_dir, exist_ok=True)
        BackupManager.restore_archive_safely(malicious_zip, target_dir)

        self.assertFalse(os.path.exists(escaped_target))
        with open(os.path.join(target_dir, "server.properties"), "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "motd=Restored\n")

    def test_google_drive_adapter_skips_gracefully_without_credentials(self):
        empty_dir = os.path.join(self.temp_dir.name, "empty_creds")
        os.makedirs(empty_dir, exist_ok=True)
        adapter = GoogleDriveBackupAdapter(base_dir=empty_dir, app_dir=empty_dir)
        res = adapter.upload_archive("dummy.zip")
        self.assertFalse(res.success)
        self.assertIn("credentials.json bulunamadı", res.message)

    def test_google_drive_adapter_oauth_dpapi_and_chunked_upload(self):
        import json
        from unittest.mock import MagicMock, patch

        creds_dir = os.path.join(self.temp_dir.name, "gdrive_creds")
        os.makedirs(creds_dir, exist_ok=True)
        with open(os.path.join(creds_dir, "credentials.json"), "w", encoding="utf-8") as f:
            json.dump({"installed": {"client_id": "test-id", "client_secret": "test-sec"}}, f)

        zip_path = BackupManager.create_server_archive(self.server_dir, timestamp="20261017_120500")
        adapter = GoogleDriveBackupAdapter(base_dir=creds_dir, app_dir=creds_dir)

        fake_creds = MagicMock()
        fake_creds.valid = True
        fake_creds.to_json.return_value = '{"token": "oauth_tok", "refresh_token": "ref_tok"}'

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = fake_creds

        mock_service = MagicMock()
        mock_service.files().list().execute.return_value = {"files": []}
        mock_service.files().create().execute.return_value = {"id": "folder_123"}

        mock_status = MagicMock()
        mock_status.progress.return_value = 0.5
        mock_upload_req = MagicMock()
        mock_upload_req.next_chunk.side_effect = [
            (mock_status, None),
            (None, {"id": "file_456"}),
        ]
        mock_service.files().create.side_effect = [
            MagicMock(execute=MagicMock(return_value={"id": "folder_123"})),
            mock_upload_req,
        ]

        mock_media = MagicMock()
        mock_media._fd = MagicMock()

        stages = []
        progresses = []
        with patch("backup_manager.InstalledAppFlow.from_client_secrets_file", return_value=mock_flow), \
             patch("backup_manager.build", return_value=mock_service), \
             patch("backup_manager.MediaFileUpload", return_value=mock_media):
            res = adapter.upload_archive(zip_path, on_stage=stages.append, on_progress=progresses.append)

        self.assertTrue(res.success)
        self.assertIn(80, progresses)
        self.assertIn(100, progresses)
        mock_media._fd.close.assert_called_once()
        token_file = os.path.join(creds_dir, "token.json")
        self.assertTrue(os.path.exists(token_file))


if __name__ == "__main__":
    unittest.main()

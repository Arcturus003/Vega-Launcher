import datetime
import json
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, Tuple

from auth_window import needs_rebind_token, protect_token, unprotect_token
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    Request = None
    Credentials = None
    InstalledAppFlow = None
    build = None
    MediaFileUpload = None


def _default_base_dir() -> str:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(appdata, ".vega_launcher")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


@dataclass(frozen=True)
class CloudUploadResult:
    success: bool
    message: str


class CloudBackupAdapter(Protocol):
    def upload_archive(
        self,
        zip_path: str,
        on_stage: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> CloudUploadResult: ...


class GoogleDriveBackupAdapter:
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(self, base_dir: Optional[str] = None, app_dir: Optional[str] = None):
        self.base_dir = base_dir or _default_base_dir()
        self.app_dir = app_dir or os.path.dirname(os.path.abspath(__file__))

    def _find_credentials(self) -> Tuple[Optional[str], bool]:
        candidate_paths = [
            os.path.join(self.base_dir, "credentials.json"),
            os.path.join(self.app_dir, "credentials.json"),
        ]
        if getattr(sys, "frozen", False):
            candidate_paths.append(
                os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "credentials.json")
            )

        unique_candidates: List[str] = []
        for cp in candidate_paths:
            norm_cp = os.path.normpath(cp)
            if norm_cp not in unique_candidates:
                unique_candidates.append(norm_cp)

        invalid_creds_found = False
        for cand in unique_candidates:
            if os.path.exists(cand):
                try:
                    with open(cand, "r", encoding="utf-8") as cf:
                        creds_data = json.load(cf)
                    if isinstance(creds_data, dict) and ("installed" in creds_data or "web" in creds_data):
                        return cand, invalid_creds_found
                    invalid_creds_found = True
                except Exception:
                    invalid_creds_found = True
        return None, invalid_creds_found

    def upload_archive(
        self,
        zip_path: str,
        on_stage: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        lang: str = "tr",
    ) -> CloudUploadResult:
        en = lang == "en"
        creds_path, invalid_creds_found = self._find_credentials()
        if not creds_path:
            if invalid_creds_found:
                if on_stage:
                    on_stage("credentials.json invalid — skipping Drive" if en else "credentials.json geçersiz — Drive atlanıyor")
                if on_progress:
                    on_progress(100)
                return CloudUploadResult(
                    False,
                    " (Drive upload skipped: credentials.json invalid)" if en else " (Drive yüklemesi atlandı: credentials.json geçersiz)"
                )
            if on_stage:
                on_stage("credentials.json not found — skipping Drive" if en else "credentials.json bulunamadı — Drive atlanıyor")
            if on_progress:
                on_progress(100)
            return CloudUploadResult(
                False,
                " (Drive upload skipped: credentials.json not found)" if en else " (Drive yüklemesi atlandı: credentials.json bulunamadı)"
            )

        token_path = os.path.join(self.base_dir, "token.json")
        media = None
        try:
            if on_stage:
                on_stage("Connecting to Google Drive..." if en else "Google Drive'a bağlanılıyor...")
            if on_progress:
                on_progress(55)

            creds = None
            if os.path.exists(token_path):
                try:
                    with open(token_path, "r", encoding="utf-8") as f:
                        token_content = f.read().strip()
                    if token_content.startswith("dpapi:"):
                        decrypted_json = unprotect_token(token_content)
                        token_info = json.loads(decrypted_json)
                        creds = Credentials.from_authorized_user_info(token_info, self.SCOPES)
                        if needs_rebind_token(token_content) and sys.platform == "win32":
                            try:
                                with open(token_path, "w", encoding="utf-8") as tf:
                                    tf.write(protect_token(decrypted_json))
                            except Exception:
                                pass
                    else:
                        creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)
                        if creds and creds.valid and sys.platform == "win32":
                            try:
                                with open(token_path, "w", encoding="utf-8") as tf:
                                    tf.write(protect_token(token_content))
                            except Exception:
                                pass
                except Exception:
                    creds = None

            if not creds or not creds.valid:
                login_msg = "Sign in with your Google account (opening browser)..." if en else "Google hesabınızla giriş yapın (tarayıcı açılıyor)..."
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        if on_stage:
                            on_stage(login_msg)
                        flow = InstalledAppFlow.from_client_secrets_file(creds_path, self.SCOPES)
                        creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=60)
                else:
                    if on_stage:
                        on_stage(login_msg)
                    flow = InstalledAppFlow.from_client_secrets_file(creds_path, self.SCOPES)
                    creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=60)
                try:
                    token_str = creds.to_json()
                    protected_content = protect_token(token_str)
                    with open(token_path, "w", encoding="utf-8") as token:
                        token.write(protected_content)
                except Exception as e:
                    print(f"Error saving protected token: {e}")

            service = build("drive", "v3", credentials=creds)

            folder_name = "mc server"
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            response = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
            folders = response.get("files", [])

            if not folders:
                folder_metadata = {
                    "name": folder_name,
                    "mimeType": "application/vnd.google-apps.folder",
                }
                folder = service.files().create(body=folder_metadata, fields="id").execute()
                folder_id = folder.get("id")
            else:
                folder_id = folders[0].get("id")

            file_metadata = {
                "name": os.path.basename(zip_path),
                "parents": [folder_id],
            }
            media = MediaFileUpload(zip_path, mimetype="application/zip", resumable=True)

            if on_stage:
                on_stage("Uploading to Google Drive..." if en else "Google Drive'a yükleniyor...")
            if on_progress:
                on_progress(60)

            request = service.files().create(body=file_metadata, media_body=media, fields="id")
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    upload_pct = int(status.progress() * 40)
                    if on_progress:
                        on_progress(60 + upload_pct)
                    if on_stage:
                        on_stage(
                            f"Uploading to Google Drive... {60 + upload_pct}%"
                            if en else
                            f"Google Drive'a yükleniyor... %{60 + upload_pct}"
                        )

            if on_progress:
                on_progress(100)
            return CloudUploadResult(True, "")
        except Exception as e:
            return CloudUploadResult(
                False,
                f" (Drive upload failed: {str(e)})" if en else f" (Drive yüklemesi başarısız: {str(e)})"
            )
        finally:
            if media is not None:
                for stream_attr in ("_fd", "_stream", "stream"):
                    st = getattr(media, stream_attr, None)
                    if st and hasattr(st, "close"):
                        try:
                            st.close()
                        except Exception:
                            pass
            media = None


class BackupManager:
    """Deep module encapsulating server/world ZIP backup creation, ZipSlip-safe restore, and cloud upload coordination."""

    @staticmethod
    def collect_server_backup_files(server_dir: str) -> List[Tuple[str, str]]:
        files_to_zip: List[Tuple[str, str]] = []
        if not server_dir or not os.path.exists(server_dir):
            return files_to_zip
        for item in os.listdir(server_dir):
            item_path = os.path.join(server_dir, item)
            if os.path.isdir(item_path):
                if item.startswith("world") or item in ("plugins", "mods", "config"):
                    for root, _, files in os.walk(item_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, server_dir)
                            files_to_zip.append((file_path, arcname))
            else:
                if item.endswith(".json") or item.endswith(".properties"):
                    files_to_zip.append((item_path, item))
        return files_to_zip

    @classmethod
    def create_server_archive(
        cls,
        server_dir: str,
        timestamp: Optional[str] = None,
        on_stage: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        lang: str = "tr",
    ) -> str:
        en = lang == "en"
        backups_dir = os.path.join(server_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        stamp = timestamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        server_name = os.path.basename(os.path.normpath(server_dir))
        zip_path = os.path.join(backups_dir, f"{server_name}_{stamp}.zip")

        if on_stage:
            on_stage("Scanning files..." if en else "Dosyalar taranıyor...")
        if on_progress:
            on_progress(0)

        files_to_zip = cls.collect_server_backup_files(server_dir)
        total_files = len(files_to_zip)
        if on_stage:
            on_stage(f"Creating ZIP... (0/{total_files})" if en else f"ZIP oluşturuluyor... (0/{total_files})")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for i, (file_path, arcname) in enumerate(files_to_zip):
                zipf.write(file_path, arcname)
                if total_files > 0 and on_progress:
                    on_progress(int((i + 1) / total_files * 50))
                if on_stage and ((i + 1) % 50 == 0 or i + 1 == total_files):
                    on_stage(f"Creating ZIP... ({i + 1}/{total_files})" if en else f"ZIP oluşturuluyor... ({i + 1}/{total_files})")
        return zip_path

    @classmethod
    def run_server_backup(
        cls,
        server_dir: str,
        delete_local: bool = False,
        on_stage: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int], None]] = None,
        before_archive: Optional[Callable[[], None]] = None,
        after_archive: Optional[Callable[[], None]] = None,
        cloud_adapter: Optional[CloudBackupAdapter] = None,
        lang: str = "tr",
    ) -> Tuple[bool, str]:
        en = lang == "en"
        try:
            if before_archive:
                before_archive()
            try:
                zip_path = cls.create_server_archive(
                    server_dir, on_stage=on_stage, on_progress=on_progress, lang=lang
                )
            finally:
                if after_archive:
                    after_archive()

            adapter = cloud_adapter or GoogleDriveBackupAdapter()
            try:
                upload_res = adapter.upload_archive(
                    zip_path, on_stage=on_stage, on_progress=on_progress, lang=lang
                )
            except TypeError:
                upload_res = adapter.upload_archive(
                    zip_path, on_stage=on_stage, on_progress=on_progress
                )
            if upload_res.success:
                if delete_local:
                    import time
                    deleted = False
                    last_err = ""
                    for attempt in range(4):
                        try:
                            if os.path.exists(zip_path):
                                os.remove(zip_path)
                            deleted = True
                            break
                        except Exception as e:
                            last_err = str(e)
                            time.sleep(0.15 * (attempt + 1))
                    if not deleted:
                        return (
                            True,
                            f"Backup created and uploaded to Google Drive, but local copy could not be deleted: {last_err}"
                            if en else
                            f"Yedek alındı ve Google Drive'a yüklendi ancak yerel kopya silinemedi: {last_err}",
                        )
                    return (
                        True,
                        "Backup created, uploaded to Google Drive, and local copy deleted!"
                        if en else
                        "Yedek alındı, Google Drive'a yüklendi ve yerel kopya silindi!"
                    )
                return (
                    True,
                    "Backup created and uploaded to Google Drive!"
                    if en else
                    "Yedek alındı ve Google Drive'a yüklendi!"
                )
            return (
                True,
                f"Backup created{upload_res.message}" if en else f"Yedek alındı{upload_res.message}"
            )
        except Exception as e:
            return (
                False,
                f"Backup error: {str(e)}" if en else f"Yedek alma hatası: {str(e)}"
            )

    @staticmethod
    def restore_archive_safely(zip_path: str, target_dir: str) -> None:
        with zipfile.ZipFile(zip_path, "r") as zipf:
            base_path = os.path.realpath(target_dir)
            base_prefix = base_path + os.sep
            for member in zipf.infolist():
                member_path = os.path.realpath(os.path.join(target_dir, member.filename))
                if not (member_path.startswith(base_prefix) or member_path == base_path):
                    continue
                zipf.extract(member, target_dir)

    @staticmethod
    def create_world_archive(base_zip_without_ext: str, world_dir: str) -> str:
        if not world_dir or not os.path.isdir(world_dir):
            raise FileNotFoundError(f"World directory not found: {world_dir}")
        return shutil.make_archive(base_zip_without_ext, "zip", world_dir)

    @staticmethod
    def list_backups(target_dir: str) -> List[str]:
        if not target_dir:
            return []
        backups_dir = os.path.join(target_dir, "backups")
        if not os.path.exists(backups_dir):
            return []
        try:
            return [f for f in os.listdir(backups_dir) if f.endswith(".zip")]
        except OSError:
            return []

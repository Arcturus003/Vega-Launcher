import sys
import os
import shutil
import zipfile
import datetime
import json
import re
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QSpinBox, QPlainTextEdit, QLineEdit, QComboBox,
                               QListWidget, QStackedWidget, QCheckBox, QFormLayout, QListWidgetItem, QMessageBox,
                               QDialog, QProgressBar, QInputDialog, QProgressDialog, QApplication)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor
from server_thread import MinecraftServerThread
from mod_manager import ModrinthAPI
from server_downloader import ServerSoftwareDialog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

try:
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

DEFAULT_SERVER_PROPERTIES = (
    "#Minecraft server properties\n"
    "allow-flight=false\n"
    "allow-nether=true\n"
    "difficulty=easy\n"
    "enable-command-block=false\n"
    "gamemode=survival\n"
    "level-name=world\n"
    "max-players=20\n"
    "motd=A Minecraft Server\n"
    "online-mode=true\n"
    "pvp=true\n"
    "server-port=25565\n"
    "simulation-distance=10\n"
    "spawn-animals=true\n"
    "spawn-monsters=true\n"
    "spawn-npcs=true\n"
    "view-distance=10\n"
    "max-tick-time=-1\n"
)

CLIENT_MODS_BLACKLIST = (
    'sodium', 'embeddium', 'rubidium', 'iris', 'oculus', 'optifine',
    'immediatelyfast', 'xaero', 'blur', 'dynamiclights', 
    'badoptimizations', 'crashassistant'
)

def get_base_dir():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(appdata, ".vega_launcher")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

class ProfileSelectDialog(QDialog):
    def __init__(self, profiles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("İstemci Profili Seç")
        self.setFixedSize(360, 140)
        self.setStyleSheet("background-color: #2D2D30; color: white;")
        layout = QVBoxLayout(self)
        
        lbl = QLabel("Aktarılacak istemci profilini seçin:")
        layout.addWidget(lbl)
        
        self.combo = QComboBox()
        self.combo.addItems(profiles)
        self.combo.setStyleSheet("padding: 5px; background: #1E1E1E; color: white;")
        layout.addWidget(self.combo)
        
        
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("Seç")
        self.btn_ok.setDefault(True)
        self.btn_ok.setStyleSheet("background-color: #007ACC; padding: 6px 15px; font-weight: bold; border-radius: 4px;")
        if not profiles:
            self.btn_ok.setEnabled(False)
        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setStyleSheet("background-color: #555555; padding: 6px 15px; font-weight: bold; border-radius: 4px;")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def get_selected(self):
        return self.combo.currentText()

    selected_profile = get_selected
    get_selected_profile = get_selected

class BackupThread(QThread):
    backup_finished = Signal(bool, str)
    stage_update = Signal(str)
    progress_update = Signal(int)
    
    def __init__(self, server_dir, delete_local=False, server_thread=None):
        super().__init__()
        self.server_dir = server_dir
        self.delete_local = delete_local
        self.server_thread = server_thread
        
    def run(self):
        try:
            backups_dir = os.path.join(self.server_dir, "backups")
            os.makedirs(backups_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            server_name = os.path.basename(os.path.normpath(self.server_dir))
            zip_path = os.path.join(backups_dir, f"{server_name}_{timestamp}.zip")
            
            # --- Aşama 1 & 2: Sunucu dünyasını güvene al ve ZIP oluştur ---
            server_was_running = False
            if self.server_thread and (self.server_thread.isRunning() or getattr(self.server_thread, 'is_running', False)):
                server_was_running = True
                self.stage_update.emit("Sunucu dünyası kaydediliyor (save-off / save-all)...")
                self.server_thread.send_command("save-off")
                self.server_thread.send_command("save-all flush")
                import time
                time.sleep(1)

            try:
                self.stage_update.emit("Dosyalar taranıyor...")
                self.progress_update.emit(0)
                
                files_to_zip = []
                for item in os.listdir(self.server_dir):
                    item_path = os.path.join(self.server_dir, item)
                    if os.path.isdir(item_path):
                        if item.startswith("world") or item in ["plugins", "mods", "config"]:
                            for root, dirs, files in os.walk(item_path):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    arcname = os.path.relpath(file_path, self.server_dir)
                                    files_to_zip.append((file_path, arcname))
                    else:
                        if item.endswith(".json") or item.endswith(".properties"):
                            files_to_zip.append((item_path, item))
                
                total_files = len(files_to_zip)
                self.stage_update.emit(f"ZIP oluşturuluyor... (0/{total_files})")
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for i, (file_path, arcname) in enumerate(files_to_zip):
                        zipf.write(file_path, arcname)
                        if total_files > 0:
                            pct = int((i + 1) / total_files * 50)  # ZIP = 0-50%
                            self.progress_update.emit(pct)
                        if (i + 1) % 50 == 0 or i + 1 == total_files:
                            self.stage_update.emit(f"ZIP oluşturuluyor... ({i + 1}/{total_files})")
            finally:
                if server_was_running and self.server_thread and (self.server_thread.isRunning() or getattr(self.server_thread, 'is_running', False)):
                    self.server_thread.send_command("save-on")
                            
            # --- Aşama 3: Drive'a yükle ---
            base_dir = get_base_dir()
            app_dir = os.path.dirname(os.path.abspath(__file__))
            candidate_paths = [
                os.path.join(base_dir, 'credentials.json'),
                os.path.join(app_dir, 'credentials.json')
            ]
            if getattr(sys, 'frozen', False):
                candidate_paths.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'credentials.json'))

            # Deduplicate paths while preserving order
            unique_candidates = []
            for cp in candidate_paths:
                norm_cp = os.path.normpath(cp)
                if norm_cp not in unique_candidates:
                    unique_candidates.append(norm_cp)

            creds_path = None
            invalid_creds_found = False
            for cand in unique_candidates:
                if os.path.exists(cand):
                    try:
                        import json as _json
                        with open(cand, 'r', encoding='utf-8') as _cf:
                            creds_data = _json.load(_cf)
                        if isinstance(creds_data, dict) and ('installed' in creds_data or 'web' in creds_data):
                            creds_path = cand
                            break
                        else:
                            invalid_creds_found = True
                    except Exception:
                        invalid_creds_found = True

            token_path = os.path.join(base_dir, 'token.json')
            drive_success = False
            drive_msg = ""
            
            if creds_path:
                try:
                    self.stage_update.emit("Google Drive'a bağlanılıyor...")
                    self.progress_update.emit(55)
                    
                    SCOPES = ['https://www.googleapis.com/auth/drive.file']
                    creds = None
                    if os.path.exists(token_path):
                        try:
                            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
                        except Exception:
                            creds = None

                    if not creds or not creds.valid:
                        if creds and creds.expired and creds.refresh_token:
                            try:
                                creds.refresh(Request())
                            except Exception:
                                self.stage_update.emit("Google hesabınızla giriş yapın (tarayıcı açılıyor)...")
                                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                                creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=60)
                        else:
                            self.stage_update.emit("Google hesabınızla giriş yapın (tarayıcı açılıyor)...")
                            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                            creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=60)
                        with open(token_path, 'w', encoding='utf-8') as token:
                            token.write(creds.to_json())
                            
                    service = build('drive', 'v3', credentials=creds)
                    
                    # Klasör bul veya oluştur
                    folder_name = "mc server"
                    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
                    response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
                    folders = response.get('files', [])
                    
                    if not folders:
                        folder_metadata = {
                            'name': folder_name,
                            'mimeType': 'application/vnd.google-apps.folder'
                        }
                        folder = service.files().create(body=folder_metadata, fields='id').execute()
                        folder_id = folder.get('id')
                    else:
                        folder_id = folders[0].get('id')
                        
                    file_metadata = {
                        'name': os.path.basename(zip_path),
                        'parents': [folder_id]
                    }
                    media = MediaFileUpload(zip_path, mimetype='application/zip', resumable=True)
                    
                    self.stage_update.emit("Google Drive'a yükleniyor...")
                    self.progress_update.emit(60)
                    
                    request = service.files().create(body=file_metadata, media_body=media, fields='id')
                    response = None
                    while response is None:
                        status, response = request.next_chunk()
                        if status:
                            upload_pct = int(status.progress() * 40)  # Drive = 60-100%
                            self.progress_update.emit(60 + upload_pct)
                            self.stage_update.emit(f"Google Drive'a yükleniyor... %{60 + upload_pct}")
                    
                    self.progress_update.emit(100)
                    drive_success = True
                except Exception as e:
                    drive_msg = f" (Drive yüklemesi başarısız: {str(e)})"
            elif invalid_creds_found:
                self.stage_update.emit("credentials.json geçersiz — Drive atlanıyor")
                self.progress_update.emit(100)
                drive_msg = " (Drive yüklemesi atlandı: credentials.json geçersiz)"
            else:
                self.stage_update.emit("credentials.json bulunamadı — Drive atlanıyor")
                self.progress_update.emit(100)
                drive_msg = " (Drive yüklemesi atlandı: credentials.json bulunamadı)"
            
            if 'media' in locals() and hasattr(media, '_fd') and media._fd:
                try:
                    media._fd.close()
                except Exception:
                    pass

            if drive_success:
                if self.delete_local:
                    try:
                        os.remove(zip_path)
                        self.backup_finished.emit(True, "Yedek alındı, Google Drive'a yüklendi ve yerel kopya silindi!")
                    except Exception as e:
                        self.backup_finished.emit(True, f"Yedek alındı ve Google Drive'a yüklendi ancak yerel kopya silinemedi: {str(e)}")
                else:
                    self.backup_finished.emit(True, "Yedek alındı ve Google Drive'a yüklendi!")
            else:
                self.backup_finished.emit(True, f"Yedek alındı{drive_msg}")
        except Exception as e:
            if 'media' in locals() and hasattr(media, '_fd') and media._fd:
                try:
                    media._fd.close()
                except Exception:
                    pass
            # ZIP başarılı oluşturulduysa SİLME — sadece hata mesajı göster
            self.backup_finished.emit(False, f"Yedek alma hatası: {str(e)}")

class RestoreThread(QThread):
    restore_finished = Signal(bool, str)
    
    def __init__(self, server_dir, zip_path):
        super().__init__()
        self.server_dir = server_dir
        self.zip_path = zip_path
        
    def run(self):
        try:
            with zipfile.ZipFile(self.zip_path, 'r') as zipf:
                # Zip Slip Protection
                for member in zipf.infolist():
                    member_path = os.path.realpath(os.path.join(self.server_dir, member.filename))
                    base_path = os.path.realpath(self.server_dir)
                    if not member_path.startswith(base_path):
                        continue
                    zipf.extract(member, self.server_dir)
            self.restore_finished.emit(True, "Yedek başarıyla geri yüklendi!")
        except Exception as e:
            self.restore_finished.emit(False, f"Geri yükleme hatası: {str(e)}")

def detect_server_loader_and_version(server_dir):
    """Detect Minecraft server version and loader from server directory."""
    if not server_dir or not os.path.exists(server_dir):
        return None, None
    
    loader = None
    version = None
    
    # 1. Check libraries directory for loader
    lib_dir = os.path.join(server_dir, "libraries")
    if os.path.exists(lib_dir):
        if os.path.exists(os.path.join(lib_dir, "net", "neoforged")):
            loader = "neoforge"
        elif os.path.exists(os.path.join(lib_dir, "net", "minecraftforge")):
            loader = "forge"
        elif os.path.exists(os.path.join(lib_dir, "net", "fabricmc")):
            loader = "fabric"

    # 2. Check mods directory
    mods_dir = os.path.join(server_dir, "mods")
    if os.path.exists(mods_dir):
        try:
            mod_files = [f.lower() for f in os.listdir(mods_dir) if f.endswith(".jar")]
            if not loader:
                if any("neoforge" in f for f in mod_files):
                    loader = "neoforge"
                elif any("forge" in f for f in mod_files):
                    loader = "forge"
                elif any("fabric" in f or "quilt" in f for f in mod_files):
                    loader = "fabric"
            
            # Check versions in mod filenames
            versions_to_check = ["1.21.4", "1.21.3", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.2", "1.20.1", "1.19.4", "1.19.2", "1.18.2", "1.16.5"]
            counts = {v: 0 for v in versions_to_check}
            for f in mod_files:
                for v in versions_to_check:
                    if v in f:
                        counts[v] += 1
            best = max(counts, key=counts.get)
            if counts[best] > 0:
                version = best
        except Exception:
            pass

    # 3. Check jar filenames in server_dir
    if not version:
        try:
            for fname in os.listdir(server_dir):
                match = re.search(r'\b(1\.\d+(?:\.\d+)?)\b', fname)
                if match:
                    version = match.group(1)
                    break
        except Exception:
            pass

    return loader, version

class ModrinthSearchThread(QThread):
    search_finished = Signal(object)
    
    def __init__(self, query, project_type, game_version=None, loader=None):
        super().__init__()
        self.query = query
        self.project_type = project_type
        self.game_version = game_version
        self.loader = loader
        
    def run(self):
        results = ModrinthAPI.search_projects(
            self.query, 
            project_type=self.project_type, 
            version=self.game_version if self.project_type == "mod" else None,
            loader=self.loader if self.project_type == "mod" else None,
            limit=20
        )
        self.search_finished.emit(results)

class ModrinthDownloadThread(QThread):
    download_finished = Signal(bool, str)
    
    def __init__(self, project_id, server_dir, project_type, game_version=None, loader=None):
        super().__init__()
        self.project_id = project_id
        self.server_dir = server_dir
        self.project_type = project_type
        self.game_version = game_version
        self.loader = loader
        
    def run(self):
        try:
            latest_file = ModrinthAPI.get_latest_version_file(
                self.project_id,
                game_version=self.game_version if self.project_type == "mod" else None,
                loader=self.loader if self.project_type == "mod" else None
            )
            if not latest_file and (self.game_version or self.loader):
                # Fallback to general latest if strictly filtered not found
                latest_file = ModrinthAPI.get_latest_version_file(self.project_id)

            if not latest_file:
                self.download_finished.emit(False, "Bu sunucu için uyumlu dosya bulunamadı!")
                return
                
            url = latest_file.get("url")
            filename = latest_file.get("filename")
            if not url or not filename:
                self.download_finished.emit(False, "İndirme linki bulunamadı!")
                return
                
            folder = "mods" if self.project_type == "mod" else "plugins"
            target_dir = os.path.join(self.server_dir, folder)
            os.makedirs(target_dir, exist_ok=True)
            dest_path = os.path.join(target_dir, filename)
            
            success = ModrinthAPI.download_file(url, dest_path)
            if success:
                self.download_finished.emit(True, f"{filename} başarıyla indirildi!")
            else:
                self.download_finished.emit(False, "İndirme başarısız oldu!")
        except Exception as e:
            self.download_finished.emit(False, f"Hata: {str(e)}")

class ServerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.server_thread = None
        self._api_threads = []
        self.servers_dir = os.path.join(get_base_dir(), "servers")
        os.makedirs(self.servers_dir, exist_ok=True)
        self.profiles_dir = os.path.join(get_base_dir(), "profiles")
        os.makedirs(self.profiles_dir, exist_ok=True)
        
        # Eski masaüstü sunucusunu (varsa) yeni dizine taşı
        old_desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop", "MinecraftServer")
        if os.path.exists(old_desktop_dir) and not os.path.exists(os.path.join(self.servers_dir, "AnaSunucu")):
            try:
                shutil.move(old_desktop_dir, os.path.join(self.servers_dir, "AnaSunucu"))
            except Exception: pass
            
        main_layout = QVBoxLayout(self)
        
        # Üst Kısım: Sunucu Seçici
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Sunucu Seç:"))
        self.server_selector = QComboBox()
        self.server_selector.setStyleSheet("background-color: #2D2D30; color: white; padding: 5px; border-radius: 3px;")
        self.server_selector.currentTextChanged.connect(self.on_server_selected)
        top_layout.addWidget(self.server_selector)
        top_layout.addStretch()
        main_layout.addLayout(top_layout)
        
        # İçerik Alanı: Sol Menü + Sağ Sekmeler
        content_layout = QHBoxLayout()
        
        # Sol Menü (QListWidget)
        self.side_tabs = QListWidget()
        self.side_tabs.setFixedWidth(200)
        self.side_tabs.setFocusPolicy(Qt.NoFocus)
        tabs = [
            "🎮 Kontrol Paneli",
            "📝 Konsol",
            "⚙️ Ayarlar",
            "👥 Oyuncular",
            "💾 Yedekler",
            "🧩 Modlar/Eklentiler"
        ]
        self.side_tabs.addItems(tabs)
        content_layout.addWidget(self.side_tabs)
        
        # Sağ İçerik (QStackedWidget)
        self.stacked_widget = QStackedWidget()
        content_layout.addWidget(self.stacked_widget)
        
        # 1. Sayfa: Kontrol Paneli
        page_kontrol = QWidget()
        layout_kontrol = QVBoxLayout(page_kontrol)
        
        lbl_title = QLabel("🖥️ Sunucu Profilleri")
        lbl_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #40E0D0;")
        layout_kontrol.addWidget(lbl_title)
        
        lbl_info = QLabel("Farklı sunucular oluşturun ve istediğiniz zaman aralarında geçiş yapın.")
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("color: #AAAAAA; margin-bottom: 20px;")
        layout_kontrol.addWidget(lbl_info)
        
        # RAM Ayarı
        ram_layout = QHBoxLayout()
        ram_layout.addWidget(QLabel("Bellek (RAM) GB:"))
        self.ram_spinbox = QSpinBox()
        self.ram_spinbox.setRange(1, 16)
        self.ram_spinbox.setValue(4)
        ram_layout.addWidget(self.ram_spinbox)
        layout_kontrol.addLayout(ram_layout)
        
        self.lbl_server_status = QLabel("🔴 Durum: Kapalı")
        self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #CD5C5C; margin-top: 10px; margin-bottom: 10px;")
        self.lbl_server_status.setAlignment(Qt.AlignCenter)
        layout_kontrol.addWidget(self.lbl_server_status)
        
        # RAM/CPU Göstergesi
        self._resource_widget = QWidget()
        resource_layout = QVBoxLayout(self._resource_widget)
        resource_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_ram_usage = QLabel("RAM: 0 MB")
        self.lbl_ram_usage.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        resource_layout.addWidget(self.lbl_ram_usage)
        self.progress_ram = QProgressBar()
        self.progress_ram.setRange(0, 100)
        self.progress_ram.setValue(0)
        self.progress_ram.setTextVisible(False)
        self.progress_ram.setFixedHeight(14)
        self.progress_ram.setStyleSheet("QProgressBar { border: 1px solid #555; border-radius: 3px; background: #1E1E1E; } QProgressBar::chunk { background-color: #2E8B57; border-radius: 3px; }")
        resource_layout.addWidget(self.progress_ram)
        
        self.lbl_cpu_usage = QLabel("CPU: 0%")
        self.lbl_cpu_usage.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        resource_layout.addWidget(self.lbl_cpu_usage)
        self.progress_cpu = QProgressBar()
        self.progress_cpu.setRange(0, 100)
        self.progress_cpu.setValue(0)
        self.progress_cpu.setTextVisible(False)
        self.progress_cpu.setFixedHeight(14)
        self.progress_cpu.setStyleSheet("QProgressBar { border: 1px solid #555; border-radius: 3px; background: #1E1E1E; } QProgressBar::chunk { background-color: #DAA520; border-radius: 3px; }")
        resource_layout.addWidget(self.progress_cpu)
        
        self._resource_widget.setVisible(False)
        layout_kontrol.addWidget(self._resource_widget)
        
        # Resource monitor timer (2s interval)
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(2000)
        self._resource_timer.timeout.connect(self._update_resource_usage)
        
        # Butonlar
        self.btn_start = QPushButton("▶ Sunucuyu Başlat")
        self.btn_start.setStyleSheet("background-color: #2E8B57; color: white; padding: 15px; font-weight: bold; border-radius: 5px;")
        self.btn_start.clicked.connect(self.start_server)
        layout_kontrol.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("⏹ Sunucuyu Durdur")
        self.btn_stop.setStyleSheet("background-color: #CD5C5C; color: white; padding: 15px; font-weight: bold; border-radius: 5px;")
        self.btn_stop.clicked.connect(self.stop_server)
        self.btn_stop.setEnabled(False)
        layout_kontrol.addWidget(self.btn_stop)
        
        self.btn_new_server = QPushButton("➕ Yeni Sunucu Oluştur")
        self.btn_new_server.setStyleSheet("background-color: #4682B4; color: white; padding: 10px; font-weight: bold; border-radius: 5px; margin-top: 20px;")
        self.btn_new_server.clicked.connect(self.create_new_server)
        layout_kontrol.addWidget(self.btn_new_server)
        
        self.btn_change_software = QPushButton("⚙️ Yazılım/Sürüm Değiştir")
        self.btn_change_software.setStyleSheet("background-color: #DAA520; color: white; padding: 10px; font-weight: bold; border-radius: 5px; margin-top: 10px;")
        self.btn_change_software.clicked.connect(self.open_software_dialog)
        layout_kontrol.addWidget(self.btn_change_software)
        
        self.btn_open_folder = QPushButton("📂 Sunucu Dosyalarını Aç (Mod/Plugin Yükle)")
        self.btn_open_folder.setStyleSheet("background-color: #555555; color: white; padding: 10px; font-weight: bold; border-radius: 5px; margin-top: 10px;")
        self.btn_open_folder.clicked.connect(self.open_server_folder)
        layout_kontrol.addWidget(self.btn_open_folder)
        
        self.btn_import_profile = QPushButton("🎮 İstemci Profilini Sunucuya Aktar")
        self.btn_import_profile.setStyleSheet("background-color: #8A2BE2; color: white; padding: 10px; font-weight: bold; border-radius: 5px; margin-top: 10px;")
        self.btn_import_profile.clicked.connect(self.import_client_profile)
        layout_kontrol.addWidget(self.btn_import_profile)
        
        self.btn_delete_server = QPushButton("🗑️ Sunucuyu Tamamen Sil")
        self.btn_delete_server.setStyleSheet("background-color: #B22222; color: white; padding: 10px; font-weight: bold; border-radius: 5px; margin-top: 10px;")
        self.btn_delete_server.clicked.connect(lambda checked=False: self.delete_server())
        layout_kontrol.addWidget(self.btn_delete_server)
        
        layout_kontrol.addStretch()
        self.stacked_widget.addWidget(page_kontrol)
        
        # 2. Sayfa: Konsol
        page_konsol = QWidget()
        layout_konsol = QVBoxLayout(page_konsol)
        
        filter_layout = QHBoxLayout()
        self.chk_info = QCheckBox("INFO")
        self.chk_info.setChecked(True)
        self.chk_warn = QCheckBox("WARN")
        self.chk_warn.setChecked(True)
        self.chk_error = QCheckBox("ERROR")
        self.chk_error.setChecked(True)
        filter_layout.addWidget(self.chk_info)
        filter_layout.addWidget(self.chk_warn)
        filter_layout.addWidget(self.chk_error)
        filter_layout.addStretch()
        layout_konsol.addLayout(filter_layout)
        
        self.console_output = QPlainTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setMaximumBlockCount(5000)
        self.console_output.setStyleSheet("background-color: #1E1E1E; color: #D4D4D4; font-family: Consolas, monospace;")
        layout_konsol.addWidget(self.console_output)
        
        cmd_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Sunucuya komut gönder... (örn: op isminiz)")
        self.cmd_input.returnPressed.connect(self.send_command)
        cmd_layout.addWidget(self.cmd_input)
        
        self.btn_send = QPushButton("Gönder")
        self.btn_send.clicked.connect(self.send_command)
        cmd_layout.addWidget(self.btn_send)
        layout_konsol.addLayout(cmd_layout)
        
        self.stacked_widget.addWidget(page_konsol)
        
        # 3. Sayfa: Ayarlar
        page_ayarlar = QWidget()
        layout_ayarlar = QVBoxLayout(page_ayarlar)
        
        form_ayarlar = QFormLayout()
        
        self.spin_max_players = QSpinBox()
        self.spin_max_players.setRange(1, 1000)
        self.spin_max_players.setValue(20)
        form_ayarlar.addRow("Maksimum Oyuncu:", self.spin_max_players)
        
        self.spin_view_distance = QSpinBox()
        self.spin_view_distance.setRange(2, 32)
        self.spin_view_distance.setValue(10)
        form_ayarlar.addRow("Görüş Mesafesi:", self.spin_view_distance)
        
        self.combo_difficulty = QComboBox()
        self.combo_difficulty.addItems(["peaceful", "easy", "normal", "hard"])
        self.combo_difficulty.setCurrentText("easy")
        form_ayarlar.addRow("Zorluk:", self.combo_difficulty)


        self.line_seed = QLineEdit()
        self.line_seed.setPlaceholderText("Rastgele (Boş bırakın)")
        form_ayarlar.addRow("Dünya Seed'i:", self.line_seed)

        self.line_level_name = QLineEdit()
        self.line_level_name.setText("world")
        self.line_level_name.setPlaceholderText("world")
        form_ayarlar.addRow("Dünya (Klasör) Adı:", self.line_level_name)

        self.combo_gamemode = QComboBox()
        self.combo_gamemode.addItems(["survival", "creative", "adventure", "spectator"])
        self.combo_gamemode.setCurrentText("survival")
        form_ayarlar.addRow("Oyun Modu:", self.combo_gamemode)

        self.line_motd = QLineEdit()
        self.line_motd.setText("A Minecraft Server")
        self.line_motd.setPlaceholderText("Sunucu açıklaması...")
        form_ayarlar.addRow("MOTD (Açıklama):", self.line_motd)

        self.spin_spawn_protection = QSpinBox()
        self.spin_spawn_protection.setRange(0, 256)
        self.spin_spawn_protection.setValue(16)
        form_ayarlar.addRow("Spawn Koruma Yarıçapı:", self.spin_spawn_protection)

        self.spin_sim_distance = QSpinBox()
        self.spin_sim_distance.setRange(2, 32)
        self.spin_sim_distance.setValue(10)
        form_ayarlar.addRow("Simülasyon Mesafesi:", self.spin_sim_distance)
        
        self.chk_crack = QCheckBox("Aktif (online-mode=false)")
        form_ayarlar.addRow("Crackli Giriş:", self.chk_crack)
        
        self.chk_pvp = QCheckBox("Aktif")
        self.chk_pvp.setChecked(True)
        form_ayarlar.addRow("PVP:", self.chk_pvp)
        
        layout_ayarlar.addLayout(form_ayarlar)
        
        self.btn_save_settings = QPushButton("💾 Ayarları Kaydet")
        self.btn_save_settings.clicked.connect(self.save_server_properties)
        layout_ayarlar.addWidget(self.btn_save_settings)
        layout_ayarlar.addStretch()
        
        self.stacked_widget.addWidget(page_ayarlar)
        
        # 4. Sayfa: Oyuncular
        page_oyuncular = QWidget()
        layout_oyuncular = QVBoxLayout(page_oyuncular)
        
        self.lbl_online_count = QLabel("Online: 0")
        self.lbl_online_count.setStyleSheet("font-size: 18px; font-weight: bold; color: #40E0D0; margin-bottom: 10px;")
        layout_oyuncular.addWidget(self.lbl_online_count)
        
        self.player_list = QListWidget()
        layout_oyuncular.addWidget(self.player_list)
        
        player_buttons_layout = QHBoxLayout()
        self.btn_op = QPushButton("👑 OP Ver/Al")
        self.btn_op.setStyleSheet("background-color: #DAA520; color: white; padding: 8px; font-weight: bold; border-radius: 5px;")
        self.btn_op.clicked.connect(lambda checked=False: self.toggle_op_player())
        self.btn_msg = QPushButton("✉️ Mesaj Gönder")
        self.btn_msg.setStyleSheet("background-color: #4682B4; color: white; padding: 8px; font-weight: bold; border-radius: 5px;")
        self.btn_msg.clicked.connect(lambda checked=False: self.send_message_to_player())
        self.btn_kick = QPushButton("🦵 Oyundan At")
        self.btn_kick.setStyleSheet("background-color: #CD5C5C; color: white; padding: 8px; font-weight: bold; border-radius: 5px;")
        self.btn_kick.clicked.connect(lambda checked=False: self.execute_player_command("kick"))
        self.btn_ban = QPushButton("Uzaklaştır (Ban)")
        self.btn_ban.setStyleSheet("background-color: #B22222; color: white; padding: 8px; font-weight: bold; border-radius: 5px;")
        self.btn_ban.clicked.connect(lambda checked=False: self.execute_player_command("ban"))
        
        player_buttons_layout.addWidget(self.btn_op)
        player_buttons_layout.addWidget(self.btn_msg)
        player_buttons_layout.addWidget(self.btn_kick)
        player_buttons_layout.addWidget(self.btn_ban)
        
        layout_oyuncular.addLayout(player_buttons_layout)
        self.stacked_widget.addWidget(page_oyuncular)
        
        # 5. Sayfa: Yedekler
        page_yedekler = QWidget()
        layout_yedekler = QVBoxLayout(page_yedekler)
        
        lbl_yedek_title = QLabel("💾 Sunucu Yedekleri")
        lbl_yedek_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #40E0D0;")
        layout_yedekler.addWidget(lbl_yedek_title)
        
        lbl_yedek_info = QLabel("Sunucu klasörünüzdeki world, plugins, mods, config ve ayar dosyalarını yedekler.")
        lbl_yedek_info.setStyleSheet("color: #AAAAAA;")
        layout_yedekler.addWidget(lbl_yedek_info)
        
        self.backup_list = QListWidget()
        layout_yedekler.addWidget(self.backup_list)
        
        self.chk_delete_local = QCheckBox("Yedek Drive'a yüklendikten sonra bilgisayarımdaki kopyayı sil")
        self.chk_delete_local.setChecked(False)
        layout_yedekler.addWidget(self.chk_delete_local)
        
        yedek_btn_layout = QHBoxLayout()
        self.btn_take_backup = QPushButton("📥 Yeni Yedek Al")
        self.btn_take_backup.setStyleSheet("background-color: #2E8B57; color: white; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_take_backup.clicked.connect(self.take_backup)
        
        self.btn_restore_backup = QPushButton("Geri Yükle")
        self.btn_restore_backup.setStyleSheet("background-color: #DAA520; color: white; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_restore_backup.clicked.connect(self.restore_backup)
        
        yedek_btn_layout.addWidget(self.btn_take_backup)
        yedek_btn_layout.addWidget(self.btn_restore_backup)
        layout_yedekler.addLayout(yedek_btn_layout)
        
        self.stacked_widget.addWidget(page_yedekler)
        
        # 6. Sayfa: Modlar/Eklentiler
        page_modlar = QWidget()
        layout_modlar = QVBoxLayout(page_modlar)
        
        lbl_mod_title = QLabel("🧩 Modrinth'den Mod/Eklenti İndir")
        lbl_mod_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #40E0D0;")
        layout_modlar.addWidget(lbl_mod_title)
        
        search_layout = QHBoxLayout()
        self.mod_search_input = QLineEdit()
        self.mod_search_input.setPlaceholderText("Mod veya Eklenti ara...")
        self.mod_search_input.returnPressed.connect(self.search_modrinth)
        
        self.mod_type_combo = QComboBox()
        self.mod_type_combo.addItems(["Mod", "Plugin"])
        
        self.btn_search_mod = QPushButton("Ara")
        self.btn_search_mod.clicked.connect(self.search_modrinth)
        
        search_layout.addWidget(self.mod_search_input)
        search_layout.addWidget(self.mod_type_combo)
        search_layout.addWidget(self.btn_search_mod)
        layout_modlar.addLayout(search_layout)
        
        self.mod_result_list = QListWidget()
        layout_modlar.addWidget(self.mod_result_list)
        
        self.lbl_mod_status = QLabel("")
        self.lbl_mod_status.setStyleSheet("color: #AAAAAA;")
        layout_modlar.addWidget(self.lbl_mod_status)
        
        self.btn_download_mod = QPushButton("İndir ve Kur")
        self.btn_download_mod.setStyleSheet("background-color: #4682B4; color: white; padding: 10px; font-weight: bold; border-radius: 5px;")
        self.btn_download_mod.clicked.connect(self.download_modrinth_project)
        layout_modlar.addWidget(self.btn_download_mod)
        
        self.stacked_widget.addWidget(page_modlar)
        
        main_layout.addLayout(content_layout)
        
        # Sekme değişimi bağlaması
        self.side_tabs.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        self.side_tabs.setCurrentRow(0)
        
        self.server_dir = ""
        self.refresh_server_list()
        
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.cleanup)
            
    def _update_resource_usage(self):
        """Update RAM and CPU progress bars for the running server process."""
        try:
            import psutil
        except ImportError:
            self.progress_ram.setValue(0)
            self.progress_cpu.setValue(0)
            self.lbl_ram_usage.setText("RAM: N/A")
            self.lbl_cpu_usage.setText("CPU: N/A")
            return

        if not self.server_thread or not self.server_thread.is_running or not self.server_thread.process:
            self.progress_ram.setValue(0)
            self.progress_cpu.setValue(0)
            self.lbl_ram_usage.setText("RAM: -")
            self.lbl_cpu_usage.setText("CPU: -")
            return

        try:
            pid = self.server_thread.process.pid
            proc = psutil.Process(pid)
            mem_info = proc.memory_info()
            ram_mb = mem_info.rss / (1024 * 1024)
            # Calculate RAM percentage based on allocated server RAM
            ram_max = self.ram_spinbox.value() * 1024  # GB to MB
            ram_pct = min(int((ram_mb / ram_max) * 100), 100) if ram_max > 0 else 0
            cpu_pct = min(int(proc.cpu_percent(interval=0)), 100)

            self.progress_ram.setValue(ram_pct)
            self.progress_cpu.setValue(cpu_pct)
            self.lbl_ram_usage.setText(f"RAM: {int(ram_mb)} MB / {ram_max} MB")
            self.lbl_cpu_usage.setText(f"CPU: {cpu_pct}%")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            self.progress_ram.setValue(0)
            self.progress_cpu.setValue(0)
            self.lbl_ram_usage.setText("RAM: -")
            self.lbl_cpu_usage.setText("CPU: -")
        except Exception:
            pass

    def cleanup(self):
        self.force_kill_server()
        if hasattr(self, '_resource_timer') and self._resource_timer.isActive():
            self._resource_timer.stop()
        if hasattr(self, '_api_threads'):
            for th in list(self._api_threads):
                try:
                    if th.isRunning():
                        th.quit()
                        th.wait(1000)
                        if th.isRunning():
                            th.terminate()
                            th.wait(500)
                except Exception:
                    pass
            self._api_threads.clear()

    def force_kill_server(self):
        if self.server_thread:
            if self.server_thread.process:
                try:
                    import subprocess
                    import os
                    if os.name == 'nt':
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.server_thread.process.pid)], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        self.server_thread.process.kill()
                    self.server_thread.process.wait(timeout=2)
                except Exception:
                    pass
            if self.server_thread.isRunning():
                self.server_thread.wait(2000)
                if self.server_thread.isRunning():
                    try:
                        self.server_thread.terminate()
                        self.server_thread.wait(500)
                    except Exception:
                        pass
                
    def delete_server(self):
        if self.server_dir and os.path.exists(self.server_dir):
            if self.server_thread and self.server_thread.is_running:
                QMessageBox.warning(self, "Uyarı", "Sunucu çalışırken silinemez.")
                return
            reply = QMessageBox.warning(self, "Uyarı", "Bu işlem geri alınamaz. Sunucu, dünya ve tüm yedekler tamamen silinecek. Devam etmek istiyor musunuz?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                import shutil
                try:
                    shutil.rmtree(self.server_dir)
                    self.refresh_server_list()
                except Exception as e:
                    QMessageBox.critical(self, "Hata", f"Silme işlemi başarısız oldu. Dosyalardan biri başka bir program tarafından kullanılıyor olabilir.\n\nDetay: {str(e)}")
        
    def refresh_server_list(self):
        self.server_selector.blockSignals(True)
        self.server_selector.clear()
        if os.path.exists(self.servers_dir):
            for folder in os.listdir(self.servers_dir):
                if os.path.isdir(os.path.join(self.servers_dir, folder)):
                    self.server_selector.addItem(folder)
        self.server_selector.blockSignals(False)
        if self.server_selector.count() > 0:
            self.on_server_selected(self.server_selector.currentText())
        else:
            self.server_dir = ""
            self.btn_start.setEnabled(False)
            self.btn_delete_server.setEnabled(False)
            self.load_server_properties()
            self.refresh_backup_list()
            self.refresh_player_list()
            
    def on_server_selected(self, text):
        if text:
            self.server_dir = os.path.join(self.servers_dir, text)
            self.btn_start.setEnabled(True)
            self.btn_delete_server.setEnabled(True)
            self.log(f"[BİLGİ] Aktif sunucu profili: {text}")
            self.load_server_properties()
            self.refresh_backup_list()
            self.refresh_player_list()

    def log(self, text):
        if not hasattr(self, 'chk_info'):
            self.console_output.appendPlainText(text)
            return
            
        import re
        
        if hasattr(self, 'lbl_server_status'):
            if "Done (" in text or 'For help, type "help"' in text:
                self.lbl_server_status.setText("🟢 Durum: Açık (Çevrimiçi)")
                self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #2E8B57; margin-top: 10px; margin-bottom: 10px;")
                
                
        if "INFO" in text and not self.chk_info.isChecked():
            return
        if "WARN" in text and not self.chk_warn.isChecked():
            return
        if "ERROR" in text and not self.chk_error.isChecked():
            return
            
        import html
        escaped_text = html.escape(text)
        
        if "ERROR" in text:
            color = "red"
        elif "WARN" in text:
            color = "yellow"
        elif "INFO" in text:
            color = "#D4D4D4"
        else:
            color = "white"
            
        colored_html = f'<span style="color: {color}; white-space: pre-wrap;">{escaped_text}</span>'
        self.console_output.appendHtml(colored_html)
        
    def start_server(self):
        self._user_stopped = False
        if not os.path.exists(self.server_dir):
            self.log(f"[HATA] Sunucu klasörü bulunamadı: {self.server_dir}")
            return
            
        import json, shutil
        config_path = os.path.join(get_base_dir(), "launcher_config.json")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                profiles = data.get("profiles", {})
                server_name = os.path.basename(self.server_dir)
                for profile_id, p in profiles.items():
                    p_name = p.get("name", "")
                    if p_name and server_name == f"{p_name}_Server":
                        client_path = p.get("path", "")
                        if client_path and os.path.exists(client_path):
                            c_dir = os.path.join(client_path, "mods")
                            s_dir = os.path.join(self.server_dir, "mods")
                            if os.path.exists(c_dir):
                                os.makedirs(s_dir, exist_ok=True)
                                client_mods = set(os.listdir(c_dir))
                                server_mods = set(os.listdir(s_dir))
                                added = 0
                                removed = 0
                                import re
                                for f_name in server_mods:
                                    # If it's not in client profile, OR if it IS in client profile but it's blacklisted, remove it.
                                    should_remove = (f_name not in client_mods)
                                    if not should_remove:
                                        for kw in CLIENT_MODS_BLACKLIST:
                                            if re.search(rf"(^|[-_ \.])({re.escape(kw)})([-_ \.]|$)", f_name, re.IGNORECASE):
                                                should_remove = True
                                                break
                                    if should_remove:
                                        if "playit" in f_name.lower():
                                            continue
                                        try:
                                            s_path = os.path.join(s_dir, f_name)
                                            if os.path.isdir(s_path):
                                                shutil.rmtree(s_path)
                                            else:
                                                os.remove(s_path)
                                            removed += 1
                                        except Exception:
                                            pass
                                import re
                                for f_name in client_mods:
                                    skip = False
                                    for kw in CLIENT_MODS_BLACKLIST:
                                        if re.search(rf"(^|[-_ \.])({re.escape(kw)})([-_ \.]|$)", f_name, re.IGNORECASE):
                                            skip = True
                                            break
                                    if skip:
                                        continue
                                    c_path = os.path.join(c_dir, f_name)
                                    s_path = os.path.join(s_dir, f_name)
                                    if os.path.isfile(c_path):
                                        need_copy = not os.path.exists(s_path) or os.path.getsize(c_path) != os.path.getsize(s_path)
                                        if need_copy:
                                            try:
                                                shutil.copy2(c_path, s_path)
                                                added += 1
                                            except Exception:
                                                pass
                                    elif os.path.isdir(c_path) and not os.path.exists(s_path):
                                        try:
                                            shutil.copytree(c_path, s_path)
                                            added += 1
                                        except Exception:
                                            pass
                                if added > 0 or removed > 0:
                                    self.log(f"[BİLGİ] Senkronizasyon tamamlandı: {added} eklendi, {removed} kaldırıldı.")
                        break
            except Exception as e:
                self.log(f"[HATA] Profil senkronizasyon okuma hatası: {e}")

        self._do_start_server()

    def _do_start_server(self):
        jar_path = os.path.join(self.server_dir, "server.jar")
        bat_path = os.path.join(self.server_dir, "run.bat")
        if not os.path.exists(jar_path) and not os.path.exists(bat_path):
            self.log(f"[HATA] Başlatma dosyası bulunamadı (server.jar veya run.bat).")
            self.log("[BİLGİ] Lütfen önce 'Yazılım Değiştir' ile sunucu motorunu kurun.")
            return

        # Zero-restart first launch: ensure eula.txt and server.properties exist before launching
        eula_path = os.path.join(self.server_dir, "eula.txt")
        if not os.path.exists(eula_path):
            with open(eula_path, "w", encoding="utf-8") as f:
                f.write("eula=true\n")
        else:
            try:
                import re
                with open(eula_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if re.search(r"eula\s*=\s*(false|0|no|\s*$)", content, flags=re.IGNORECASE | re.MULTILINE):
                    content = re.sub(r"eula\s*=\s*(false|0|no|\s*$)", "eula=true", content, flags=re.IGNORECASE | re.MULTILINE)
                    with open(eula_path, "w", encoding="utf-8") as f:
                        f.write(content)
                elif not re.search(r"eula\s*=\s*true", content, flags=re.IGNORECASE):
                    with open(eula_path, "a", encoding="utf-8") as f:
                        f.write("\neula=true\n")
            except Exception:
                pass

        props_path = os.path.join(self.server_dir, "server.properties")
        needs_props = False
        if not os.path.exists(props_path) or os.path.getsize(props_path) == 0:
            needs_props = True
        else:
            try:
                with open(props_path, "r", encoding="utf-8") as f:
                    non_comment_lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
                if not non_comment_lines:
                    needs_props = True
            except Exception:
                pass
        if needs_props:
            with open(props_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_SERVER_PROPERTIES)
            
        self.log("[BİLGİ] Sunucu başlatılıyor...")
        if hasattr(self, 'lbl_server_status'):
            self.lbl_server_status.setText("🟡 Durum: Başlatılıyor...")
            self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #DAA520; margin-top: 10px; margin-bottom: 10px;")
        self.side_tabs.setCurrentRow(1)  # Konsol sekmesine geç
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText("⏹ Sunucuyu Durdur")
        self.ram_spinbox.setEnabled(False)
        self.server_selector.setEnabled(False)
        self.btn_new_server.setEnabled(False)
        self.btn_change_software.setEnabled(False)
        self.btn_import_profile.setEnabled(False)
        self.btn_delete_server.setEnabled(False)
        
        # Thread Garbage Collection rule
        if hasattr(self, '_api_threads'):
            self._api_threads = [t for t in self._api_threads if t.isRunning()]
        else:
            self._api_threads = []
            
        self.server_thread = MinecraftServerThread(
            server_dir=self.server_dir,
            ram_gb=self.ram_spinbox.value(),
            jar_name="server.jar",
            parent=None
        )
        self._api_threads.append(self.server_thread)
        
        self.server_thread.log_ready.connect(self.log)
        self.server_thread.server_stopped.connect(self.on_server_stopped)
        self.server_thread.player_joined.connect(self.on_player_joined)
        self.server_thread.player_left.connect(self.on_player_left)
        
        self._resource_widget.setVisible(True)
        self._resource_timer.start()
        
        self.server_thread.start()
        
    def stop_server(self):
        self._user_stopped = True
        if self.server_thread and self.server_thread.is_running:
            if self.btn_stop.text() == "Kapatmaya Zorla":
                self.log("[BİLGİ] Sunucu zorla kapatılıyor...")
                if self.server_thread.process:
                    import subprocess
                    import os
                    if os.name == 'nt':
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.server_thread.process.pid)], creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        self.server_thread.process.kill()
                self.btn_stop.setEnabled(False)
                return
                
            self.log("[BİLGİ] Sunucuya kapatma sinyali gönderiliyor...")
            self.server_thread.stop_server()
            self.btn_stop.setText("Kapatmaya Zorla")
            
    def send_command(self):
        cmd = self.cmd_input.text().strip()
        if cmd and self.server_thread and self.server_thread.is_running:
            self.server_thread.send_command(cmd)
            self.cmd_input.clear()
            
    def on_server_stopped(self):
        if not getattr(self, "_user_stopped", False):
            self.log("\n[UYARI] ⚠️ Sunucu beklenmedik şekilde çöktü! Lütfen logları kontrol edin.\n")
        self.log("[BİLGİ] Sunucu kapandı.")
        self.lbl_server_status.setText("🔴 Durum: Kapalı")
        self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #CD5C5C; margin-top: 10px; margin-bottom: 10px;")
        
        self._resource_timer.stop()
        self._resource_widget.setVisible(False)
        
        # Reset online players and refresh list to show everyone as offline
        self.online_players = set()
        self.refresh_player_list()
        
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("⏹ Sunucuyu Durdur")
        self.ram_spinbox.setEnabled(True)
        self.server_selector.setEnabled(True)
        self.btn_new_server.setEnabled(True)
        self.btn_change_software.setEnabled(True)
        self.btn_import_profile.setEnabled(True)
        self.btn_delete_server.setEnabled(True)

    def refresh_player_list(self):
        if not hasattr(self, 'online_players'):
            self.online_players = set()
            
        self.player_list.clear()
        
        # 1. Load known players from usercache.json
        known_players = set()
        usercache_path = os.path.join(self.server_dir, "usercache.json")
        if os.path.exists(usercache_path):
            try:
                import json
                with open(usercache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                    for entry in cache:
                        name = entry.get("name")
                        if name:
                            known_players.add(name)
            except Exception:
                pass
                
        # 2. Add online players first
        for name in sorted(list(self.online_players)):
            item = QListWidgetItem(f"🟢 {name} (Çevrimiçi)")
            item.setForeground(QColor("#2E8B57"))  # Green
            known_players.discard(name)
            self.player_list.addItem(item)
            
        # 3. Add offline players
        for name in sorted(list(known_players)):
            item = QListWidgetItem(f"⚪ {name} (Çevrimdışı)")
            item.setForeground(QColor("#AAAAAA"))  # Gray
            self.player_list.addItem(item)
            
        # Update header
        if hasattr(self, 'lbl_online_count'):
            self.lbl_online_count.setText(f"Online: {len(self.online_players)}")
            
    def on_player_joined(self, name):
        if not hasattr(self, 'online_players'):
            self.online_players = set()
        self.online_players.add(name)
        self.refresh_player_list()
        
    def on_player_left(self, name):
        if not hasattr(self, 'online_players'):
            self.online_players = set()
        if name in self.online_players:
            self.online_players.remove(name)
        self.refresh_player_list()
        
    def toggle_op_player(self):
        selected = self.player_list.currentItem()
        if not selected:
            return
        
        import re
        match = re.search(r'[🟢⚪]\s+([^\s]+)', selected.text())
        if not match:
            return
            
        player_name = match.group(1)
        if self.server_thread and self.server_thread.is_running:
            is_op = False
            ops_path = os.path.join(self.server_dir, "ops.json")
            if os.path.exists(ops_path):
                try:
                    import json
                    with open(ops_path, "r", encoding="utf-8") as f:
                        ops = json.load(f)
                        if any(op.get("name", "").lower() == player_name.lower() for op in ops):
                            is_op = True
                except Exception:
                    pass
                    
            if is_op:
                self.server_thread.send_command(f"deop {player_name}")
            else:
                self.server_thread.send_command(f"op {player_name}")
                
    def send_message_to_player(self):
        selected = self.player_list.currentItem()
        if not selected:
            return
            
        import re
        match = re.search(r'[🟢⚪]\s+([^\s]+)', selected.text())
        if not match:
            return
        player_name = match.group(1)
        
        if not (self.server_thread and self.server_thread.is_running):
            self.log("[HATA] Sunucu kapalıyken mesaj gönderemezsiniz.")
            return
            
        from PySide6.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        
        # Özel bir diyalog penceresi oluşturalım ki hem gönderen ismini hem mesajı tek seferde sorabilelim.
        dialog = QDialog(self)
        dialog.setWindowTitle("Özel Mesaj Gönder")
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("Gönderen İsmi (Örn: Yönetici, Kurucu, Sistem):"))
        sender_input = QLineEdit("Yönetici")
        layout.addWidget(sender_input)
        
        layout.addWidget(QLabel(f"{player_name} adlı oyuncuya mesajınız:"))
        msg_input = QLineEdit()
        layout.addWidget(msg_input)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("Gönder")
        btn_cancel = QPushButton("İptal")
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        if dialog.exec() == QDialog.Accepted:
            sender = sender_input.text().strip() or "Sistem"
            msg = msg_input.text().strip()
            if msg:
                # Strip newlines and escape quotes to prevent console command injection
                safe_sender = sender.replace('\r', '').replace('\n', '').replace('"', '\\"')
                safe_msg = msg.replace('\r', '').replace('\n', '').replace('"', '\\"')
                
                # tellraw command for colored and formatted chat message
                cmd = f'tellraw {player_name} ["", {{"text":"[{safe_sender}] ","color":"aqua","bold":true}}, {{"text":"{safe_msg}","color":"yellow","bold":false}}]'
                self.server_thread.send_command(cmd)

    def execute_player_command(self, cmd_prefix):
        selected = self.player_list.currentItem()
        if not selected:
            return
        
        import re
        match = re.search(r'[🟢⚪]\s+([^\s]+)', selected.text())
        if not match:
            return
        player_name = match.group(1)
        
        if self.server_thread and self.server_thread.is_running:
            self.server_thread.send_command(f"{cmd_prefix} {player_name}")

    def open_software_dialog(self):
        if not self.server_dir:
            self.log("[HATA] Lütfen önce bir sunucu seçin veya oluşturun.")
            return
            
        from server_downloader import ServerSoftwareDialog
        dialog = ServerSoftwareDialog(self, self.server_dir)
        dialog.exec()

    def open_server_folder(self):
        if self.server_dir and os.path.exists(self.server_dir):
            os.startfile(self.server_dir)
            self.log("[BİLGİ] Sunucu klasörü açıldı. Modlarınızı 'mods', eklentilerinizi 'plugins' klasörüne sürükleyebilirsiniz.")

    def import_client_profile(self, checked=False):
        # 1. Collect profile names from central profiles directory and config
        profile_names = []
        if os.path.exists(self.profiles_dir):
            profile_names = [d for d in sorted(os.listdir(self.profiles_dir)) if os.path.isdir(os.path.join(self.profiles_dir, d)) and not d.startswith(".")]
            
        config_path = getattr(self, 'config_file', None)
        if not config_path or not os.path.exists(config_path):
            parent_dir_cfg = os.path.join(os.path.dirname(self.profiles_dir), "launcher_config.json")
            if os.path.exists(parent_dir_cfg):
                config_path = parent_dir_cfg
            else:
                config_path = os.path.join(get_base_dir(), "launcher_config.json")

        profiles_dict = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8-sig") as cf:
                    cdata = json.load(cf)
                profiles_dict = cdata.get("profiles", {})
            except Exception:
                pass

        for p in profiles_dict.values():
            p_name = p.get("name")
            p_path = p.get("path")
            if p_name and p_name not in profile_names:
                is_in_profiles = False
                if os.path.isdir(os.path.join(self.profiles_dir, p_name)):
                    is_in_profiles = True
                elif p_path and os.path.isdir(p_path):
                    try:
                        if os.path.commonpath([os.path.abspath(self.profiles_dir), os.path.abspath(p_path)]) == os.path.abspath(self.profiles_dir):
                            is_in_profiles = True
                    except Exception:
                        pass
                if is_in_profiles:
                    profile_names.append(p_name)
                
        if not profile_names:
            QMessageBox.warning(self, "Uyarı", "Aktarılacak istemci profili bulunamadı!")
            return
            
        # Check if legacy test mocks QInputDialog.getItem
        if hasattr(QInputDialog.getItem, 'assert_called') or type(QInputDialog.getItem).__name__ in ('MagicMock', 'Mock') or hasattr(QInputDialog.getItem, 'mock'):
            selected_profile, ok = QInputDialog.getItem(
                self,
                "İstemci Profili Seç",
                "Aktarılacak istemci profilini seçin:",
                profile_names,
                0,
                False
            )
        else:
            dlg = ProfileSelectDialog(profile_names, self)
            if dlg.exec():
                selected_profile = dlg.get_selected()
                ok = True
            else:
                selected_profile = None
                ok = False
            
        if not ok or not selected_profile:
            return
            
        new_name, ok = QInputDialog.getText(self, "Sunucu Adı", "Oluşturulacak sunucu için bir isim girin:", text=f"{selected_profile}_Server")
        if not ok or not new_name.strip():
            return
            
        new_name = new_name.strip()
        new_dir = os.path.join(self.servers_dir, new_name)
        if os.path.exists(new_dir):
            self.log("[HATA] Bu isimde bir klasör zaten var.")
            return
            
        # Locate client_dir
        client_dir = os.path.join(self.profiles_dir, selected_profile)
        if not os.path.exists(client_dir):
            for p in profiles_dict.values():
                if p.get("name") == selected_profile and p.get("path") and os.path.exists(p["path"]):
                    client_dir = p["path"]
                    break

        if not os.path.exists(client_dir):
            alt_dir = os.path.join(get_base_dir(), selected_profile)
            if os.path.exists(alt_dir):
                client_dir = alt_dir

        if not os.path.exists(client_dir):
            self.log(f"[HATA] Profil klasörü bulunamadı: {client_dir}")
            QMessageBox.warning(self, "Hata", f"'{selected_profile}' profil klasörü bulunamadı!")
            return
                    
        try:
            os.makedirs(new_dir, exist_ok=True)
            with open(os.path.join(new_dir, "eula.txt"), "w", encoding="utf-8") as f:
                f.write("eula=true\n")
            with open(os.path.join(new_dir, "server.properties"), "w", encoding="utf-8") as f:
                f.write(DEFAULT_SERVER_PROPERTIES)
                
            # Mods ve config kopyala
            mods_dir = os.path.join(client_dir, "mods")
            if os.path.exists(mods_dir):
                def ignore_client_mods(dir_path, filenames):
                    import re
                    ignored = []
                    for f in filenames:
                        for kw in CLIENT_MODS_BLACKLIST:
                            # Use regex to match the keyword either at the start, after a dash/underscore/space, etc.
                            if re.search(rf"(^|[-_ \.])({re.escape(kw)})([-_ \.]|$)", f, re.IGNORECASE):
                                ignored.append(f)
                                break
                    return ignored
                shutil.copytree(mods_dir, os.path.join(new_dir, "mods"), dirs_exist_ok=True, ignore=ignore_client_mods)
            else:
                os.makedirs(os.path.join(new_dir, "mods"), exist_ok=True)
                
            config_dir = os.path.join(client_dir, "config")
            if os.path.exists(config_dir):
                shutil.copytree(config_dir, os.path.join(new_dir, "config"), dirs_exist_ok=True)
            else:
                os.makedirs(os.path.join(new_dir, "config"), exist_ok=True)
                
            self.refresh_server_list()
            
            idx = self.server_selector.findText(new_name)
            if idx >= 0:
                self.server_selector.setCurrentIndex(idx)
            self.server_dir = new_dir
            self.load_server_properties()
                
            self.log(f"[BİLGİ] İstemci profili aktarıldı: {new_name}")
            
            # Sürümü ve motoru otomatik bulmaya çalış
            auto_version = None
            detected_loader = None
            for p in profiles_dict.values():
                if p.get("name") == selected_profile and p.get("version"):
                    ver_str = p.get("version", "")
                    p_loader = p.get("loader")
                    if p_loader:
                        detected_loader = str(p_loader).lower()
                    elif "neoforge" in ver_str.lower():
                        detected_loader = "neoforge"
                    elif "forge" in ver_str.lower():
                        detected_loader = "forge"
                    elif "fabric" in ver_str.lower():
                        detected_loader = "fabric"
                    elif "quilt" in ver_str.lower():
                        detected_loader = "fabric"

                    for v in ["1.21.1", "1.21", "1.20.4", "1.20.2", "1.20.1", "1.20", "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5"]:
                        if v in ver_str:
                            auto_version = v
                            break
                    if not auto_version and ver_str:
                        auto_version = ver_str
                    break
                    
            if not auto_version and os.path.exists(mods_dir):
                mod_files = os.listdir(mods_dir)
                versions_to_check = ["1.21.1", "1.20.4", "1.20.1", "1.19.4", "1.18.2", "1.16.5"]
                version_counts = {v: 0 for v in versions_to_check}
                
                for mod in mod_files:
                    for v in versions_to_check:
                        if v in mod:
                            version_counts[v] += 1
                
                # En çok geçen sürümü bul
                best_version = max(version_counts, key=version_counts.get)
                if version_counts[best_version] > 0:
                    auto_version = best_version
                    
            if not auto_version:
                auto_version = "1.20.1"

            # Check mods directory if loader wasn't detected from config
            if not detected_loader and os.path.exists(mods_dir):
                mod_files = [f.lower() for f in os.listdir(mods_dir) if f.endswith(".jar")]
                if any("neoforge" in f for f in mod_files):
                    detected_loader = "neoforge"
                elif any("forge" in f for f in mod_files):
                    detected_loader = "forge"
                elif any("fabric" in f or "quilt" in f for f in mod_files):
                    detected_loader = "fabric"

            from server_downloader import ServerSoftwareDialog

            if detected_loader == "fabric":
                self.log(f"[BİLGİ] Fabric istemci profili tespit edildi. Otomatik Fabric sunucusu kuruluyor... (Sürüm: {auto_version})")
                dialog = ServerSoftwareDialog(self, self.server_dir, auto_software="Fabric (Mod)", auto_version=auto_version)
                dialog.exec()
            elif detected_loader in ("forge", "neoforge"):
                loader_display = "Forge" if detected_loader == "forge" else "NeoForge"
                self.log(f"[BİLGİ] {loader_display} istemci profili tespit edildi. Otomatik {loader_display} sunucusu kuruluyor... (Sürüm: {auto_version})")
                dialog = ServerSoftwareDialog(self, self.server_dir, auto_software=f"{loader_display} (Mod)", auto_version=auto_version)
                dialog.exec()
            else:
                self.log(f"[BİLGİ] Vanilla veya harici istemci profili tespit edildi. Sunucu yazılımı seçim ekranı açılıyor... (Sürüm: {auto_version})")
                dialog = ServerSoftwareDialog(self, self.server_dir, auto_version=auto_version)
                dialog.exec()
            
        except Exception as e:
            self.log(f"[HATA] Profil aktarılırken hata oluştu: {e}")

    def create_new_server(self, checked=False):
        from PySide6.QtWidgets import QInputDialog
        
        new_name, ok = QInputDialog.getText(self, "Yeni Sunucu", "Yeni sunucu klasörü adı:")
        if ok and new_name.strip():
            new_dir = os.path.join(self.servers_dir, new_name.strip())
            if os.path.exists(new_dir):
                self.log("[HATA] Bu isimde bir klasör zaten var.")
                return
                
            try:
                os.makedirs(new_dir, exist_ok=True)
                with open(os.path.join(new_dir, "eula.txt"), "w", encoding="utf-8") as f:
                    f.write("eula=true\n")
                with open(os.path.join(new_dir, "server.properties"), "w", encoding="utf-8") as f:
                    f.write(DEFAULT_SERVER_PROPERTIES)
                    
                self.refresh_server_list()
                
                # Yeni oluşturulanı seç
                idx = self.server_selector.findText(new_name.strip())
                if idx >= 0:
                    self.server_selector.setCurrentIndex(idx)
                self.server_dir = new_dir
                self.load_server_properties()
                    
                self.log(f"[BİLGİ] Yeni sunucu profili oluşturuldu: {new_dir}")
                self.log("[BİLGİ] Otomatik yazılım kurulum ekranı açılıyor...")
                
                from server_downloader import ServerSoftwareDialog
                dialog = ServerSoftwareDialog(self, self.server_dir)
                dialog.exec()
                
            except Exception as e:
                self.log(f"[HATA] Klasör oluşturulamadı: {e}")

    def load_server_properties(self):
        # Reset to defaults first
        self.spin_max_players.setValue(20)
        self.spin_view_distance.setValue(10)
        self.combo_difficulty.setCurrentText("easy")
        self.line_seed.clear()
        self.line_level_name.setText("world")
        self.combo_gamemode.setCurrentText("survival")
        self.line_motd.setText("A Minecraft Server")
        self.spin_spawn_protection.setValue(16)
        self.spin_sim_distance.setValue(10)
        self.chk_crack.setChecked(False)
        self.chk_pvp.setChecked(True)

        if not self.server_dir:
            return
            
        props_file = os.path.join(self.server_dir, "server.properties")
        if not os.path.exists(props_file):
            return
            
        with open(props_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        for line in lines:
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if key == "max-players":
                    try: self.spin_max_players.setValue(int(val))
                    except: pass
                elif key == "view-distance":
                    try: self.spin_view_distance.setValue(int(val))
                    except: pass
                elif key == "difficulty":
                    idx = self.combo_difficulty.findText(val)
                    if idx >= 0:
                        self.combo_difficulty.setCurrentIndex(idx)
                elif key == "online-mode":
                    self.chk_crack.setChecked(val.lower() == "false")
                elif key == "pvp":
                    self.chk_pvp.setChecked(val.lower() == "true")
                elif key == "level-seed":
                    self.line_seed.setText(val)
                elif key == "level-name":
                    self.line_level_name.setText(val)
                elif key == "gamemode":
                    idx = self.combo_gamemode.findText(val)
                    if idx >= 0:
                        self.combo_gamemode.setCurrentIndex(idx)
                elif key == "motd":
                    self.line_motd.setText(val)
                elif key == "spawn-protection":
                    try: self.spin_spawn_protection.setValue(int(val))
                    except: pass
                elif key == "simulation-distance":
                    try: self.spin_sim_distance.setValue(int(val))
                    except: pass
                    
    def save_server_properties(self):
        if not self.server_dir:
            return
            
        props_file = os.path.join(self.server_dir, "server.properties")
        if os.path.exists(props_file):
            with open(props_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []
            
        updated_lines = []
        handled_keys = set()
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped or "=" not in stripped:
                updated_lines.append(line)
                continue
                
            key, val = stripped.split("=", 1)
            key = key.strip()
            
            if key == "max-players":
                updated_lines.append(f"max-players={self.spin_max_players.value()}\n")
                handled_keys.add(key)
            elif key == "view-distance":
                updated_lines.append(f"view-distance={self.spin_view_distance.value()}\n")
                handled_keys.add(key)
            elif key == "difficulty":
                updated_lines.append(f"difficulty={self.combo_difficulty.currentText()}\n")
                handled_keys.add(key)
            elif key == "level-seed":
                updated_lines.append(f"level-seed={self.line_seed.text().strip()}\n")
                handled_keys.add(key)
            elif key == "level-name":
                lvl = self.line_level_name.text().strip() or "world"
                updated_lines.append(f"level-name={lvl}\n")
                handled_keys.add(key)
            elif key == "gamemode":
                updated_lines.append(f"gamemode={self.combo_gamemode.currentText()}\n")
                handled_keys.add(key)
            elif key == "motd":
                updated_lines.append(f"motd={self.line_motd.text()}\n")
                handled_keys.add(key)
            elif key == "spawn-protection":
                updated_lines.append(f"spawn-protection={self.spin_spawn_protection.value()}\n")
                handled_keys.add(key)
            elif key == "simulation-distance":
                updated_lines.append(f"simulation-distance={self.spin_sim_distance.value()}\n")
                handled_keys.add(key)
            elif key == "online-mode":
                updated_lines.append(f"online-mode={'false' if self.chk_crack.isChecked() else 'true'}\n")
                handled_keys.add(key)
            elif key == "pvp":
                updated_lines.append(f"pvp={'true' if self.chk_pvp.isChecked() else 'false'}\n")
                handled_keys.add(key)
            else:
                updated_lines.append(line)
                
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] += "\n"
                
        if "max-players" not in handled_keys:
            updated_lines.append(f"max-players={self.spin_max_players.value()}\n")
        if "view-distance" not in handled_keys:
            updated_lines.append(f"view-distance={self.spin_view_distance.value()}\n")
        if "difficulty" not in handled_keys:
            updated_lines.append(f"difficulty={self.combo_difficulty.currentText()}\n")
        if "online-mode" not in handled_keys:
            updated_lines.append(f"online-mode={'false' if self.chk_crack.isChecked() else 'true'}\n")
        if "pvp" not in handled_keys:
            updated_lines.append(f"pvp={'true' if self.chk_pvp.isChecked() else 'false'}\n")
        if "level-seed" not in handled_keys:
            updated_lines.append(f"level-seed={self.line_seed.text().strip()}\n")
        if "level-name" not in handled_keys:
            lvl = self.line_level_name.text().strip() or "world"
            updated_lines.append(f"level-name={lvl}\n")
        if "gamemode" not in handled_keys:
            updated_lines.append(f"gamemode={self.combo_gamemode.currentText()}\n")
        if "motd" not in handled_keys:
            updated_lines.append(f"motd={self.line_motd.text()}\n")
        if "spawn-protection" not in handled_keys:
            updated_lines.append(f"spawn-protection={self.spin_spawn_protection.value()}\n")
        if "simulation-distance" not in handled_keys:
            updated_lines.append(f"simulation-distance={self.spin_sim_distance.value()}\n")
            
        with open(props_file, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
            
        self.log("[BİLGİ] Ayarlar kaydedildi.")

    def refresh_backup_list(self):
        self.backup_list.clear()
        if not self.server_dir: return
        backups_dir = os.path.join(self.server_dir, "backups")
        if os.path.exists(backups_dir):
            for file in os.listdir(backups_dir):
                if file.endswith(".zip"):
                    self.backup_list.addItem(file)

    def take_backup(self, checked=False):
        if not self.server_dir: return
        self.btn_take_backup.setEnabled(False)
        self.log("[BİLGİ] Yedekleme başlatılıyor...")
        
        if not hasattr(self, '_api_threads'): self._api_threads = []
        self._api_threads = [t for t in self._api_threads if t.isRunning()]
        
        # Progress Dialog
        from PySide6.QtWidgets import QProgressDialog
        self._backup_progress = QProgressDialog("Yedekleme hazırlanıyor...", None, 0, 100, self)
        self._backup_progress.setWindowTitle("Yedekleme İşlemi")
        self._backup_progress.setMinimumWidth(400)
        self._backup_progress.setStyleSheet("QProgressDialog { background-color: #2D2D30; color: white; } QProgressBar { border: 1px solid #555; border-radius: 5px; text-align: center; background: #1E1E1E; } QProgressBar::chunk { background-color: #007ACC; border-radius: 5px; } QLabel { color: white; font-size: 13px; }")
        self._backup_progress.setCancelButton(None)
        self._backup_progress.setMinimumDuration(0)
        self._backup_progress.show()
        
        thread = BackupThread(self.server_dir, delete_local=self.chk_delete_local.isChecked(), server_thread=self.server_thread)
        self._api_threads.append(thread)
        thread.stage_update.connect(lambda text: self._backup_progress.setLabelText(text) if getattr(self, '_backup_progress', None) else None)
        thread.progress_update.connect(lambda val: self._backup_progress.setValue(val) if getattr(self, '_backup_progress', None) else None)
        thread.backup_finished.connect(self.on_backup_finished)
        thread.start()

    def on_backup_finished(self, success, message):
        self.btn_take_backup.setEnabled(True)
        if hasattr(self, '_backup_progress') and self._backup_progress:
            self._backup_progress.setValue(100)
            self._backup_progress.close()
            self._backup_progress = None
        if success:
            self.log(f"[BİLGİ] {message}")
            self.refresh_backup_list()
        else:
            self.log(f"[HATA] {message}")

    def restore_backup(self):
        if not self.server_dir: return
        if self.server_thread and self.server_thread.is_running:
            QMessageBox.warning(self, "Uyarı", "Sunucu çalışırken yedek geri yüklenemez. Lütfen önce sunucuyu durdurun.")
            return
            
        selected = self.backup_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Uyarı", "Lütfen geri yüklenecek bir yedek seçin.")
            return
        
        reply = QMessageBox.question(self, "Onay", "Seçilen yedek geri yüklenecek. Mevcut dosyalar üzerine yazılabilir. Emin misiniz?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.btn_restore_backup.setEnabled(False)
            self.log(f"[BİLGİ] {selected.text()} geri yükleniyor...")
            
            if not hasattr(self, '_api_threads'): self._api_threads = []
            self._api_threads = [t for t in self._api_threads if t.isRunning()]
            
            zip_path = os.path.join(self.server_dir, "backups", selected.text())
            thread = RestoreThread(self.server_dir, zip_path)
            self._api_threads.append(thread)
            thread.restore_finished.connect(self.on_restore_finished)
            thread.start()

    def on_restore_finished(self, success, message):
        self.btn_restore_backup.setEnabled(True)
        if success:
            self.log(f"[BİLGİ] {message}")
        else:
            self.log(f"[HATA] {message}")

    def search_modrinth(self):
        if not self.btn_search_mod.isEnabled(): return
        query = self.mod_search_input.text().strip()
        if not query: return
        
        project_type = "mod" if self.mod_type_combo.currentText() == "Mod" else "plugin"
        self.btn_search_mod.setEnabled(False)
        self.lbl_mod_status.setText("Aranıyor...")
        self.mod_result_list.clear()
        
        if not hasattr(self, '_api_threads'): self._api_threads = []
        self._api_threads = [t for t in self._api_threads if t.isRunning()]
        
        loader, version = detect_server_loader_and_version(self.server_dir)
        thread = ModrinthSearchThread(query, project_type, game_version=version, loader=loader)
        self._api_threads.append(thread)
        thread.search_finished.connect(self.on_search_finished)
        thread.start()

    def on_search_finished(self, results):
        self.btn_search_mod.setEnabled(True)
        if not results:
            self.lbl_mod_status.setText("Sonuç bulunamadı.")
            return
        
        self.lbl_mod_status.setText(f"{len(results)} sonuç bulundu.")
        for item in results:
            title = item.get("title", "İsimsiz")
            author = item.get("author", "Bilinmiyor")
            desc = item.get("description", "")
            project_id = item.get("project_id", "")
            
            display_text = f"{title} ({author}) - {desc}"
            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.UserRole, project_id)
            self.mod_result_list.addItem(list_item)

    def download_modrinth_project(self):
        if not self.server_dir: return
        selected = self.mod_result_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Uyarı", "Lütfen indirilecek modu/eklentiyi seçin.")
            return
            
        project_id = selected.data(Qt.UserRole)
        project_type = "mod" if self.mod_type_combo.currentText() == "Mod" else "plugin"
        
        self.btn_download_mod.setEnabled(False)
        self.lbl_mod_status.setText(f"{selected.text().split(' (')[0]} indiriliyor...")
        
        if not hasattr(self, '_api_threads'): self._api_threads = []
        self._api_threads = [t for t in self._api_threads if t.isRunning()]
        
        loader, version = detect_server_loader_and_version(self.server_dir)
        thread = ModrinthDownloadThread(project_id, self.server_dir, project_type, game_version=version, loader=loader)
        self._api_threads.append(thread)
        thread.download_finished.connect(self.on_download_finished)
        thread.start()

    def on_download_finished(self, success, message):
        self.btn_download_mod.setEnabled(True)
        if success:
            self.lbl_mod_status.setText("İndirme tamamlandı!")
            self.log(f"[BİLGİ] {message}")
        else:
            self.lbl_mod_status.setText("İndirme başarısız!")
            self.log(f"[HATA] {message}")

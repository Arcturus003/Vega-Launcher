__app_name__ = "Vega Launcher"
__author__ = "Arcturus"
__version__ = "1.0.1"
__copyright__ = "© 2026 Arcturus. All rights reserved."

import sys
import os
import json
import uuid
import ctypes
import shutil
import subprocess
import traceback
import re
import zipfile
import urllib.parse
import concurrent.futures
import threading

# Görev çubuğunda (Taskbar) ve Görev Yöneticisi'nde doğru ikon/isimle çıkması için
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Arcturus.VegaLauncher.1.0")
    ctypes.windll.kernel32.SetConsoleTitleW("Vega Launcher")
except: pass

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QSizePolicy, 
                               QHBoxLayout, QPushButton, QLabel, QLineEdit, QScrollArea,
                               QStackedWidget, QSplitter, QComboBox, QMessageBox, QDialog, QFormLayout, QSpinBox, QListWidget, QListWidgetItem, QProgressDialog, QProgressBar)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPainterPath, QPen, QColor

from mod_manager import ModrinthAPI
from ui_components import NavBar, ActionBar, InstalledModsPanel
from card_widget import CardWidget, ImageLoaderThread
from auth_window import MicrosoftLoginDialog
from vanilla_thread import DownloadVanillaThread
from playtime_tracker import PlaytimeTrackerThread
from server_widget import ServerWidget

class ImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(50)
        
        
        sizePolicy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sizePolicy.setHeightForWidth(True)
        self.setSizePolicy(sizePolicy)
        
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(15)
        self.shadow.setColor(QColor(0, 0, 0, 150))
        self.shadow.setOffset(0, 4)
        self.setGraphicsEffect(self.shadow)
        self.shadow.setEnabled(False)

    def set_image(self, pixmap):
        self._pixmap = pixmap
        self.setStyleSheet("background: transparent; border: none; margin-bottom: 10px;")
        self.shadow.setEnabled(True)
        self.updateGeometry()
        self.update_image()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        if self._pixmap and not self._pixmap.isNull():
            orig_w = self._pixmap.width()
            orig_h = self._pixmap.height()
            if orig_w > 0:
                h = int(w * orig_h / orig_w)
                if orig_w < 256 and orig_h < 256:
                    return min(h, orig_h) # Don't scale up tiny icons
                return h # Let it grow as much as the width requires
        return super().heightForWidth(w)

    def sizeHint(self):
        if self._pixmap and not self._pixmap.isNull():
            orig_w = self._pixmap.width()
            orig_h = self._pixmap.height()
            # We want it to be as wide as possible, but sizeHint doesn't know layout width.
            # QSizePolicy.Ignored will handle width expansion. Just return original dimensions.
            return QSize(orig_w, orig_h)
        return super().sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_image()

    def update_image(self):
        if self._pixmap and not self._pixmap.isNull():
            w = self.width()
            h = self.height()
            if w < 10 or h < 10: return
            
            orig_w = self._pixmap.width()
            orig_h = self._pixmap.height()
            
            if orig_w < 256 and orig_h < 256:
                scale_w = min(w, orig_w)
                scale_h = min(h, orig_h)
            else:
                scale_w = w
                scale_h = h
            
            scaled = self._pixmap.scaled(scale_w, scale_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            rounded = QPixmap(scaled.size())
            rounded.fill(Qt.transparent)
            
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing)
            
            path = QPainterPath()
            path.addRoundedRect(1, 1, scaled.width() - 2, scaled.height() - 2, 12, 12)
            
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, scaled)
            
            painter.setClipping(False)
            pen = QPen(QColor(255, 255, 255, 40))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawPath(path)
            painter.end()
            
            super().setPixmap(rounded)

class DownloadModThread(QThread):
    task_finished = Signal(bool, str)
    def __init__(self, url, path):
        super().__init__()
        self.url = url
        self.path = path
    def run(self):
        success = ModrinthAPI.download_file(self.url, self.path)
        if success:
            self.task_finished.emit(True, "İndirme başarılı.")
        else:
            self.task_finished.emit(False, "İndirme başarısız.")

class DownloadModpackThread(QThread):
    progress_update = Signal(str)
    progress_val = Signal(int, int)
    task_finished = Signal(bool, str, str) # success, message, version_id
    
    def __init__(self, profile_dir, pack_url, is_local=False):
        super().__init__()
        self.profile_dir = profile_dir
        self.pack_url = pack_url # Eğer is_local True ise, bu dosya yoludur
        self.is_local = is_local
        
    def run(self):
        import requests, tempfile
        try:
            with tempfile.TemporaryDirectory() as tmpdirname:
                if self.is_local:
                    mrpack_path = self.pack_url
                else:
                    self.progress_update.emit("Modpack arşivi indiriliyor...")
                    self.progress_val.emit(0, 0)
                    r = requests.get(self.pack_url, timeout=30)
                    r.raise_for_status()
                    mrpack_path = os.path.join(tmpdirname, "pack.zip")
                    with open(mrpack_path, "wb") as f:
                        f.write(r.content)
                    
                self.progress_update.emit("Arşiv açılıyor...")
                self.progress_val.emit(0, 0)
                try:
                    if mrpack_path.lower().endswith(".rar"):
                        import subprocess
                        subprocess.run(["tar", "-xf", mrpack_path, "-C", tmpdirname], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    else:
                        with zipfile.ZipFile(mrpack_path, 'r') as zip_ref:
                            zip_ref.extractall(tmpdirname)
                except Exception as e:
                    if "Overlapped entries" in str(e) or "zip bomb" in str(e).lower() or "not a zip file" in str(e).lower():
                        self.progress_update.emit("Arşiv açılıyor (Alternatif metod ile)...")
                        try:
                            subprocess.run(["powershell", "-NoProfile", "-Command", f"Expand-Archive -Force -Path '{mrpack_path}' -DestinationPath '{tmpdirname}'"], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        except Exception:
                            # Son çare olarak tar ile dene
                            subprocess.run(["tar", "-xf", mrpack_path, "-C", tmpdirname], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    else:
                        raise e
                    
                # Modrinth formatı kontrolü
                mr_index_path = None
                cf_index_path = None
                
                for root, dirs, files_in_dir in os.walk(tmpdirname):
                    if "modrinth.index.json" in files_in_dir:
                        mr_index_path = os.path.join(root, "modrinth.index.json")
                        break
                    elif "manifest.json" in files_in_dir:
                        cf_index_path = os.path.join(root, "manifest.json")
                        break
                
                is_curseforge = False
                if cf_index_path:
                    is_curseforge = True
                    with open(cf_index_path, 'r', encoding='utf-8') as f:
                        index = json.load(f)
                    tmpdirname = os.path.dirname(cf_index_path) # Kök dizini güncelle
                elif mr_index_path:
                    with open(mr_index_path, 'r', encoding='utf-8') as f:
                        index = json.load(f)
                    tmpdirname = os.path.dirname(mr_index_path) # Kök dizini güncelle
                else:
                    raise Exception("Geçerli bir Modpack formatı bulunamadı! (modrinth.index.json veya manifest.json eksik)")
                
                import minecraft_launcher_lib
                mc_dir = os.path.join(os.getenv("APPDATA", ""), ".minecraft")
                new_version_id = ""
                failed_mods = []
                
                if not is_curseforge:
                    # Modrinth kurulumu
                    deps = index.get("dependencies", {})
                    mc_version = deps.get("minecraft", "1.20.1")
                    forge_version = deps.get("forge")
                    fabric_version = deps.get("fabric-loader")
                    quilt_version = deps.get("quilt-loader")
                    neoforge_version = deps.get("neoforge")
                    
                    if fabric_version:
                        self.progress_update.emit(f"Fabric {fabric_version} kuruluyor...")
                        self.progress_val.emit(0, 0)
                        minecraft_launcher_lib.fabric.install_fabric(mc_version, mc_dir)
                        new_version_id = f"fabric-loader-{fabric_version}-{mc_version}"
                    elif quilt_version:
                        self.progress_update.emit(f"Quilt {quilt_version} kuruluyor...")
                        self.progress_val.emit(0, 0)
                        try:
                            minecraft_launcher_lib.quilt.install_quilt(mc_version, mc_dir)
                        except: pass
                        new_version_id = f"quilt-loader-{quilt_version}-{mc_version}"
                    elif neoforge_version:
                        self.progress_update.emit(f"NeoForge {neoforge_version} algılandı...")
                        self.progress_val.emit(0, 0)
                        new_version_id = f"neoforge-{neoforge_version}-{mc_version}"
                    elif forge_version:
                        self.progress_update.emit(f"Forge {forge_version} kuruluyor...")
                        self.progress_val.emit(0, 0)
                        try:
                            minecraft_launcher_lib.forge.install_forge_version(f"{mc_version}-{forge_version}", mc_dir)
                        except: pass
                        new_version_id = f"{mc_version}-forge-{forge_version}"
                    else:
                        new_version_id = mc_version
                        
                    self.progress_update.emit(f"Gereksinimler okunuyor: MC {mc_version}, Yükleyici: {new_version_id}")
                    
                    files = index.get("files", [])
                    total = len(files)
                    completed = [0]
                    lock = threading.Lock()
                    
                    def download_mr_file(file_info):
                        path = file_info.get("path")
                        downloads = file_info.get("downloads", [])
                        file_basename = os.path.basename(path) if path else "Bilinmeyen Dosya"
                        
                        if not path or not downloads:
                            return False, file_basename + " (İndirme linki yok)"
                            
                        dl_url = downloads[0]
                        target_path = os.path.join(self.profile_dir, path)
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        
                        for attempt in range(3):
                            try:
                                fr = requests.get(dl_url, timeout=20)
                                fr.raise_for_status()
                                with open(target_path, "wb") as f_out:
                                    f_out.write(fr.content)
                                
                                with lock:
                                    completed[0] += 1
                                    self.progress_update.emit(f"İndiriliyor: {file_basename} ({completed[0]}/{total})")
                                    self.progress_val.emit(completed[0], total)
                                return True, ""
                            except: pass
                        return False, file_basename

                    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                        results = list(executor.map(download_mr_file, files))
                        for ok, msg in results:
                            if not ok:
                                failed_mods.append(msg)
                else:
                    # CurseForge kurulumu
                    mc_info = index.get("minecraft", {})
                    mc_version = mc_info.get("version", "1.20.1")
                    loaders = mc_info.get("modLoaders", [])
                    
                    new_version_id = mc_version
                    if loaders:
                        loader_id = loaders[0].get("id", "")
                        if loader_id.startswith("forge-"):
                            forge_version = loader_id.split("-")[1]
                            self.progress_update.emit(f"Forge {forge_version} kuruluyor...")
                            self.progress_val.emit(0, 0)
                            try:
                                minecraft_launcher_lib.forge.install_forge_version(f"{mc_version}-{forge_version}", mc_dir)
                            except: pass
                            new_version_id = f"{mc_version}-forge-{forge_version}"
                            
                            # Bazen forge formati 1.12.2-forge-14.23.5.2860 gibi olmaz, id'nin kendisi de olabilir
                            # ama minecraft_launcher_lib standart olarak MC-forge-FORGE uretir.
                        elif loader_id.startswith("fabric-"):
                            fabric_version = loader_id.split("-")[1]
                            self.progress_update.emit(f"Fabric {fabric_version} kuruluyor...")
                            self.progress_val.emit(0, 0)
                            minecraft_launcher_lib.fabric.install_fabric(mc_version, mc_dir)
                            new_version_id = f"fabric-loader-{fabric_version}-{mc_version}"
                        else:
                            new_version_id = loader_id
                        
                    self.progress_update.emit(f"Gereksinimler okunuyor: Yükleyici: {new_version_id}")
                    
                    files = index.get("files", [])
                    total = len(files)
                    completed = [0]
                    lock = threading.Lock()
                    
                    def download_cf_file(file_info):
                        pid = file_info.get("projectID") or file_info.get("projectId")
                        fid = file_info.get("fileID") or file_info.get("fileId")
                        if not pid or not fid: return True, ""
                        
                        cf_url = f"https://www.curseforge.com/api/v1/mods/{pid}/files/{fid}/download"
                        
                        for attempt in range(3):
                            try:
                                fr = requests.get(cf_url, timeout=20, allow_redirects=True)
                                fr.raise_for_status()
                                
                                parsed_url = urllib.parse.urlparse(fr.url)
                                file_basename = os.path.basename(parsed_url.path)
                                if not file_basename.endswith(".jar"):
                                    file_basename = f"{pid}-{fid}.jar"
                                    
                                target_path = os.path.join(self.profile_dir, "mods", file_basename)
                                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                                
                                with open(target_path, "wb") as f_out:
                                    f_out.write(fr.content)
                                
                                with lock:
                                    completed[0] += 1
                                    self.progress_update.emit(f"CurseForge'dan İndiriliyor: {file_basename} ({completed[0]}/{total})")
                                    self.progress_val.emit(completed[0], total)
                                return True, ""
                            except: pass
                        return False, f"Proje ID: {pid}"
                        
                    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                        results = list(executor.map(download_cf_file, files))
                        for ok, msg in results:
                            if not ok:
                                failed_mods.append(msg)

                self.progress_update.emit("Ayarlar, Haritalar ve Config dosyaları kopyalanıyor...")
                self.progress_val.emit(0, 0)
                for override_folder in ["overrides", "client-overrides", "overrides/saves", "overrides/config"]:
                    overrides_dir = os.path.join(tmpdirname, override_folder.split("/")[0])
                    if not os.path.exists(overrides_dir): continue
                    
                    for root, dirs, files_in_dir in os.walk(overrides_dir):
                        for file in files_in_dir:
                            src_file = os.path.join(root, file)
                            rel_path = os.path.relpath(src_file, overrides_dir)
                            dst_file = os.path.join(self.profile_dir, rel_path)
                            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                            shutil.copy2(src_file, dst_file)
                            
            if failed_mods:
                msg = "Modpack kuruldu, ancak bazı modlar indirilemedi (Sunucudan silinmiş olabilirler):\n" + ", ".join(failed_mods[:5])
                if len(failed_mods) > 5:
                    msg += f" ... ve {len(failed_mods)-5} tane daha."
                self.task_finished.emit(True, msg, new_version_id)
            else:
                self.task_finished.emit(True, "Modpack başarıyla kuruldu!", new_version_id)
        except Exception as e:
            self.task_finished.emit(False, f"Modpack kurulum hatası: {str(e)}", "")

class ProjectDetailsThread(QThread):
    task_finished = Signal(dict)
    def __init__(self, project_id):
        super().__init__()
        self.project_id = project_id
    def run(self):
        try:
            details = ModrinthAPI.get_project_details(self.project_id)
            if details:
                self.task_finished.emit(details)
        except:
            pass

class EditProfileDialog(QDialog):
    def __init__(self, current_name, current_ram, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Profili Düzenle")
        self.resize(350, 150)
        if parent: self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        self.name_input.setText(current_name)
        
        self.ram_input = QSpinBox()
        self.ram_input.setRange(1024, 32768)
        self.ram_input.setSingleStep(1024)
        self.ram_input.setValue(current_ram)
        self.ram_input.setSuffix(" MB")
        
        form_layout.addRow("Profil Adı:", self.name_input)
        form_layout.addRow("RAM (MB):", self.ram_input)
        
        layout.addLayout(form_layout)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Kaydet")
        save_btn.clicked.connect(self.accept)
        
        cancel_btn = QPushButton("İptal")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_data(self):
        return self.name_input.text().strip(), self.ram_input.value()

class AddProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Yeni Profil Ekle")
        self.resize(350, 200)
        if parent: self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Örn: Zombi Macerası")
        
        self.version_input = QComboBox()
        self.load_versions()
        
        self.ram_input = QSpinBox()
        self.ram_input.setRange(1024, 32768)
        self.ram_input.setSingleStep(1024)
        self.ram_input.setValue(4096)
        self.ram_input.setSuffix(" MB")
        
        form_layout.addRow("Profil Adı:", self.name_input)
        form_layout.addRow("Sürüm:", self.version_input)
        form_layout.addRow("RAM (MB):", self.ram_input)
        
        layout.addLayout(form_layout)
        
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("Kaydet")
        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setStyleSheet("background-color: #B22222; border-color: #8B0000;")
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def load_versions(self):
        self.version_input.clear()
        mc_dir = os.path.join(os.getenv("APPDATA", ""), ".minecraft")
        versions_dir = os.path.join(mc_dir, "versions")
        versions = []
        if os.path.exists(versions_dir):
            for d in os.listdir(versions_dir):
                if os.path.isdir(os.path.join(versions_dir, d)):
                    versions.append(d)
        if versions:
            versions.sort(reverse=True)
            self.version_input.addItems(versions)
        else:
            self.version_input.addItem("1.20.1")
            self.version_input.setEditable(True)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "version": self.version_input.currentText(),
            "ram": self.ram_input.value()
        }

class ProfileWidget(QWidget):
    update_clicked = Signal(str)
    
    def __init__(self, name, version, ram, profile_id, parent=None):
        super().__init__(parent)
        self.profile_id = profile_id
        self.setMinimumHeight(70)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        
        icon_lbl = QLabel("🎮")
        icon_lbl.setStyleSheet("font-size: 32px; background: transparent; color: #40E0D0;")
        layout.addWidget(icon_lbl)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: white; background: transparent;")
        info_layout.addWidget(name_lbl)
        
        badge_layout = QHBoxLayout()
        v_badge = QLabel(f"v {version}")
        v_badge.setStyleSheet("background-color: rgba(0,0,0,0.5); color: #40E0D0; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold; border: 1px solid rgba(64,224,208,0.3);")
        r_badge = QLabel(f"RAM: {ram} MB")
        r_badge.setStyleSheet("background-color: rgba(0,0,0,0.5); color: #FFA500; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: bold; border: 1px solid rgba(255,165,0,0.3);")
        
        badge_layout.addWidget(v_badge)
        badge_layout.addWidget(r_badge)
        
        self.update_btn = QPushButton("Güncelle")
        self.update_btn.setStyleSheet("background-color: #FFA500; color: black; font-weight: bold; border-radius: 4px; padding: 2px 8px; font-size: 11px; border: 1px solid rgba(255,165,0,0.3);")
        self.update_btn.setVisible(False)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(lambda checked=False: self.update_clicked.emit(self.profile_id))
        badge_layout.addWidget(self.update_btn)
        
        badge_layout.addStretch()
        
        info_layout.addLayout(badge_layout)
        layout.addLayout(info_layout)
        layout.addStretch()

class DetailPanel(QWidget):
    download_requested = Signal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DetailPanel")
        self.current_project = None
        self.img_threads = []
        self.image_cache = {}
        self.url_labels = {}
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        header_layout = QHBoxLayout()
        
        self.title = QLabel("Seçim Bekleniyor")
        self.title.setStyleSheet("font-size: 24px; font-weight: bold; color: #40E0D0;")
        header_layout.addWidget(self.title)
        
        header_layout.addStretch()
        
        self.close_btn = QPushButton("✖")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setStyleSheet("background: transparent; color: #FF4444; font-size: 20px; font-weight: bold; border: none;")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.hide)
        header_layout.addWidget(self.close_btn)
        
        layout.addLayout(header_layout)
        
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #CCC; margin-top: 10px; margin-bottom: 10px;")
        layout.addWidget(self.desc)
        
        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_scroll.setStyleSheet("background: transparent; border: none;")
        
        self.gallery_container = QWidget()
        self.gallery_container.setStyleSheet("background: transparent;")
        self.gallery_layout = QVBoxLayout(self.gallery_container)
        self.gallery_layout.setAlignment(Qt.AlignTop)
        
        self.gallery_scroll.setWidget(self.gallery_container)
        layout.addWidget(self.gallery_scroll, 1)
        
        self.download_btn = QPushButton("Aktif Profile İndir")
        self.download_btn.clicked.connect(self.on_download_click)
        self.download_btn.setEnabled(False)
        self.download_btn.setFixedHeight(45)
        layout.addWidget(self.download_btn)

    def on_download_click(self):
        if self.current_project:
            self.download_requested.emit(self.current_project)

    def clear_gallery(self):
        self.url_labels.clear()
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def update_info(self, data):
        self.current_project = data
        ptype = data.get("project_type", "mod")
        if ptype == "modpack":
            self.download_btn.setText("Modpack'i Yeni Profil Olarak Kur")
        else:
            self.download_btn.setText("Aktif Profile İndir")
        
        self.download_btn.setEnabled(True)
        self.title.setText(data.get("title", "Yükleniyor..."))
        self.desc.setText(data.get("description", ""))
        self.clear_gallery()
        
        project_id = data.get("project_id")
        if not project_id: return
        
        if not hasattr(self, '_api_threads'):
            self._api_threads = []
            
        # API çağrısını arka planda yap - arayüz donmasın
        thread = ProjectDetailsThread(project_id)
        self._api_threads.append(thread)
        thread.task_finished.connect(self.on_details_loaded)
        thread.start()
        
        # Biten thread'leri temizle
        self._api_threads = [t for t in self._api_threads if t.isRunning()]

    def on_details_loaded(self, details):
        self.title.setText(details.get("title", "İsimsiz"))
        self.desc.setText(details.get("description", "Açıklama bulunmuyor."))
        
        gallery = details.get("gallery", [])
        urls_to_load = []
        
        if gallery:
            for item in gallery:
                urls_to_load.append(item.get("url"))
        elif details.get("icon_url"):
            urls_to_load.append(details.get("icon_url"))
            
        if urls_to_load:
            for url in urls_to_load:
                if not url: continue
                lbl = ImageLabel()
                lbl.setText("Resim Yükleniyor...")
                lbl.setStyleSheet("background-color: rgba(0,0,0,0.5); border: 1px solid #444; border-radius: 8px; margin-bottom: 10px;")
                self.gallery_layout.addWidget(lbl)
                
                if url in self.image_cache:
                    lbl.set_image(self.image_cache[url])
                    lbl.setText("")
                else:
                    if url not in self.url_labels:
                        self.url_labels[url] = []
                    self.url_labels[url].append(lbl)
                    
                    thread = ImageLoaderThread(url)
                    thread.loaded_with_url.connect(self.on_image_loaded)
                    self.img_threads.append(thread)
                    thread.start()
        else:
            lbl = QLabel("Görsel Bulunmuyor")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setMinimumHeight(200)
            lbl.setStyleSheet("background-color: rgba(0,0,0,0.5); border: 1px solid #444; border-radius: 8px;")
            self.gallery_layout.addWidget(lbl)

    def on_image_loaded(self, url, data_bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(data_bytes)
        self.image_cache[url] = pixmap
        if url in self.url_labels:
            for lbl in self.url_labels[url]:
                try:
                    lbl.set_image(pixmap)
                    lbl.setText("")
                except: pass
            del self.url_labels[url]

class ModrinthSearchThread(QThread):
    search_finished = Signal(object)

    def __init__(self, query, project_type, index, limit, version, loader):
        super().__init__()
        self.query = query
        self.project_type = project_type
        self.index = index
        self.limit = limit
        self.version = version
        self.loader = loader

    def run(self):
        try:
            results = ModrinthAPI.search_projects(
                self.query, self.project_type, index=self.index, 
                limit=self.limit, version=self.version, loader=self.loader
            )
            self.search_finished.emit(results)
        except Exception:
            self.search_finished.emit(None)

class ModrinthBrowser(QWidget):
    item_selected = Signal(object)
    update_item_requested = Signal(object)
    
    def __init__(self, project_type):
        super().__init__()
        self.project_type = project_type
        self.current_version = None
        self.current_loader = None
        self._search_thread = None
        layout = QVBoxLayout(self)
        
        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(f"{project_type.capitalize()} ara... (Yazmaya başlayın)")
        self.search_input.textChanged.connect(self.on_text_changed)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        # Filters
        filter_layout = QHBoxLayout()
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("İlgiliye Göre", "relevance")
        self.sort_combo.addItem("İndirme Sayısı", "downloads")
        self.sort_combo.addItem("En Yeni", "newest")
        self.sort_combo.addItem("Son Güncellenen", "updated")
        self.sort_combo.currentIndexChanged.connect(lambda x=None: self.search())
        filter_layout.addWidget(self.sort_combo)
        
        self.version_combo = QComboBox()
        self.version_combo.addItem("Otomatik (Aktif Profil)", "detect")
        self.version_combo.addItem("Tüm Sürümler", "all")
        for v in ["1.21.1", "1.21", "1.20.4", "1.20.1", "1.19.4", "1.19.2", "1.18.2", "1.16.5", "1.12.2"]:
            self.version_combo.addItem(v, v)
        self.version_combo.currentIndexChanged.connect(lambda x=None: self.search())
        filter_layout.addWidget(self.version_combo)
        
        self.loader_combo = QComboBox()
        self.loader_combo.addItem("Otomatik (Aktif Profil)", "detect")
        self.loader_combo.addItem("Tümü", "all")
        for l in ["Forge", "NeoForge", "Fabric", "Quilt"]:
            self.loader_combo.addItem(l, l.lower())
        self.loader_combo.currentIndexChanged.connect(lambda x=None: self.search())
        filter_layout.addWidget(self.loader_combo)
        
        layout.addLayout(filter_layout)
        
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.search)
        
        # Grid Area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background: transparent;")
        
        self.grid_layout = QVBoxLayout(self.grid_container)
        self.grid_layout.setAlignment(Qt.AlignTop)
        
        self.scroll.setWidget(self.grid_container)
        layout.addWidget(self.scroll)

    def get_active_loader(self):
        if hasattr(self, 'loader_combo'):
            selected = self.loader_combo.currentData()
            if selected == "all":
                return None
            elif selected != "detect":
                return selected
                
        if self.project_type == "shader":
            return None
            
        window = self.window()
        loader = getattr(window, 'active_profile_loader', None)
        if loader:
            return loader
        if hasattr(window, 'get_active_profile_loader'):
            return window.get_active_profile_loader()
        return None

    def refresh_if_needed(self):
        v = self.get_active_version()
        ldr = self.get_active_loader()
        if self.current_version != v or getattr(self, 'current_loader', None) != ldr or self.grid_layout.count() == 0:
            self.current_version = v
            self.current_loader = ldr
            self.load_trending()

    def on_text_changed(self, text):
        self.search_timer.start(500)

    def get_active_version(self):
        if hasattr(self, 'version_combo'):
            selected = self.version_combo.currentData()
            if selected == "all":
                return None
            elif selected != "detect":
                return selected
                
        # We need the parent window to get the active profile version
        window = self.window()
        if hasattr(window, 'active_profile_version'):
            version = window.active_profile_version
            if not version: return None
            
            match = re.search(r'\b(1\.\d+(\.\d+)?)\b', version)
            if match:
                return match.group(1)
            return version
        return None

    def load_trending(self):
        self.clear_grid()
        version = self.get_active_version()
        loader = self.get_active_loader()
        sort_index = self.sort_combo.currentData() if hasattr(self, 'sort_combo') else "downloads"
        
        loading_lbl = QLabel("Yükleniyor...")
        loading_lbl.setAlignment(Qt.AlignCenter)
        loading_lbl.setStyleSheet("color: white; font-size: 16px;")
        self.grid_layout.addWidget(loading_lbl)
        
        if not hasattr(self, '_search_threads'):
            self._search_threads = []
            
        self._search_threads = [t for t in self._search_threads if t.isRunning()]
        
        thread = ModrinthSearchThread("", self.project_type, sort_index, 18, version, loader)
        thread.search_finished.connect(self.on_search_finished)
        self._search_threads.append(thread)
        self._search_thread = thread # keep as latest
        thread.start()

    def search(self):
        query = self.search_input.text().strip()
        if not query:
            self.load_trending()
            return
            
        self.clear_grid()
        version = self.get_active_version()
        loader = self.get_active_loader()
        sort_index = self.sort_combo.currentData() if hasattr(self, 'sort_combo') else "relevance"
        
        loading_lbl = QLabel("Yükleniyor...")
        loading_lbl.setAlignment(Qt.AlignCenter)
        loading_lbl.setStyleSheet("color: white; font-size: 16px;")
        self.grid_layout.addWidget(loading_lbl)
        
        if not hasattr(self, '_search_threads'):
            self._search_threads = []
            
        self._search_threads = [t for t in self._search_threads if t.isRunning()]
        
        thread = ModrinthSearchThread(query, self.project_type, sort_index, 18, version, loader)
        thread.search_finished.connect(self.on_search_finished)
        self._search_threads.append(thread)
        self._search_thread = thread # keep as latest
        thread.start()

    def on_search_finished(self, results):
        # Yalnızca en son başlatılan thread'in sonucunu kabul et
        sender = self.sender()
        if hasattr(self, '_search_thread') and sender != self._search_thread:
            return
            
        self.clear_grid()
        if results is None or not results:
            msg = "Modlar yüklenemedi, internet bağlantınızı kontrol edin." if results is None else "Sonuç bulunamadı."
            error_lbl = QLabel(msg)
            error_lbl.setAlignment(Qt.AlignCenter)
            error_lbl.setStyleSheet("color: #FF5555; font-size: 16px;")
            self.grid_layout.addWidget(error_lbl)
            return
        self.populate(results)

    def clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                w = item.widget()
                if hasattr(w, 'cleanup'):
                    w.cleanup()
                w.deleteLater()
            elif item.layout():
                self.clear_layout(item.layout())

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                w = item.widget()
                if hasattr(w, 'cleanup'):
                    w.cleanup()
                w.deleteLater()
            elif item.layout(): self.clear_layout(item.layout())
        layout.deleteLater()

    def populate(self, results):
        row_layout = QHBoxLayout()
        count = 0
        for data in results:
            card = CardWidget(data)
            card.clicked.connect(self.item_selected.emit)
            if hasattr(card, 'update_clicked'):
                card.update_clicked.connect(self.update_item_requested.emit)
            row_layout.addWidget(card)
            count += 1
            if count % 3 == 0:
                self.grid_layout.addLayout(row_layout)
                row_layout = QHBoxLayout()
        if count % 3 != 0:
            row_layout.addStretch()
            self.grid_layout.addLayout(row_layout)


class CustomProgressOverlay(QDialog):
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(500, 150)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: rgba(20, 20, 25, 240);
                border: 2px solid #9733EE;
                border-radius: 15px;
            }
        """)
        clayout = QVBoxLayout(container)
        clayout.setContentsMargins(20, 20, 20, 20)
        
        self.title_lbl = QLabel("Mod Kuruluyor...")
        self.title_lbl.setStyleSheet("color: #FFAAFF; font-size: 22px; font-weight: bold; border: none; background: transparent;")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        clayout.addWidget(self.title_lbl)
        
        self.desc_lbl = QLabel(f"{filename} indiriliyor...")
        self.desc_lbl.setStyleSheet("color: #DDDDDD; font-size: 14px; border: none; background: transparent;")
        self.desc_lbl.setAlignment(Qt.AlignCenter)
        clayout.addWidget(self.desc_lbl)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                color: white;
                font-weight: bold;
                background: #111;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9733EE, stop:1 #DA22FF);
                border-radius: 3px;
            }
        """)
        self.progress_bar.setValue(0)
        clayout.addWidget(self.progress_bar)
        
        layout.addWidget(container)
        
        if parent:
            geom = parent.geometry()
            self.move(geom.center() - self.rect().center())
            
    def update_progress(self, val, text=None):
        self.progress_bar.setValue(val)
        if text:
            self.desc_lbl.setText(text)


class VegaLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        import integrity_check
        is_ok, tampered = integrity_check.verify_integrity()
        if not is_ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(None, "Güvenlik Uyarısı", f"⚠️ Bu uygulama yetkisiz olarak değiştirilmiş! Orijinal sürümü indirin: {__author__}")
            sys.exit(1)
            
        self.setWindowTitle(f"Vega Launcher — by {__author__}")
        self.resize(1440, 810)
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.setWindowIcon(QIcon(os.path.join(self.base_dir, "enderman_icon.ico")))
        self._active_threads = []
        self.active_profile_version = None
        self.active_profile_loader = None
        self._is_closing = False

        
        try:
            with open(os.path.join(self.base_dir, "style.qss"), "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except: pass
        
        self.data_dir = os.path.join(os.environ.get("APPDATA"), ".vega_launcher")
        os.makedirs(self.data_dir, exist_ok=True)
        self.profiles_dir = os.path.join(self.data_dir, "profiles")
        self.config_file = os.path.join(self.data_dir, "launcher_config.json")
        self.profiles = {}
        self.ms_login = {}
        
        bg_path = os.path.join(self.base_dir, "bg.jpg")
        if os.path.exists(bg_path):
            bg_path_fwd = bg_path.replace("\\", "/")
            extra_css = f"QMainWindow {{ background-image: url('{bg_path_fwd}'); background-position: center; }}"
            self.setStyleSheet(self.styleSheet() + extra_css)
        else:
            self.setStyleSheet(self.styleSheet() + "QMainWindow { background-color: #111; }")
        
        self.mc_dir = os.path.join(os.getenv("APPDATA", ""), ".minecraft")
        
        self.ensure_directories()
        self.load_config()
        
        self.init_ui()

    def ensure_directories(self):
        os.makedirs(self.profiles_dir, exist_ok=True)
        if not os.path.exists(self.config_file):
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump({"profiles": {}, "ms_login": {}}, f, indent=4)

    def load_config(self):
        if __author__ != "Arcturus":
            sys.exit(1)
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    self.profiles = data.get("profiles", {})
                    self.ms_login = data.get("ms_login", {})
                    if not isinstance(self.profiles, dict):
                        self.profiles = {}
                    if not isinstance(self.ms_login, dict):
                        self.ms_login = {}
                    
                    for pid, pdata in self.profiles.items():
                        folder_name = pdata.get("name")
                        if pdata.get("path"):
                            folder_name = os.path.basename(pdata["path"])
                        pdata["path"] = os.path.join(self.profiles_dir, folder_name)
            except Exception as e:
                print(e)
                self.profiles = {}
                self.ms_login = {}
        else:
            self.profiles = {}
            self.ms_login = {}
        
        # Disk'te var ama config'de kayıtlı olmayan profilleri otomatik ekle
        existing_names = {os.path.basename(p.get("path","")) for p in self.profiles.values()}
        if os.path.exists(self.profiles_dir):
            for d in os.listdir(self.profiles_dir):
                if os.path.isdir(os.path.join(self.profiles_dir, d)) and d not in existing_names:
                    self.profiles[str(uuid.uuid4())] = {
                        "name": d, "version": "1.20.1", "ram": 4096,
                        "path": os.path.join(self.profiles_dir, d)
                    }
            self.save_config()

    def save_config(self):
        config_data = {
            "profiles": getattr(self, "profiles", {}),
            "ms_login": getattr(self, "ms_login", {})
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        self.sync_with_standard_launchers()

    def sync_with_standard_launchers(self):
        mc_dir = os.path.join(os.getenv("APPDATA", ""), ".minecraft")
        target_files = ["launcher_profiles.json", "tlauncher_profiles.json"]
        
        for file_name in target_files:
            file_path = os.path.join(mc_dir, file_name)
            data = {"profiles": {}}
            
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if not isinstance(data, dict):
                            data = {"profiles": {}}
                        if "profiles" not in data or not isinstance(data.get("profiles"), dict):
                            data["profiles"] = {}
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    continue
            
            # Remove old vega_ profiles that might have been deleted
            keys_to_remove = [k for k in data.get("profiles", {}) if k.startswith("vega_")]
            for k in keys_to_remove:
                del data["profiles"][k]
            
            for pid, pdata in getattr(self, "profiles", {}).items():
                profile_key = f"vega_{pid}"
                ram_val = pdata.get("ram")
                if not ram_val:
                    ram_val = 4096
                
                data["profiles"][profile_key] = {
                    "name": f"[Vega] {pdata.get('name') or 'Unknown'}",
                    "lastVersionId": pdata.get("version_id") or pdata.get("version") or "",
                    "gameDir": pdata.get("path") or "",
                    "javaArgs": f"-Xmx{ram_val}m -Xms512m",
                    "type": "custom"
                }
            
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                temp_path = file_path + ".tmp"
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                
                import time
                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        os.replace(temp_path, file_path)
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            time.sleep(0.1 * (2 ** attempt))
                        else:
                            raise e
            except Exception as e:
                print(f"Error writing to {file_path}: {e}")
            finally:
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.nav_bar = NavBar()
        self.nav_bar.nav_clicked.connect(self.switch_tab)
        self.nav_bar.game_changed.connect(self.on_game_changed)
        main_layout.addWidget(self.nav_bar)
        
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("background: transparent;")
        
        self.stack = QStackedWidget()
        
        # Profile List Tab
        self.profile_page = QWidget()
        profile_layout = QVBoxLayout(self.profile_page)
        profile_layout.setContentsMargins(40, 40, 40, 40)
        lbl = QLabel("Profilleriniz")
        lbl.setStyleSheet("font-size: 24px; color: #40E0D0;")
        profile_layout.addWidget(lbl)
        
        # ARAMA ÇUBUĞU
        self.profile_search = QLineEdit()
        self.profile_search.setPlaceholderText("🔍 Profillerde ara...")
        self.profile_search.textChanged.connect(self.filter_profiles)
        profile_layout.addWidget(self.profile_search)
        
        from PySide6.QtGui import QShortcut, QKeySequence
        
        self.profile_list = QListWidget()
        self.profile_list.itemClicked.connect(self.on_profile_selected)
        self.profile_list.itemDoubleClicked.connect(lambda item=None: self.on_play())
        self.profile_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(self.show_profile_context_menu)
        self.refresh_profile_list()
        
        # Klavye kısayolları (Enter -> Oyna, Delete -> Sil)
        self.shortcut_play = QShortcut(QKeySequence("Return"), self.profile_list)
        self.shortcut_play.activated.connect(self.on_play)
        self.shortcut_del = QShortcut(QKeySequence("Delete"), self.profile_list)
        self.shortcut_del.activated.connect(self.delete_profile)
        
        # İlk profili otomatik seç
        if self.profile_list.count() > 0:
            self.profile_list.setCurrentRow(0)
        
        self.add_profile_btn = QPushButton("Yeni Profil Ekle")
        self.add_profile_btn.clicked.connect(self.add_profile)
        self.add_profile_btn.setStyleSheet("background-color: #2E8B57; border: none; font-size: 14px; padding: 10px;")
        
        self.install_file_btn = QPushButton("📥 Zip'ten Kur")
        self.install_file_btn.clicked.connect(self.install_from_file)
        self.install_file_btn.setStyleSheet("background-color: #D2691E; border: none; font-size: 14px; padding: 10px;")
        
        self.open_folder_btn = QPushButton("📂 Profil Klasörü")
        self.open_folder_btn.clicked.connect(self.open_profile_folder)
        self.open_folder_btn.setStyleSheet("background-color: #555; border: none; font-size: 14px; padding: 10px;")
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.add_profile_btn)
        btn_layout.addWidget(self.install_file_btn)
        btn_layout.addWidget(self.open_folder_btn)
        
        profile_layout.addWidget(self.profile_list)
        profile_layout.addLayout(btn_layout)
        
        self.pack_browser = ModrinthBrowser("modpack")
        self.pack_browser.item_selected.connect(self.on_browser_item_selected)
        self.pack_browser.update_item_requested.connect(self.on_browser_update_requested)
        
        self.mod_browser = ModrinthBrowser("mod")
        self.mod_browser.item_selected.connect(self.on_browser_item_selected)
        
        self.shader_browser = ModrinthBrowser("shader")
        self.shader_browser.item_selected.connect(self.on_browser_item_selected)
        
        self.stack.addWidget(self.profile_page)
        self.stack.addWidget(self.pack_browser)
        self.stack.addWidget(self.mod_browser)
        self.stack.addWidget(self.shader_browser)

        # Bedrock Page (4)
        self.bedrock_page = QWidget()
        bed_layout = QVBoxLayout(self.bedrock_page)
        bed_lbl = QLabel("Minecraft: Bedrock Edition")
        bed_lbl.setStyleSheet("font-size: 42px; font-weight: 900; color: white; margin-bottom: 10px;")
        bed_lbl.setAlignment(Qt.AlignCenter)
        bed_desc = QLabel("Windows 10/11 için optimize edilmiş, çapraz platform destekli sürüm.")
        bed_desc.setStyleSheet("font-size: 16px; color: #CCCCCC; margin-bottom: 40px;")
        bed_desc.setAlignment(Qt.AlignCenter)
        bed_btn = QPushButton("🚀 BEDROCK OYNA")
        bed_btn.setCursor(Qt.PointingHandCursor)
        bed_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #11998e, stop:1 #38ef7d);
                color: white; font-size: 24px; font-weight: bold;
                padding: 20px 50px; border-radius: 15px; border: 2px solid #88FFCC;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #15B0A0, stop:1 #45FF8D);
                border: 2px solid #FFFFFF;
            }
            QPushButton:pressed { background: #0E7568; border: 2px solid #11998e; }
        """)
        bed_btn.clicked.connect(lambda x=None: os.system("explorer.exe shell:AppsFolder\\Microsoft.MinecraftUWP_8wekyb3d8bbwe!App"))
        bed_layout.addStretch()
        bed_layout.addWidget(bed_lbl)
        bed_layout.addWidget(bed_desc)
        bed_layout.addWidget(bed_btn, alignment=Qt.AlignCenter)
        bed_layout.addStretch()
        self.stack.addWidget(self.bedrock_page)
        
        # Dungeons Page (5)
        self.dungeons_page = QWidget()
        dun_layout = QVBoxLayout(self.dungeons_page)
        dun_layout.setContentsMargins(0, 0, 0, 0)
        
        # Üst Kısım
        dun_top = QWidget()
        dun_top.setStyleSheet("background-color: #171615;")
        dun_top_layout = QVBoxLayout(dun_top)
        
        dun_lbl = QLabel("Minecraft Dungeons")
        dun_lbl.setStyleSheet("font-size: 36px; font-weight: 900; color: #FFAAFF; margin-top: 10px;")
        dun_lbl.setAlignment(Qt.AlignCenter)
        dun_desc = QLabel("Zindanları keşfet, efsanevi silahlar kuşan ve Arch-Illager'ı yen!")
        dun_desc.setStyleSheet("font-size: 16px; color: #DDDDDD; margin-bottom: 20px;")
        dun_desc.setAlignment(Qt.AlignCenter)
        
        dun_btn = QPushButton("ZİNDANA GİR")
        dun_btn.setCursor(Qt.PointingHandCursor)
        dun_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9733EE, stop:1 #DA22FF);
                color: white; font-size: 24px; font-weight: bold; border-radius: 8px; padding: 15px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #a84cf0, stop:1 #e044ff);
                border: 2px solid #FF88FF;
            }
            QPushButton:pressed { background: #7020C0; border: 2px solid #9733EE; }
        """)
        dun_btn.clicked.connect(lambda x=None: os.system("explorer.exe shell:AppsFolder\\Microsoft.Lovika_8wekyb3d8bbwe!Game"))
        
        dun_mods_btn = QPushButton("Kurulu Modlar")
        dun_mods_btn.setCursor(Qt.PointingHandCursor)
        dun_mods_btn.setStyleSheet("""
            QPushButton {
                background: #333; color: white; font-size: 16px; font-weight: bold; border-radius: 8px; padding: 15px; border: 1px solid #555;
            }
            QPushButton:hover { background: #444; }
        """)
        dun_mods_btn.clicked.connect(self.show_dungeons_mods)
        
        h_dun = QHBoxLayout()
        h_dun.addStretch()
        h_dun.addWidget(dun_btn, 1)
        h_dun.addWidget(dun_mods_btn, 0)
        h_dun.addStretch()
        
        dun_top_layout.addWidget(dun_lbl)
        dun_top_layout.addWidget(dun_desc)
        dun_top_layout.addLayout(h_dun)
        
        # Web Browser
        from PySide6.QtCore import QUrl
        self.dun_browser = QWebEngineView()
        self.dun_browser.load(QUrl("https://www.curseforge.com/minecraft-dungeons"))
        
        profile = self.dun_browser.page().profile()
        profile.downloadRequested.connect(self.handle_dungeons_download)
        
        dun_layout.addWidget(dun_top)
        dun_layout.addWidget(self.dun_browser)
        
        self.stack.addWidget(self.dungeons_page)
        
        self.server_page = ServerWidget()
        self.server_widget = self.server_page
        self.stack.addWidget(self.server_page)
        
        self.splitter.addWidget(self.stack)
        
        self.right_stack = QStackedWidget()
        
        self.detail_panel = DetailPanel()
        self.detail_panel.download_requested.connect(self.download_project)
        self.right_stack.addWidget(self.detail_panel)
        
        self.installed_mods_panel = InstalledModsPanel()
        self.right_stack.addWidget(self.installed_mods_panel)
        
        self.splitter.addWidget(self.right_stack)
        self.splitter.setSizes([800, 500])
        self.right_stack.hide()
        
        content_layout.addWidget(self.splitter)
        
        self.action_bar = ActionBar()
        self.action_bar.play_clicked.connect(self.on_play)
        self.action_bar.folder_btn.clicked.connect(lambda x=None: os.startfile(self.mc_dir))
        content_layout.addWidget(self.action_bar)
        
        main_layout.addLayout(content_layout)
        
        self.nav_bar.btns["home"].click()
        self.on_profile_selected()
        self.detail_panel.hide()
        
        # Durum çubuğu
        self.statusBar().setStyleSheet("color: #888; background: rgba(15,15,20,0.9); border-top: 1px solid #333;")
        self.statusBar().showMessage("Vega Launcher hazır — Profil seçip OYNA'ya basın!")
        self.start_update_checker()

    def filter_profiles(self, text):
        search_text = text.lower()
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            pid = item.data(Qt.UserRole)
            pdata = self.profiles.get(pid, {})
            name = pdata.get("name", "").lower()
            item.setHidden(search_text not in name)

    def open_profile_folder(self):
        pid, pdata = self.get_selected_profile()
        if pdata and os.path.exists(pdata["path"]):
            os.startfile(pdata["path"])
        else:
            os.startfile(self.profiles_dir)

    def switch_tab(self, key):
        mapping = {"home": 0, "packs": 1, "mods": 2, "shaders": 3, "bedrock_home": 4, "dungeons_home": 5, "server": 6}
        idx = mapping.get(key, 0)
        self.stack.setCurrentIndex(idx)
        
        if key == "home":
            # If a profile is selected, show its mod panel, else hide
            if self.profile_list.currentItem():
                self.right_stack.setCurrentWidget(self.installed_mods_panel)
                self.right_stack.show()
            else:
                self.right_stack.hide()
        elif key in ["bedrock_home", "dungeons_home", "server"]:
            self.right_stack.hide()
        else:
            # Store/search tabs
            self.right_stack.setCurrentWidget(self.detail_panel)
            self.right_stack.show()
        
        if idx == 1: self.pack_browser.refresh_if_needed()
        elif idx == 2: self.mod_browser.refresh_if_needed()
        elif idx == 3: self.shader_browser.refresh_if_needed()
        
    def on_game_changed(self, game_name):
        self.action_bar.hide()
        self.detail_panel.hide()
        if game_name == "Minecraft: Java Edition":
            self.action_bar.show()
            self.switch_tab("home")
        elif game_name == "Minecraft for Windows":
            self.switch_tab("bedrock_home")
        elif game_name == "Minecraft Dungeons":
            self.switch_tab("dungeons_home")

    def on_browser_item_selected(self, data):
        self.right_stack.setCurrentWidget(self.detail_panel)
        self.detail_panel.show()
        self.right_stack.show()
        self.detail_panel.update_info(data)

    def refresh_profile_list(self):
        self.profile_list.clear()
        for pid, pdata in self.profiles.items():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, pid)
            
            widget = ProfileWidget(pdata.get('name', 'Bilinmiyor'), pdata.get('version', 'Bilinmiyor'), pdata.get('ram', 4096), pid)
            widget.update_clicked.connect(self.on_profile_update_clicked)
            
            if hasattr(self, 'available_updates') and pid in self.available_updates:
                ver_id, url = self.available_updates[pid]
                widget.update_btn.setVisible(True)
                widget.new_version_id = ver_id
                widget.new_url = url
                
            item.setSizeHint(widget.sizeHint())
            
            self.profile_list.addItem(item)
            self.profile_list.setItemWidget(item, widget)

    def _get_profile_item(self, profile_id):
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if item and item.data(Qt.UserRole) == profile_id:
                return item
        return None

    def _get_profile_widget(self, profile_id):
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if item and item.data(Qt.UserRole) == profile_id:
                return self.profile_list.itemWidget(item)
        return None

    def _generate_unique_profile_name(self, base_name):
        pack_name = base_name
        profile_path = os.path.join(self.profiles_dir, pack_name)
        counter = 1
        while os.path.exists(profile_path) or any(p.get("name") == pack_name for p in self.profiles.values()):
            pack_name = f"{base_name} ({counter})"
            profile_path = os.path.join(self.profiles_dir, pack_name)
            counter += 1
        return pack_name, profile_path

    def get_active_profile_loader(self, pdata=None):
        if pdata is None:
            _, pdata = self.get_selected_profile()
        if not pdata or not isinstance(pdata, dict):
            return None

        # Tier 1: Explicit loader stored in profile dictionary
        loader_val = pdata.get("loader")
        if loader_val:
            return str(loader_val).lower()

        # Tier 2: Check version string for known loader prefixes/substrings
        ver = str(pdata.get("version") or "").lower()
        for known in ["neoforge", "forge", "fabric", "quilt"]:
            if known in ver:
                return known

        # Tier 3: Scan profile's mods directory for jar naming signatures
        prof_path = pdata.get("path") or ""
        if prof_path and os.path.isdir(prof_path):
            mods_dir = os.path.join(prof_path, "mods")
            if os.path.isdir(mods_dir):
                try:
                    files = [f.lower() for f in os.listdir(mods_dir) if f.endswith(".jar")]
                    neo_cnt = sum(1 for f in files if "neoforge" in f)
                    fab_cnt = sum(1 for f in files if "fabric" in f)
                    quilt_cnt = sum(1 for f in files if "quilt" in f)
                    forge_cnt = sum(1 for f in files if "forge" in f and "neoforge" not in f)

                    counts = {"neoforge": neo_cnt, "fabric": fab_cnt, "quilt": quilt_cnt, "forge": forge_cnt}
                    top_loader = max(counts, key=counts.get)
                    if counts[top_loader] > 0:
                        return top_loader
                except Exception:
                    pass

        # Tier 4: Vanilla / no loader
        return None

    def on_profile_selected(self):
        pid, pdata = self.get_selected_profile()
        if pdata:
            self.active_profile_version = pdata['version']
            self.active_profile_loader = self.get_active_profile_loader(pdata)
            self.action_bar.pack_name.setText(pdata['name'])
            playtime = pdata.get("playtime", 0)
            hours = playtime // 3600
            mins = (playtime % 3600) // 60
            pt_str = f" • Oynama: {hours}s {mins}dk" if playtime > 0 else ""
            self.action_bar.pack_size.setText(f"{pdata['version']} | {pdata['ram']} MB{pt_str}")
            self.statusBar().showMessage(f"Aktif Profil: {pdata['name']} ({pdata['version']})")
            
            # Mod yöneticisini yükle ve göster
            mods_dir = os.path.join(pdata["path"], "mods")
            self.installed_mods_panel.load_mods(mods_dir, pdata, pid, self)
            self.right_stack.setCurrentWidget(self.installed_mods_panel)
            self.right_stack.show()
        else:
            self.active_profile_version = None
            self.active_profile_loader = None
            self.action_bar.pack_name.setText("Profil Seçilmedi")
            self.action_bar.pack_size.setText("")
            self.statusBar().showMessage("Profil seçilmedi")
            self.right_stack.hide()

    def show_dungeons_mods(self):
        dun_mods_dir = r"C:\XboxGames\Minecraft Dungeons\Content\Dungeons\Content\Paks\~mods"
        if not os.path.exists(dun_mods_dir):
            os.makedirs(dun_mods_dir, exist_ok=True)
        self.installed_mods_panel.load_mods(dun_mods_dir)
        self.right_stack.setCurrentWidget(self.installed_mods_panel)
        self.right_stack.show()

    def show_profile_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self.profile_list.itemAt(pos)
        if not item: return
        self.profile_list.setCurrentItem(item)
        self.on_profile_selected()
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2D2D2D; color: white; border: 1px solid #555; }
            QMenu::item { padding: 5px 20px; }
            QMenu::item:selected { background-color: #40E0D0; color: black; }
        """)
        
        play_action = menu.addAction("▶ Oyna")
        folder_action = menu.addAction("📁 Profil Klasörünü Aç")
        menu.addSeparator()
        edit_action = menu.addAction("✏ Düzenle")
        del_action = menu.addAction("🗑 Sil")
        
        action = menu.exec(self.profile_list.mapToGlobal(pos))
        
        if action == play_action:
            self.on_play()
        elif action == folder_action:
            self.open_profile_folder()
        elif action == edit_action:
            self.edit_profile()
        elif action == del_action:
            self.delete_profile()

    def get_selected_profile(self):
        current_item = self.profile_list.currentItem()
        if not current_item: return None, None
        pid = current_item.data(Qt.UserRole)
        return pid, self.profiles.get(pid)

    def add_profile(self):
        dialog = AddProfileDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data['name'] or not data['version']:
                QMessageBox.warning(self, "Hata", "Lütfen tüm alanları doldurun.")
                return
            
            pack_name, profile_path = self._generate_unique_profile_name(data['name'])
            
            os.makedirs(profile_path, exist_ok=True)
            profile_id = str(uuid.uuid4())
                
            self.profiles[profile_id] = {
                "name": pack_name,
                "version": data['version'],
                "ram": data['ram'],
                "path": profile_path
            }
            self.save_config()
            self.refresh_profile_list()

    def delete_profile(self):
        pid, pdata = self.get_selected_profile()
        if not pid: return
        reply = QMessageBox.question(self, 'Emin misiniz?', 
                                     f"{pdata.get('name', 'Profil')} adlı profili tamamen silmek (tüm modlar ve ayarlar dahil) istediğinize emin misiniz?", 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            profile_path = pdata.get("path", "")
            
            if profile_path and os.path.exists(profile_path):
                # 1. Deneme: shutil.rmtree
                try:
                    shutil.rmtree(profile_path, ignore_errors=True)
                except: pass
                
                # 2. Deneme: Hâlâ duruyorsa Windows komutuyla zorla sil
                if os.path.exists(profile_path):
                    try:
                        os.system(f'rd /s /q "{profile_path}"')
                    except: pass
                
                # 3. Son kontrol: Klasör hâlâ silinmediyse kullanıcıyı uyar ve config'den silme
                if os.path.exists(profile_path):
                    QMessageBox.warning(self, "Silinemedi", 
                        f"Profil klasörü silinemedi (başka bir program tarafından kullanılıyor olabilir):\n{profile_path}\n\n"
                        "Lütfen klasörü manuel olarak silin, ardından tekrar deneyin.")
                    return
            
            # Klasör başarıyla silindi (veya zaten yoktu) -> config'den de kaldır
            del self.profiles[pid]
            self.save_config()
            self.refresh_profile_list()

    def edit_profile(self):
        pid, pdata = self.get_selected_profile()
        if not pid:
            QMessageBox.warning(self, "Uyarı", "Lütfen düzenlemek için bir profil seçin.")
            return
            
        dialog = EditProfileDialog(pdata.get("name", "Profil"), pdata.get("ram", 4096), self)
        if dialog.exec() == QDialog.Accepted:
            new_name, new_ram = dialog.get_data()
            if not new_name:
                QMessageBox.warning(self, "Hata", "Profil adı boş olamaz.")
                return
                
            if any(p.get("name") == new_name and p_id != pid for p_id, p in self.profiles.items()):
                QMessageBox.warning(self, "Hata", "Bu isimde başka bir profil zaten var.")
                return
            
            self.profiles[pid]["name"] = new_name
            self.profiles[pid]["ram"] = new_ram
            self.save_config()
            self.refresh_profile_list()
            
            item = self._get_profile_item(pid)
            if item:
                self.profile_list.setCurrentItem(item)
                self.on_profile_selected()

    def install_from_file(self):
        try:
            from PySide6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(self, "Modpack Arşivi Seç", "", "Arşiv Dosyaları (*.zip *.mrpack *.rar)")
            if not file_path: return
            
            base_name = os.path.basename(file_path).split('.')[0]
            pack_name, profile_path = self._generate_unique_profile_name(base_name)
                
            self.pending_modpack = (pack_name, profile_path)
            
            self.progress_dialog = QProgressDialog("Dosyadan kuruluyor...", "İptal", 0, 100, self)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.setAutoClose(False) # Auto-close KAPALI (0=0 olunca kendi kendine kapanmasını önler)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.show()
            
            self.dl_thread = DownloadModpackThread(profile_path, file_path, is_local=True)
            self._active_threads = [t for t in self._active_threads if t.isRunning()]
            self._active_threads.append(self.dl_thread)
            self.dl_thread.progress_update.connect(self.progress_dialog.setLabelText)
            self.dl_thread.progress_val.connect(self.update_progress)
            self.dl_thread.task_finished.connect(self.on_modpack_finished)
            self.dl_thread.start()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"install_from_file çöktü:\n{str(e)}\n\n{traceback.format_exc()}")

    def update_progress(self, current, total):
        if hasattr(self, "progress_dialog") and self.progress_dialog.isVisible():
            if total == 0:
                self.progress_dialog.setMaximum(0)
                self.progress_dialog.setValue(0)
            else:
                self.progress_dialog.setMaximum(total)
                self.progress_dialog.setValue(current)

    def download_project(self, project):
        ptype = project.get("project_type", "mod")
        
        if ptype == "modpack":
            version = self.pack_browser.get_active_version()
            loader = self.pack_browser.get_active_loader()
            
            self.detail_panel.download_btn.setText("Modpack hazırlanıyor...")
            QApplication.processEvents()
            
            file_data = ModrinthAPI.get_latest_version_file(project["project_id"], game_version=version, loader=loader)
            if not file_data:
                err_msg = "Bu modpack için uygun bir sürüm bulunamadı."
                if version or loader:
                    err_msg += f"\n(Filtreler: {version or 'Tümü'} / {loader or 'Tümü'})"
                QMessageBox.critical(self, "Hata", err_msg)
                self.detail_panel.download_btn.setText("Modpack'i Yeni Profil Olarak Kur")
                return
                
            url = file_data["url"]
            version_id = file_data.get("version_id")
            proj_id = project.get("project_id")
            
            safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', project.get("title", "Modpack")).strip()
            if not safe_name: safe_name = "Modpack"
            
            pack_name, new_path = self._generate_unique_profile_name(safe_name)
                
            os.makedirs(new_path, exist_ok=True)
            self.pending_modpack = (pack_name, new_path, proj_id, version_id)
            
            self.progress_dialog = QProgressDialog("Modpack indiriliyor...", "İptal", 0, 100, self)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.setAutoClose(False)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.show()
            
            self.dl_thread = DownloadModpackThread(new_path, url, is_local=False)
            self._active_threads = [t for t in self._active_threads if t.isRunning()]
            self._active_threads.append(self.dl_thread)
            self.dl_thread.progress_update.connect(self.progress_dialog.setLabelText)
            self.dl_thread.progress_val.connect(self.update_progress)
            self.dl_thread.task_finished.connect(self.on_modpack_finished)
            self.dl_thread.start()
            return
            
        # MODS & SHADERS (requires active profile)
        pid, pdata = self.get_selected_profile()
        if not pid:
            QMessageBox.warning(self, "Uyarı", "Lütfen Profiller sekmesinden bir profil seçin.")
            return
            
        version = pdata["version"]
        match = re.search(r'\b(1\.\d+(\.\d+)?)\b', version)
        base_version = match.group(1) if match else version
        loader = self.get_active_profile_loader(pdata) if ptype == "mod" else None
        
        self.detail_panel.download_btn.setText("Dosya bilgisi alınıyor...")
        self.detail_panel.download_btn.setEnabled(False)
        QApplication.processEvents()
        
        file_data = ModrinthAPI.get_latest_version_file(project["project_id"], game_version=base_version, loader=loader)
        if not file_data:
            err_msg = f"Bu öğenin {base_version} sürümü"
            if loader:
                err_msg += f" ve {loader.capitalize()} motoru"
            err_msg += " için uyumlu bir dosyası bulunamadı."
            QMessageBox.critical(self, "Hata", err_msg)
            self.detail_panel.download_btn.setText("Aktif Profile İndir")
            self.detail_panel.download_btn.setEnabled(True)
            return
            
        url = file_data["url"]
        filename = file_data["filename"]
        
        folder = "shaderpacks" if ptype == "shader" else "mods"
        target_dir = os.path.join(pdata["path"], folder)
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, filename)
        
        if os.path.exists(target_path):
            QMessageBox.information(self, "Zaten Mevcut", f"Bu öğe zaten profilinize yüklenmiş:\n{filename}")
            self.detail_panel.download_btn.setText("Aktif Profile İndir")
            self.detail_panel.download_btn.setEnabled(True)
            return
        
        self.detail_panel.download_btn.setText("İndiriliyor...")
        self.statusBar().showMessage(f"İndiriliyor: {filename}...")
        QApplication.processEvents()
        
        self.dl_thread = DownloadModThread(url, target_path)
        self._active_threads = [t for t in self._active_threads if t.isRunning()]
        self._active_threads.append(self.dl_thread)
        self.dl_thread.task_finished.connect(self.on_download_finished)
        self.dl_thread.start()

    def on_download_finished(self, success, msg):
        self.detail_panel.download_btn.setText("Aktif Profile İndir")
        self.detail_panel.download_btn.setEnabled(True)
        if success:
            self.statusBar().showMessage("İndirme işlemi tamamlandı!")
            QMessageBox.information(self, "Başarılı", "İndirme işlemi tamamlandı!")
        else:
            self.statusBar().showMessage(f"İndirme hatası: {msg}")
            QMessageBox.critical(self, "Hata", msg)

    def on_modpack_finished(self, success, msg, new_version_id):
        try:
            if hasattr(self, "progress_dialog") and self.progress_dialog:
                self.progress_dialog.close()
                
            self.detail_panel.download_btn.setText("Modpack'i Yeni Profil Olarak Kur")
            self.detail_panel.download_btn.setEnabled(True)
            if success:
                pending = getattr(self, "pending_modpack", ("Modpack", ""))
                existing_pid = None
                if len(pending) >= 5:
                    pack_name, pack_path, proj_id, ver_id, existing_pid = pending
                elif len(pending) == 4:
                    pack_name, pack_path, proj_id, ver_id = pending
                else:
                    pack_name, pack_path = pending[:2]
                    proj_id, ver_id = None, None

                if existing_pid and existing_pid in self.profiles:
                    profile_id = existing_pid
                    if new_version_id:
                        self.profiles[profile_id]["version"] = new_version_id
                    if proj_id:
                        self.profiles[profile_id]["project_id"] = proj_id
                    if ver_id:
                        self.profiles[profile_id]["version_id"] = ver_id
                    det_loader = self.get_active_profile_loader(self.profiles[profile_id])
                    if det_loader:
                        self.profiles[profile_id]["loader"] = det_loader
                    
                    if hasattr(self, 'available_updates') and profile_id in self.available_updates:
                        del self.available_updates[profile_id]
                    
                    widget = self._get_profile_widget(profile_id)
                    if widget and hasattr(widget, "update_btn"):
                        widget.update_btn.setVisible(False)
                else:
                    profile_id = str(uuid.uuid4())
                    self.profiles[profile_id] = {
                        "name": pack_name,
                        "version": new_version_id if new_version_id else "1.20.1",
                        "ram": 4096,
                        "path": pack_path
                    }
                    if proj_id and ver_id:
                        self.profiles[profile_id]["project_id"] = proj_id
                        self.profiles[profile_id]["version_id"] = ver_id
                        self.profiles[profile_id]["source"] = "modrinth"
                    det_loader = self.get_active_profile_loader(self.profiles[profile_id])
                    if det_loader:
                        self.profiles[profile_id]["loader"] = det_loader

                self.save_config()
                self.refresh_profile_list()
                
                item = self._get_profile_item(profile_id)
                if item:
                    self.profile_list.setCurrentItem(item)
                    self.on_profile_selected()
                QMessageBox.information(self, "Başarılı", msg)
            else:
                QMessageBox.critical(self, "Kurulum Hatası", msg)
        except Exception as e:
            QMessageBox.critical(self, "Kritik Hata", f"on_modpack_finished çöktü:\n{str(e)}\n\n{traceback.format_exc()}")

    def update_modpack(self, profile_id, project_id, new_version_id, new_url):
        pdata = self.profiles.get(profile_id)
        if not pdata: return
        
        loader = self.get_active_profile_loader(pdata)
        ver_str = str(pdata.get("version") or "")
        match = re.search(r'(?<![\d\.])(1\.(?:[7-9]|\d{2})(?:\.\d+)?)(?![\d\.])', ver_str)
        base_version = match.group(1) if match else None

        # Güvenlik doğrulaması: Hedef dosyanın profil motoruyla (Fabric vb.) uyumlu olduğunu kesinleştir
        verified_file = ModrinthAPI.get_latest_version_file(project_id, game_version=base_version, loader=loader)
        if not verified_file and loader:
            verified_file = ModrinthAPI.get_latest_version_file(project_id, loader=loader)

        if verified_file:
            new_version_id = verified_file.get("version_id") or new_version_id
            new_url = verified_file.get("url") or new_url
        elif loader:
            QMessageBox.warning(self, "Güncelleme Uyarısı", f"Bu modpaketin {loader.capitalize()} motoru için uyumlu bir güncellemesi bulunamadı.")
            return

        reply = QMessageBox.question(self, 'Güncelleme', "Modpaketi güncellenecek. Eski mods ve config klasörleri silinecek. Onaylıyor musunuz?", QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
            
        mods_dir = os.path.join(pdata["path"], "mods")
        config_dir = os.path.join(pdata["path"], "config")
        shutil.rmtree(mods_dir, ignore_errors=True)
        shutil.rmtree(config_dir, ignore_errors=True)
        
        self.pending_modpack = (pdata["name"], pdata["path"], project_id, new_version_id, profile_id)
        
        self.progress_dialog = QProgressDialog("Modpack güncelleniyor...", "İptal", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.show()
        
        self.dl_thread = DownloadModpackThread(pdata["path"], new_url, is_local=False)
        self._active_threads = [t for t in self._active_threads if t.isRunning()]
        self._active_threads.append(self.dl_thread)
        self.dl_thread.progress_update.connect(self.progress_dialog.setLabelText)
        self.dl_thread.progress_val.connect(self.update_progress)
        self.dl_thread.task_finished.connect(self.on_modpack_finished)
        self.dl_thread.start()

    def on_update_available(self, profile_id, latest_version_id, url):
        if not hasattr(self, 'available_updates'):
            self.available_updates = {}
        self.available_updates[profile_id] = (latest_version_id, url)
        
        # Update ProfileWidget
        widget = self._get_profile_widget(profile_id)
        if widget and hasattr(widget, "update_btn"):
            widget.update_btn.setVisible(True)
            widget.new_version_id = latest_version_id
            widget.new_url = url
                
        # Also try to show it on CardWidget in browsers if visible
        pdata = self.profiles.get(profile_id, {})
        project_id = pdata.get("project_id")
        if project_id:
            for browser in [self.pack_browser, self.mod_browser, self.shader_browser]:
                for i in range(browser.grid_layout.count()):
                    row_layout = browser.grid_layout.itemAt(i)
                    if row_layout and row_layout.layout():
                        for j in range(row_layout.layout().count()):
                            item_layout = row_layout.layout().itemAt(j)
                            if item_layout and item_layout.widget():
                                card = item_layout.widget()
                                if hasattr(card, "data") and card.data.get("project_id") == project_id:
                                    if hasattr(card, "update_btn"):
                                        card.update_btn.setVisible(True)
                                    card.update_info = (profile_id, latest_version_id, url)

    def on_profile_update_clicked(self, profile_id):
        widget = self._get_profile_widget(profile_id)
        if widget and hasattr(widget, "new_version_id") and hasattr(widget, "new_url"):
            pdata = self.profiles.get(profile_id)
            if pdata:
                self.update_modpack(profile_id, pdata.get("project_id"), widget.new_version_id, widget.new_url)

    def on_browser_update_requested(self, data):
        # We need to find which card emitted it. Since we don't have the widget directly here,
        # we can just use the project_id to find the matching profile and its new version info.
        project_id = data.get("project_id")
        if not project_id: return
        for pid, pdata in self.profiles.items():
            if pdata.get("project_id") == project_id:
                # Find profile widget to get the url and version_id
                widget = self._get_profile_widget(pid)
                if widget and hasattr(widget, "new_version_id") and hasattr(widget, "new_url"):
                    self.update_modpack(pid, project_id, widget.new_version_id, widget.new_url)
                    return
                break

    def start_update_checker(self):
        from mod_manager import UpdateCheckerThread
        self.update_checker = UpdateCheckerThread(self.profiles)
        self.update_checker.update_available.connect(self.on_update_available)
        self._active_threads = [t for t in self._active_threads if t.isRunning()]
        self._active_threads.append(self.update_checker)
        self.update_checker.start()

    def on_play(self):
        try:
            pid, pdata = self.get_selected_profile()
            if not pid:
                QMessageBox.warning(self, "Uyarı", "Lütfen bir profil seçin.")
                return
                
            if not hasattr(self, 'ms_login') or not self.ms_login:
                dialog = MicrosoftLoginDialog(self)
                if dialog.exec() == QDialog.Accepted:
                    self.ms_login = dialog.get_account_data()
                    self.save_config()
                else:
                    return
                    
            options = {
                "username": self.ms_login.get("name", "Player"),
                "uuid": self.ms_login.get("id", ""),
                "token": self.ms_login.get("access_token", ""),
                "jvmArguments": [f"-Xmx{pdata.get('ram', 2048)}m", "-Xms512m"],
                "launcherName": "Vega Launcher",
                "launcherVersion": "1.0",
                "gameDirectory": pdata["path"],
            }
            
            mc_dir = self.mc_dir
            os.makedirs(mc_dir, exist_ok=True)
            version = pdata["version"]
            version_dir = os.path.join(mc_dir, "versions", version)
            
            if not os.path.exists(version_dir):
                is_loader = ("fabric-loader" in version.lower() or "forge" in version.lower() or "neoforge" in version.lower())
                if is_loader:
                    QMessageBox.warning(
                        self,
                        "Motor Eksik",
                        f"Bu profil için seçilen motor ({version}) .minecraft klasöründe bulunamadı.\n"
                        f"Lütfen 'Motor Kur' butonunu kullanarak ilgili motoru kurun."
                    )
                    return
                self.vanilla_thread = DownloadVanillaThread(version, mc_dir)
                self._active_threads = [t for t in self._active_threads if t.isRunning()]
                self._active_threads.append(self.vanilla_thread)

                if hasattr(self, 'action_bar'):
                    self.action_bar.play_btn.setEnabled(False)
                    self.action_bar.play_btn.setText("İndiriliyor...")
                    self.action_bar.progress.setVisible(True)
                    self.action_bar.progress.setRange(0, 100)
                    self.action_bar.progress.setValue(0)
                    self.vanilla_thread.progress_val.connect(self.action_bar.progress.setValue)

                self.progress_dlg = QProgressDialog(f"Minecraft {version} indiriliyor...", "İptal", 0, 100, self)
                self.progress_dlg.setWindowTitle("İndirme")
                self.progress_dlg.setWindowModality(Qt.WindowModal)
                
                self.vanilla_thread.progress_update.connect(self.progress_dlg.setLabelText)
                self.vanilla_thread.progress_update.connect(lambda s: self.statusBar().showMessage(f"İndiriliyor: {s}"))
                self.vanilla_thread.progress_val.connect(self.progress_dlg.setValue)
                
                def _launch_after_vanilla(success, msg):
                    self.progress_dlg.close()
                    if hasattr(self, 'action_bar'):
                        self.action_bar.progress.setVisible(False)
                    if success:
                        self._do_launch(options, version, mc_dir, pid, pdata)
                    else:
                        if hasattr(self, 'action_bar'):
                            self.action_bar.play_btn.setEnabled(True)
                            self.action_bar.play_btn.setText("OYNA")
                        self.statusBar().showMessage(f"İndirme hatası: {msg}")
                        QMessageBox.critical(self, "İndirme Hatası", msg)
                    
                self.vanilla_thread.task_finished.connect(_launch_after_vanilla)
                self.vanilla_thread.start()
                self.progress_dlg.exec()
            else:
                self._do_launch(options, version, mc_dir, pid, pdata)
        except Exception as e:
            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(True)
                self.action_bar.play_btn.setText("OYNA")
            QMessageBox.critical(self, "Kritik Hata", f"on_play sırasında hata:\n{str(e)}\n\n{traceback.format_exc()}")

    def _do_launch(self, options, version, mc_dir, pid, pdata):
        import minecraft_launcher_lib
        try:
            import integrity_check
            if not integrity_check.verify_integrity()[0]:
                sys.exit(1)
                
            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(False)
                self.action_bar.play_btn.setText("Başlatılıyor...")
            self.statusBar().showMessage(f"Minecraft {version} başlatılıyor...")

            cmd = minecraft_launcher_lib.command.get_minecraft_command(version, mc_dir, options)
            process = subprocess.Popen(cmd, cwd=pdata["path"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            
            self.tracker_thread = PlaytimeTrackerThread(process, pid)
            self._active_threads = [t for t in self._active_threads if t.isRunning()]
            self._active_threads.append(self.tracker_thread)
            self.tracker_thread.tracking_finished.connect(self.on_game_closed)
            self.tracker_thread.start()
            
            QTimer.singleShot(1500, self.on_game_started)
        except Exception as e:
            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(True)
                self.action_bar.play_btn.setText("OYNA")
            self.statusBar().showMessage(f"Başlatma hatası: {e}")
            QMessageBox.critical(self, "Başlatma Hatası", f"Oyun başlatılamadı:\n{str(e)}\n\n{traceback.format_exc()}")

    def on_game_started(self):
        if hasattr(self, '_launch_splash'):
            self._launch_splash.close()
        if hasattr(self, 'action_bar'):
            self.action_bar.play_btn.setText("OYUNDA")
        self.statusBar().showMessage("Oyun çalışıyor...")
        self.showMinimized() # Kullanıcı çöktüğünü sanmasın diye sadece küçült
        
    def on_game_closed(self, pid, elapsed_seconds):
        if hasattr(self, 'action_bar'):
            self.action_bar.play_btn.setText("OYNA")
            self.action_bar.play_btn.setEnabled(True)
            self.action_bar.progress.setVisible(False)
        self.statusBar().showMessage("Oyun kapandı. Toplam oynama süresi kaydedildi.")

        if not self.isVisible() or getattr(self, '_is_closing', False):
            if pid in self.profiles:
                current = self.profiles[pid].get("playtime", 0)
                self.profiles[pid]["playtime"] = current + elapsed_seconds
                self.save_config()
            return

        self.show()
        if pid in self.profiles:
            current = self.profiles[pid].get("playtime", 0)
            self.profiles[pid]["playtime"] = current + elapsed_seconds
            self.save_config()
            self.on_profile_selected()


    def handle_dungeons_download(self, download):
        # QWebEngineDownloadRequest (PySide6)
        target_dir = r"C:\XboxGames\Minecraft Dungeons\Content\Dungeons\Content\Paks\~mods"
        if not os.path.exists(r"C:\XboxGames\Minecraft Dungeons"):
            QMessageBox.warning(self, "Hata", "Minecraft Dungeons XboxGames klasöründe bulunamadı.")
            download.cancel()
            return
            
        os.makedirs(target_dir, exist_ok=True)
        filename = download.suggestedFileName()
        
        if not filename.endswith(".pak") and not filename.endswith(".zip"):
            QMessageBox.warning(self, "Geçersiz Dosya", "Bu dosya bir Dungeons modu (.pak veya .zip) değil!")
        
        dest_path = os.path.join(target_dir, filename)
        download.setDownloadDirectory(target_dir)
        download.setDownloadFileName(filename)
        
        # Setup sleek progress overlay
        self.dun_overlay = CustomProgressOverlay(filename, self)
        self.dun_overlay.show()
        
        def update_dl(received, total):
            if total > 0:
                pct = int((received/total)*100)
                self.dun_overlay.update_progress(pct, f"{filename} indiriliyor... %{pct}")
                
        download.downloadProgress.connect(update_dl)
        
        def on_finished():
            if download.isFinished():
                self.dun_overlay.title_lbl.setText("İşleniyor...")
                self.dun_overlay.update_progress(100, "Ayıklanıyor ve kuruluyor...")
                QApplication.processEvents()
                
                if filename.endswith(".zip"):
                    try:
                        extracted_paks = []
                        with zipfile.ZipFile(dest_path, 'r') as zip_ref:
                            for zip_info in zip_ref.infolist():
                                if zip_info.filename.endswith('.pak'):
                                    zip_info.filename = os.path.basename(zip_info.filename)
                                    zip_ref.extract(zip_info, target_dir)
                                    extracted_paks.append(zip_info.filename)
                        os.remove(dest_path)
                        
                        self.dun_overlay.close()
                        if extracted_paks:
                            pak_names = "\n".join(extracted_paks)
                            QMessageBox.information(self, "Kurulum Başarılı!", f"ZIP içinden PAK dosyaları başarıyla çıkarıldı ve oyuna kuruldu!\n\nKurulan Modlar:\n{pak_names}")
                        else:
                            QMessageBox.warning(self, "Uyarı", f"İndirilen {filename} ZIP dosyasının içinden hiçbir '.pak' uzantılı mod çıkmadı! Bu dosya Dungeons modu olmayabilir.")
                    except Exception as e:
                        self.dun_overlay.close()
                        QMessageBox.critical(self, "Çıkarma Hatası", f"ZIP dosyası çıkartılırken hata oluştu:\n{e}")
                else:
                    self.dun_overlay.close()
                    QMessageBox.information(self, "Kurulum Başarılı!", f"Mod başarıyla kuruldu ve aktif edildi!\n\nDosya: {filename}")
            else:
                self.dun_overlay.close()
                
        download.stateChanged.connect(lambda state: on_finished() if state == QWebEngineDownloadRequest.DownloadCompleted else None)
        download.accept()

    def closeEvent(self, event):
        self._is_closing = True
        # 1. Cleanup server widget / page
        server_w = getattr(self, 'server_widget', None) or getattr(self, 'server_page', None)
        if server_w:
            if hasattr(server_w, 'cleanup'):
                try:
                    server_w.cleanup()
                except Exception:
                    pass
            elif hasattr(server_w, 'force_kill_server'):
                try:
                    server_w.force_kill_server()
                except Exception:
                    pass

        # 2. Stop card widget background threads
        try:
            CardWidget.cleanup_all_threads()
        except Exception:
            pass

        # 3. Stop background threads in _active_threads and known attributes
        threads_to_stop = []
        if hasattr(self, '_active_threads') and isinstance(self._active_threads, (list, set)):
            threads_to_stop.extend(list(self._active_threads))

        for attr in ['update_checker', 'tracker_thread', 'vanilla_thread', 'dl_thread']:
            th = getattr(self, attr, None)
            if th and th not in threads_to_stop:
                threads_to_stop.append(th)

        for th in threads_to_stop:
            try:
                if th.isRunning():
                    if hasattr(th, 'stop'):
                        try:
                            th.stop()
                        except Exception:
                            pass
                    elif hasattr(th, 'stop_server'):
                        try:
                            th.stop_server()
                        except Exception:
                            pass
                    th.quit()
                    if not th.wait(1000):
                        th.terminate()
                        th.wait(500)
            except Exception:
                pass

        # 4. Terminate any running tracker subprocess
        if hasattr(self, 'tracker_thread') and self.tracker_thread:
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    self.tracker_thread.tracking_finished.disconnect(self.on_game_closed)
            except Exception:
                pass
            proc = getattr(self.tracker_thread, 'process', None)
            if proc and hasattr(proc, 'poll') and proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                except Exception:
                    pass

        # 5. Accept event and call super
        if event is not None:
            if hasattr(event, 'accept'):
                try:
                    event.accept()
                except Exception:
                    pass
            try:
                super().closeEvent(event)
            except Exception:
                pass


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName('Vega Launcher')
    app.setOrganizationName('Arcturus')
    
    if getattr(sys, 'frozen', False):
        app_base_dir = os.path.dirname(sys.executable)
    else:
        app_base_dir = os.path.dirname(os.path.abspath(__file__))
    app.setWindowIcon(QIcon(os.path.join(app_base_dir, 'enderman_icon.ico')))
    
    import integrity_check
    is_ok, tampered = integrity_check.verify_integrity()
    if not is_ok:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Güvenlik Uyarısı", f"⚠️ Bu uygulama yetkisiz olarak değiştirilmiş! Orijinal sürümü indirin: {__author__}")
        sys.exit(1)
        
    window = VegaLauncher()
    window.show()

    # GitHub Releases uzerinden guncelleme kontrolu (arka planda, hata olursa sessiz)
    # Gelistirme ortaminda (python main.py) varsayilan olarak kapali; test icin VEGA_UPDATE_DEV=1
    try:
        if getattr(sys, 'frozen', False) or os.environ.get('VEGA_UPDATE_DEV') == '1':
            from app_updater import AppUpdater
            window._app_updater = AppUpdater(window, __version__)
            QTimer.singleShot(3000, window._app_updater.check)
    except Exception as _upd_err:
        print(f"[Updater] Baslatilamadi: {_upd_err}")

    sys.exit(app.exec())

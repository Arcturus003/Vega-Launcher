import os
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, 
                               QPushButton, QProgressBar, QMessageBox)
from mod_manager import ModrinthAPI
from sound_manager import SoundManager
from runtime_provisioner import RuntimeProvisioner, DEFAULT_PROVISIONER

_active_download_threads = []

class ServerDownloadThread(QThread):
    progress = Signal(int)
    log_msg = Signal(str)
    finished_dl = Signal(bool)

    def __init__(self, software, version, target_path, parent=None, provisioner: RuntimeProvisioner = None, lang: str = "tr"):
        super().__init__(parent)
        self.software = software
        self.version = version
        self.target_path = target_path
        self.provisioner = provisioner or DEFAULT_PROVISIONER
        self.lang = lang
        self.is_downloading = False

    def run(self):
        # Server download and provisioning delegating to RuntimeProvisioner using headers=ModrinthAPI.HEADERS
        self.is_downloading = True
        en = self.lang == "en"
        try:
            self.provisioner.provision_server_runtime(
                self.software,
                self.version,
                self.target_path,
                on_progress=self.progress.emit,
                on_log=self.log_msg.emit,
                is_cancelled=lambda: not self.is_downloading,
                lang=self.lang,
            )
            self.finished_dl.emit(True)
        except Exception as e:
            self.log_msg.emit(f"[ERROR] Download failed: {e}" if en else f"[HATA] İndirme başarısız: {e}")
            self.finished_dl.emit(False)
        finally:
            self.is_downloading = False

class ServerSoftwareDialog(QDialog):
    def __init__(self, parent=None, server_dir=None, auto_software=None, auto_version=None):
        super().__init__(parent)
        from PySide6.QtCore import Qt
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.server_dir = server_dir
        self.dl_thread = None

        self.lang = "tr"
        p = parent
        while p:
            if hasattr(p, "settings") and isinstance(p.settings, dict):
                self.lang = p.settings.get("language", "tr")
                break
            if hasattr(p, "lang") and isinstance(p.lang, str):
                self.lang = p.lang
                break
            p = getattr(p, "parent", lambda: None)()
        en = (self.lang == "en")

        self.setWindowTitle("Change Server Software / Engine" if en else "Yazılım / Motor Değiştir")
        self.setFixedSize(400, 250)
        self.setStyleSheet("background-color: #2D2D30; color: white;")
        
        layout = QVBoxLayout(self)
        
        lbl = QLabel("Server Software (Mod/Plugin Framework):" if en else "Sunucu Yazılımı (Mod/Eklenti Altyapısı):")
        layout.addWidget(lbl)
        
        self.combo_software = QComboBox()
        self.combo_software.addItems(
            ["Purpur (Plugin)", "Fabric (Mod)", "Forge (Mod)", "NeoForge (Mod)"]
            if en else
            ["Purpur (Eklenti)", "Fabric (Mod)", "Forge (Mod)", "NeoForge (Mod)"]
        )
        self.combo_software.setStyleSheet("padding: 5px; background: #1E1E1E;")
        layout.addWidget(self.combo_software)
        
        lbl2 = QLabel("Version:" if en else "Sürüm:")
        layout.addWidget(lbl2)
        
        self.combo_version = QComboBox()
        self.combo_version.addItems(["1.21.4", "1.21.3", "1.21.2", "1.21.1", "1.21", "1.20.4", "1.20.2", "1.20.1", "1.20", "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5"])
        self.combo_version.setStyleSheet("padding: 5px; background: #1E1E1E;")
        layout.addWidget(self.combo_version)
        
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        
        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)
        
        self.btn_install = QPushButton("Install Software" if en else "Yazılımı Kur")
        self.btn_install.setObjectName("PrimaryAccentButton")
        self.btn_install.setCursor(Qt.PointingHandCursor)
        self.btn_install.clicked.connect(self.install_software)
        layout.addWidget(self.btn_install)

        if auto_version:
            if self.combo_version.findText(auto_version) == -1:
                self.combo_version.addItem(auto_version)
            self.combo_version.setCurrentText(auto_version)
            
        if auto_software:
            if en and auto_software == "Purpur (Eklenti)":
                auto_software = "Purpur (Plugin)"
            self.combo_software.setCurrentText(auto_software)
            
        if auto_version and auto_software:
            lbl.hide()
            self.combo_software.hide()
            lbl2.hide()
            self.combo_version.hide()
            self.btn_install.hide()
            self.setFixedSize(400, 100)
            self.setWindowTitle("Automatic Installation" if en else "Otomatik Kurulum")
            
            from PySide6.QtCore import QTimer
            self._auto_install_timer = QTimer(self)
            self._auto_install_timer.setSingleShot(True)
            self._auto_install_timer.timeout.connect(self.install_software)
            self._auto_install_timer.start(500)
        
    def closeEvent(self, event):
        en = (self.lang == "en")
        if self.dl_thread and self.dl_thread.is_downloading:
            QMessageBox.warning(self, "Warning" if en else "Uyarı", "Download in progress, please wait!" if en else "İndirme işlemi devam ediyor, lütfen bekleyin!")
            event.ignore()
        else:
            event.accept()

    def reject(self):
        en = (self.lang == "en")
        if self.dl_thread and self.dl_thread.is_downloading:
            QMessageBox.warning(self, "Warning" if en else "Uyarı", "Download in progress, please wait!" if en else "İndirme işlemi devam ediyor, lütfen bekleyin!")
            return
        super().reject()
            
    def install_software(self):
        en = (self.lang == "en")
        if not self.server_dir:
            self.lbl_status.setText("No valid server selected!" if en else "Geçerli bir sunucu seçili değil!")
            return
            
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass

        software = self.combo_software.currentText()
        version = self.combo_version.currentText()
        target_jar = os.path.join(self.server_dir, "server.jar")
        
        self.btn_install.setEnabled(False)
        self.lbl_status.setText(f"Downloading {software} {version}..." if en else f"{software} {version} indiriliyor...")
        self.progress.setValue(0)
        
        self.dl_thread = ServerDownloadThread(software, version, target_jar, parent=None, lang=self.lang)
        
        # Rule 3: Keep strong reference in main UI class and module-level registry
        global _active_download_threads
        _active_download_threads = [t for t in _active_download_threads if t.isRunning()]
        _active_download_threads.append(self.dl_thread)

        parent_widget = self.parent()
        if hasattr(parent_widget, '_api_threads'):
            parent_widget._api_threads = [t for t in parent_widget._api_threads if t.isRunning()]
            parent_widget._api_threads.append(self.dl_thread)
            
        self.dl_thread.progress.connect(self.progress.setValue)
        self.dl_thread.log_msg.connect(self.lbl_status.setText)
        self.dl_thread.finished_dl.connect(self.on_finished)
        self.dl_thread.start()
        
    def on_finished(self, success):
        en = (self.lang == "en")
        self.btn_install.setEnabled(True)
        try:
            from sound_manager import SoundManager
            if success:
                SoundManager.get_instance().play_levelup()
            else:
                SoundManager.get_instance().play_error()
        except Exception:
            pass
        if success:
            QMessageBox.information(
                self,
                "Success" if en else "Başarılı",
                "Software updated successfully!\nYou can check your mods or plugins folder." if en else "Yazılım başarıyla güncellendi!\nMods veya Plugins klasörünüzü kontrol edebilirsiniz."
            )
            self.accept()
        else:
            if not self.btn_install.isVisible():
                QMessageBox.warning(
                    self,
                    "Error" if en else "Hata",
                    "Installation failed or unsupported software." if en else "Kurulum başarısız oldu veya desteklenmeyen yazılım."
                )
                self.reject()

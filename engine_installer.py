import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QComboBox, QProgressBar, QMessageBox)
from PySide6.QtCore import QThread, Signal
from runtime_provisioner import RuntimeProvisioner, RuntimeSpec, DEFAULT_PROVISIONER

class EngineInstallThread(QThread):
    progress_update = Signal(int, int, str)
    finished_install = Signal(bool, str) # success, version_id_or_error

    def __init__(self, engine_type, mc_version, mc_dir, provisioner: RuntimeProvisioner = None, lang: str = "tr"):
        super().__init__()
        self.engine_type = engine_type
        self.mc_version = mc_version
        self.mc_dir = mc_dir
        self.provisioner = provisioner or DEFAULT_PROVISIONER
        self.lang = lang
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            def on_progress(cur, tot, text):
                self.progress_update.emit(cur, tot, text)

            spec = RuntimeSpec(mc_version=self.mc_version, loader=self.engine_type.lower())
            installed_ver = self.provisioner.install_client_runtime(
                spec,
                mc_dir=self.mc_dir,
                on_progress=on_progress,
                is_cancelled=lambda: self._is_cancelled,
                lang=self.lang,
            )
            self.finished_install.emit(True, installed_ver)
        except Exception as e:
            self.finished_install.emit(False, str(e))

class EngineInstallDialog(QDialog):
    def __init__(self, profile_data, profile_id, main_window, parent=None, lang=None):
        super().__init__(parent)
        self.profile_data = profile_data
        self.profile_id = profile_id
        self.main_window = main_window # To update config and UI
        if lang is None:
            if main_window and hasattr(main_window, "settings") and isinstance(main_window.settings, dict):
                lang = main_window.settings.get("language", "tr")
            elif parent and hasattr(parent, "lang"):
                lang = parent.lang
            else:
                lang = "tr"
        self.lang = lang
        en = self.lang == "en"
        
        # Orijinal sürüm adını al (örn: 1.20.1, fabric-loader-0.14.22-1.20.1 vb.)
        self.current_version = profile_data.get("version", "")
        # Saf minecraft sürümünü ayıkla (eğer zaten fabric/forge ise baz versiyonu bulur)
        self.base_mc_version = self.extract_base_version(self.current_version)
        
        self.setWindowTitle(f"Engine Installer - {profile_data.get('name')}" if en else f"Motor Kurucu - {profile_data.get('name')}")
        self.setFixedSize(450, 250)
        
        theme_key = "electric_amethyst"
        if main_window and hasattr(main_window, "settings") and isinstance(main_window.settings, dict):
            theme_key = main_window.settings.get("theme", "electric_amethyst")
        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            r, g, b = t["rgb"]
            glow = t["glow"]
            primary = t["primary"]
            prim_light = t["primary_light"]
            grad_start = t["gradient_start"]
            sec = t.get("secondary", "#06B6D4")
        except Exception:
            glow = "#C084FC"
            primary = "#8B5CF6"
            prim_light = "#A855F7"
            grad_start = "#7C3AED"
            sec = "#06B6D4"
            r, g, b = (139, 92, 246)

        self.setStyleSheet(f"QDialog {{ background-color: #12121A; border: 1px solid rgba({r}, {g}, {b}, 0.45); border-radius: 12px; }}")
        
        layout = QVBoxLayout(self)
        
        info_lbl = QLabel(f"Game Version: {self.base_mc_version}" if en else f"Oyun Sürümü: {self.base_mc_version}")
        info_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {glow};")
        layout.addWidget(info_lbl)
        
        desc = QLabel(
            "Select the mod loader (engine) to install for this profile.\nLoaders allow you to run external mods (.jar)."
            if en else
            "Bu profile kurulacak motoru (Loader) seçin.\nMotorlar harici modları (.jar) çalıştırmanızı sağlar."
        )
        desc.setStyleSheet("color: #CCC;")
        layout.addWidget(desc)
        
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(["Fabric", "Forge", "NeoForge"])
        self.engine_combo.setStyleSheet(f"padding: 8px; font-size: 14px; background: #1A1A26; color: white; border: 1px solid rgba({r}, {g}, {b}, 0.35); border-radius: 6px;")
        layout.addWidget(self.engine_combo)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(f"QProgressBar {{ border: 1px solid rgba({r}, {g}, {b}, 0.35); border-radius: 5px; text-align: center; background: #111; }} QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {grad_start}, stop:0.7 {prim_light}, stop:1 {sec}); border-radius: 3px; }}")
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #888;")
        layout.addWidget(self.status_lbl)
        
        btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("Install" if en else "Kur")
        self.install_btn.setObjectName("PrimaryAccentButton")
        from PySide6.QtCore import Qt
        self.install_btn.setCursor(Qt.PointingHandCursor)
        self.install_btn.clicked.connect(self.start_install)
        btn_layout.addWidget(self.install_btn)
        
        self.cancel_btn = QPushButton("Cancel" if en else "İptal")
        self.cancel_btn.setStyleSheet("background-color: #E53935; color: white; padding: 8px; font-weight: bold; border-radius: 6px;")
        def _on_cancel():
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_click()
            except Exception:
                pass
            self.reject()
        self.cancel_btn.clicked.connect(_on_cancel)
        btn_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(btn_layout)
        self.thread = None

    def closeEvent(self, event):
        en = self.lang == "en"
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Warning" if en else "Uyarı", "Installation in progress, please wait!" if en else "Kurulum işlemi devam ediyor, lütfen bekleyin!")
            event.ignore()
        else:
            event.accept()

    def reject(self):
        en = self.lang == "en"
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Warning" if en else "Uyarı", "Installation in progress, please wait!" if en else "Kurulum işlemi devam ediyor, lütfen bekleyin!")
            return
        super().reject()

    def extract_base_version(self, ver_str):
        return RuntimeProvisioner.extract_base_version(ver_str)

    def start_install(self):
        engine = self.engine_combo.currentText()
        mc_dir = self.main_window.mc_dir
        
        if hasattr(self.main_window, 'sound_mgr') and self.main_window.sound_mgr:
            self.main_window.sound_mgr.play_click()
            
        self.install_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.engine_combo.setEnabled(False)
        self.progress_bar.show()
        
        self.thread = EngineInstallThread(engine, self.base_mc_version, mc_dir, lang=self.lang)
        self.thread.progress_update.connect(self.update_progress)
        self.thread.finished_install.connect(self.on_install_finished)
        self.thread.start()
        
        # Keep reference to prevent GC
        self.main_window._api_threads = getattr(self.main_window, '_api_threads', [])
        self.main_window._api_threads.append(self.thread)
        
    def update_progress(self, current, total, text):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        if text:
            self.status_lbl.setText(text)
            
    def on_install_finished(self, success, result):
        en = self.lang == "en"
        if success:
            if hasattr(self.main_window, 'sound_mgr') and self.main_window.sound_mgr:
                self.main_window.sound_mgr.play_levelup()
            QMessageBox.information(
                self,
                "Success" if en else "Başarılı",
                f"Engine installed successfully!\nNew Version: {result}" if en else f"Motor başarıyla kuruldu!\nYeni Sürüm: {result}"
            )
            # Update config and UI
            loader_val = self.engine_combo.currentText().lower()
            if hasattr(self.main_window, "update_profile_runtime"):
                self.main_window.update_profile_runtime(self.profile_id, result, loader_val)
            else:
                self.main_window.profiles[self.profile_id]["version"] = result
                self.main_window.profiles[self.profile_id]["loader"] = loader_val
                self.main_window.save_config()
                self.main_window.on_profile_selected()
            self.accept()
        else:
            if hasattr(self.main_window, 'sound_mgr') and self.main_window.sound_mgr:
                self.main_window.sound_mgr.play_error()
            QMessageBox.critical(
                self,
                "Error" if en else "Hata",
                f"Installation failed:\n{result}" if en else f"Kurulum başarısız oldu:\n{result}"
            )
            self.install_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.engine_combo.setEnabled(True)
            self.progress_bar.hide()
            self.status_lbl.setText("An error occurred." if en else "Hata oluştu.")

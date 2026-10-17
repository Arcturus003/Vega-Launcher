__app_name__ = "Vega Launcher"
__author__ = "Arcturus"
__version__ = "2.0.0"
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
import time

# Görev çubuğunda (Taskbar) ve Görev Yöneticisi'nde doğru ikon/isimle çıkması için
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Arcturus.VegaLauncher.1.0")
    ctypes.windll.kernel32.SetConsoleTitleW("Vega Launcher")
except (AttributeError, OSError, Exception): pass

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QSizePolicy, 
                               QHBoxLayout, QPushButton, QLabel, QLineEdit, QScrollArea,
                               QStackedWidget, QSplitter, QComboBox, QMessageBox, QDialog, QFormLayout, QSpinBox, QListWidget, QListWidgetItem, QProgressDialog, QProgressBar,
                               QFrame, QGridLayout, QFileDialog, QMenu, QCheckBox, QSlider)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QUrl
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPainterPath, QPen, QColor, QShortcut, QKeySequence, QFontDatabase

from mod_manager import (
    ModrinthAPI,
    ContentCatalog,
    CompatibilityPolicy,
    DownloadModThread,
    DownloadModpackThread,
    ProjectDetailsThread,
    ModrinthSearchThread,
)
from ui_components import NavBar, ActionBar, InstalledModsPanel
from card_widget import CardWidget, ImageLoaderThread, format_number, _ICON_CACHE
from auth_window import MicrosoftLoginDialog, protect_token, unprotect_token
from vanilla_thread import DownloadVanillaThread
from runtime_provisioner import RuntimeProvisioner, RuntimeSpec, RuntimeInstallThread
from playtime_tracker import PlaytimeTrackerThread
from profile_store import ProfileAndConfigStore, DEFAULT_SETTINGS
from server_widget import ServerWidget
from sound_manager import SoundManager
from particle_overlay import ParticleOverlay
from launch_pipeline import GameLaunchPipeline, DEFAULT_LAUNCH_PIPELINE
from auth_vault import AuthenticationVault, DEFAULT_AUTH_VAULT
import theme_manager

class TokenValidationThread(QThread):
    validation_finished = Signal(dict)

    def __init__(self, ms_login, parent=None):
        super().__init__(parent)
        self.ms_login = ms_login

    def run(self):
        token = (self.ms_login or {}).get("access_token", "")
        is_valid = False
        network_error = False
        if token:
            try:
                import requests
                r = requests.get(
                    "https://api.minecraftservices.com/minecraft/profile",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5
                )
                if r.status_code == 200:
                    is_valid = True
                elif r.status_code == 401:
                    is_valid = False
                else:
                    network_error = True
            except Exception as e:
                print(f"[Auth] Token validation network error: {e}")
                network_error = True

        if is_valid:
            self.validation_finished.emit({"status": "ok"})
            return

        if network_error:
            self.validation_finished.emit({"status": "network_error"})
            return

        refresh_token = (self.ms_login or {}).get("refresh_token")
        if refresh_token:
            try:
                import minecraft_launcher_lib.microsoft_account as ma
                from auth_window import CLIENT_ID, REDIRECT_URI
                refreshed = ma.complete_refresh(CLIENT_ID, None, REDIRECT_URI, refresh_token)
                if refreshed and "access_token" in refreshed:
                    self.validation_finished.emit({"status": "ok", "refreshed_login": refreshed})
                    return
            except Exception as e:
                print(f"[Auth] Token refresh error: {e}")
                err_str = str(e).lower()
                is_net_err = False
                try:
                    import requests
                    if isinstance(e, requests.exceptions.RequestException):
                        is_net_err = True
                except Exception:
                    pass
                if not is_net_err and isinstance(e, (OSError, IOError)):
                    is_net_err = True
                if not is_net_err and any(x in err_str for x in ["connection", "timeout", "network", "getaddrinfo", "max retries", "disconnected", "reset", "abort", "unreachable"]):
                    is_net_err = True

                if is_net_err:
                    self.validation_finished.emit({"status": "network_error_abort", "error_msg": str(e)})
                    return

        self.validation_finished.emit({"status": "need_login"})

class EditProfileDialog(QDialog):
    def __init__(self, current_name, current_ram, current_icon="", current_banner="", parent=None):
        if isinstance(current_banner, QWidget):
            parent = current_banner
            current_banner = ""
        super().__init__(parent)
        self.delete_requested = False
        lang = "tr"
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            lang = parent.settings.get("language", "tr")
        self.is_en = (lang == "en")
        en = self.is_en
        self.setWindowTitle("Edit Profile" if en else "Profili Düzenle")
        self.resize(520, 640)
        self.setMinimumWidth(480)
        
        self.current_icon = (current_icon or "🎮").strip()
        self.current_banner = (current_banner or "").strip()
        self.preset_buttons = []
        self.preset_banner_buttons = []

        theme_key = "electric_amethyst"
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            theme_key = parent.settings.get("theme", "electric_amethyst")
        self.theme_key = theme_key
        t_data = theme_manager.get_theme(theme_key)
        r, g, b = t_data["rgb"]
        glow_color = t_data["glow"]
        prim_light = t_data["primary_light"]
        primary_color = t_data["primary"]
        grad_start = t_data["gradient_start"]
        
        base_dlg_qss = """
            QDialog {
                background-color: #12121A;
                border: 1px solid rgba(139, 92, 246, 0.45);
                border-radius: 14px;
            }
            QLabel {
                color: #F8FAFC;
                font-size: 13px;
                font-weight: 600;
            }
            QLineEdit, QSpinBox {
                background: #1A1A26;
                border: 1px solid rgba(139, 92, 246, 0.35);
                border-radius: 8px;
                padding: 6px 12px;
                color: #FFFFFF;
                font-size: 13px;
            }
            QLineEdit:focus, QSpinBox:focus {
                border-color: #A855F7;
                background: #202030;
            }
        """
        self.setStyleSheet(theme_manager.generate_theme_qss(base_dlg_qss, theme_key))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        title_lbl = QLabel("Edit Profile Settings" if en else "Profil Ayarlarını Düzenle")
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: 800; color: {glow_color};")
        layout.addWidget(title_lbl)

        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        self.name_input = QLineEdit()
        self.name_input.setText(current_name)

        self.ram_input = QSpinBox()
        self.ram_input.setRange(1024, 32768)
        self.ram_input.setSingleStep(1024)
        self.ram_input.setValue(current_ram)
        self.ram_input.setSuffix(" MB")

        form_layout.addRow(("Profile Name:" if en else "Profil Adı:"), self.name_input)
        form_layout.addRow(("RAM Amount:" if en else "RAM Miktarı:"), self.ram_input)
        layout.addLayout(form_layout)

        # --- ICON SELECTOR SECTION ---
        icon_sec_lbl = QLabel("Profile Icon / Emoji:" if en else "Profil Simgesi / Emojisi:")
        icon_sec_lbl.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {prim_light}; margin-top: 2px;")
        layout.addWidget(icon_sec_lbl)

        icon_row = QHBoxLayout()
        icon_row.setSpacing(12)

        self.preview_box = QFrame()
        self.preview_box.setFixedSize(50, 50)
        self.preview_box.setStyleSheet(f"""
            QFrame {{
                background: rgba({r}, {g}, {b}, 0.2);
                border: 2px solid {primary_color};
                border-radius: 12px;
            }}
        """)
        p_lay = QVBoxLayout(self.preview_box)
        p_lay.setContentsMargins(0, 0, 0, 0)
        self.preview_lbl = QLabel(self.current_icon or "🎮")
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        self.preview_lbl.setStyleSheet("font-size: 26px; background: transparent; font-family: 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif;")
        p_lay.addWidget(self.preview_lbl)
        icon_row.addWidget(self.preview_box)

        custom_vbox = QVBoxLayout()
        custom_vbox.setSpacing(4)
        hint_lbl = QLabel("Özel emoji girin (veya listeden seçin):" if not en else "Type custom emoji (or choose below):")
        hint_lbl.setStyleSheet("font-size: 11px; color: #94A3B8; font-weight: 500;")
        self.custom_icon_input = QLineEdit()
        self.custom_icon_input.setPlaceholderText("Örn: 🎮, ⚔️, ⛏️" if not en else "E.g.: 🎮, ⚔️, ⛏️")
        self.custom_icon_input.setStyleSheet("font-family: 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', 'Segoe UI', sans-serif; font-size: 18px; padding: 2px 8px;")
        self.custom_icon_input.setText(self.current_icon or "🎮")
        self.custom_icon_input.textChanged.connect(self._on_custom_icon_changed)
        custom_vbox.addWidget(hint_lbl)
        custom_vbox.addWidget(self.custom_icon_input)
        icon_row.addLayout(custom_vbox)
        layout.addLayout(icon_row)

        presets = [
            "🎮", "⚔️", "⛏️", "🛡️", "🧙", "🚀", "💎", "🐉",
            "⚙️", "🧪", "🏹", "🏰", "🧟", "🌱", "🌾", "📦"
        ]
        grid = QGridLayout()
        grid.setSpacing(6)
        cols = 8
        for i, sym in enumerate(presets):
            btn = QPushButton(sym)
            btn.setFixedSize(36, 36)
            btn.setCursor(Qt.PointingHandCursor)
            is_active = (sym == (self.current_icon or "🎮"))
            self._style_preset_btn(btn, is_active)
            btn.clicked.connect(lambda ch=False, s=sym, b=btn: self._select_preset_icon(s, b))
            self.preset_buttons.append((sym, btn))
            grid.addWidget(btn, i // cols, i % cols)
        layout.addLayout(grid)

        # --- BANNER SELECTOR SECTION ---
        banner_sec_lbl = QLabel("Profile Showcase Banner:" if en else "Profil Vitrin Bannerı:")
        banner_sec_lbl.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {prim_light}; margin-top: 4px;")
        layout.addWidget(banner_sec_lbl)

        self.banner_preview = QFrame()
        self.banner_preview.setFixedHeight(48)
        self.banner_preview.setCursor(Qt.PointingHandCursor)
        bp_lay = QVBoxLayout(self.banner_preview)
        bp_lay.setContentsMargins(12, 0, 12, 0)
        self.banner_preview_lbl = QLabel("")
        self.banner_preview_lbl.setStyleSheet("color: white; font-weight: 700; font-size: 12px; background: transparent;")
        bp_lay.addWidget(self.banner_preview_lbl, alignment=Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self.banner_preview)

        # Banner Presets
        banner_chips_lay = QHBoxLayout()
        banner_chips_lay.setSpacing(6)
        presets_info = theme_manager.get_banner_preset_names("en" if en else "tr")
        for key, name in presets_info:
            b_btn = QPushButton(name)
            b_btn.setCursor(Qt.PointingHandCursor)
            b_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.06);
                    color: #CBD5E1;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 6px;
                    padding: 4px 8px;
                    font-size: 11px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background: rgba({r}, {g}, {b}, 0.22);
                    border-color: {prim_light};
                    color: white;
                }}
            """)
            b_btn.clicked.connect(lambda ch=False, k=key: self._select_preset_banner(k))
            self.preset_banner_buttons.append((key, b_btn))
            banner_chips_lay.addWidget(b_btn)
        layout.addLayout(banner_chips_lay)

        # Custom Banner File Row
        custom_banner_row = QHBoxLayout()
        custom_banner_row.setSpacing(8)
        self.btn_choose_banner = QPushButton("Choose Custom Image..." if en else "Özel Görsel Seç...")
        self.btn_choose_banner.setCursor(Qt.PointingHandCursor)
        self.btn_choose_banner.setStyleSheet(f"""
            QPushButton {{
                background: rgba({r}, {g}, {b}, 0.18);
                color: #EDE9FE;
                border: 1px solid rgba({r}, {g}, {b}, 0.4);
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: rgba({r}, {g}, {b}, 0.32);
                border-color: {glow_color};
            }}
        """)
        self.btn_choose_banner.clicked.connect(lambda checked=False: self._choose_custom_banner())

        self.btn_clear_banner = QPushButton("Default" if en else "Varsayılan")
        self.btn_clear_banner.setCursor(Qt.PointingHandCursor)
        self.btn_clear_banner.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                color: #94A3B8;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: white;
                background: rgba(255, 255, 255, 0.12);
            }
        """)
        self.btn_clear_banner.clicked.connect(lambda checked=False: self._select_preset_banner(""))

        custom_banner_row.addWidget(self.btn_choose_banner)
        custom_banner_row.addWidget(self.btn_clear_banner)
        custom_banner_row.addStretch()
        layout.addLayout(custom_banner_row)

        self._update_banner_preview()

        layout.addSpacing(4)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        del_btn = QPushButton("Delete Profile" if en else "Profili Sil")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setStyleSheet("""
            QPushButton {
                background: rgba(239, 68, 68, 0.15);
                color: #F87171;
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 8px;
                padding: 7px 14px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #DC2626;
                color: #FFFFFF;
                border-color: #EF4444;
            }
        """)
        del_btn.clicked.connect(lambda checked=False: self._on_delete_clicked(en))
        btn_layout.addWidget(del_btn)

        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel" if en else "İptal")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.06);
                color: #CBD5E1;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 7px 16px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.12);
                color: white;
            }
        """)
        cancel_btn.clicked.connect(self._on_cancel_clicked)

        save_btn = QPushButton("Save" if en else "Kaydet")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {grad_start}, stop:1 {prim_light});
                color: white;
                font-weight: 700;
                border: none;
                border-radius: 8px;
                padding: 7px 20px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {primary_color}, stop:1 {glow_color});
            }}
        """)
        save_btn.clicked.connect(self._on_save_clicked)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _on_save_clicked(self):
        try:
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.accept()

    def _on_cancel_clicked(self):
        try:
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.reject()

    def _update_banner_preview(self):
        banner = self.current_banner
        theme_key = getattr(self, "theme_key", "electric_amethyst")
        t_data = theme_manager.get_theme(theme_key)
        r, g, b = t_data["rgb"]
        prim_light = t_data["primary_light"]
        if not banner:
            self.banner_preview.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba({r}, {g}, {b}, 0.35), stop:1 rgba(18, 18, 26, 0.95));
                    border: 1px dashed {prim_light};
                    border-radius: 10px;
                }}
            """)
            self.banner_preview_lbl.setText("Default Theme Banner" if self.is_en else "Varsayılan Tema Vitrini")
        elif banner in theme_manager.BANNER_PRESETS:
            preset = theme_manager.BANNER_PRESETS[banner]
            self.banner_preview.setStyleSheet(f"""
                QFrame {{
                    background: {preset['gradient']};
                    border: 1.5px solid {preset['accent']};
                    border-radius: 10px;
                }}
            """)
            self.banner_preview_lbl.setText(preset.get("name_en" if self.is_en else "name_tr", banner))
        elif os.path.exists(banner):
            fwd = banner.replace("\\", "/")
            self.banner_preview.setStyleSheet(f"""
                QFrame {{
                    background-image: url('{fwd}');
                    background-position: center;
                    border: 1.5px solid {prim_light};
                    border-radius: 10px;
                }}
            """)
            self.banner_preview_lbl.setText(os.path.basename(banner))
        else:
            self.banner_preview.setStyleSheet("QFrame { background: #1A1A26; border-radius: 10px; }")
            self.banner_preview_lbl.setText(banner)

    def _select_preset_banner(self, preset_key: str):
        try:
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.current_banner = preset_key
        self._update_banner_preview()

    def _choose_custom_banner(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Banner Image" if self.is_en else "Banner Görseli Seç",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if file_path:
            try:
                SoundManager.get_instance().play_click()
            except Exception:
                pass
            self.current_banner = file_path
            self._update_banner_preview()

    def _style_preset_btn(self, btn, is_active):
        theme_key = getattr(self, "theme_key", "electric_amethyst")
        t_data = theme_manager.get_theme(theme_key)
        r, g, b = t_data["rgb"]
        glow = t_data["glow"]
        prim = t_data["primary"]
        base = """
            QPushButton {
                padding: 0px;
                margin: 0px;
                font-size: 19px;
                font-family: 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', sans-serif;
                text-align: center;
        """
        if is_active:
            btn.setStyleSheet(base + f"""
                background: rgba({r}, {g}, {b}, 0.45);
                border: 2px solid {glow};
                border-radius: 8px;
            }}
            """)
        else:
            btn.setStyleSheet(base + f"""
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: rgba({r}, {g}, {b}, 0.25);
                border-color: {prim};
            }}
            """)

    def _select_preset_icon(self, sym, active_btn):
        try:
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.current_icon = sym
        self.preview_lbl.setText(sym)
        self.custom_icon_input.blockSignals(True)
        self.custom_icon_input.setText(sym)
        self.custom_icon_input.blockSignals(False)
        for s, b in self.preset_buttons:
            self._style_preset_btn(b, s == sym)

    def _on_custom_icon_changed(self, text):
        clean = text.strip()
        self.current_icon = clean or "🎮"
        self.preview_lbl.setText(self.current_icon)
        for s, b in self.preset_buttons:
            self._style_preset_btn(b, s == self.current_icon)

    def _on_delete_clicked(self, en):
        reply = QMessageBox.question(
            self,
            "Confirm Delete" if en else "Silme Onayı",
            f"'{self.name_input.text().strip()}' profilini tamamen silmek istediğinize emin misiniz?\n(Tüm modlar ve ayarlar silinecektir)"
            if not en else
            f"Are you sure you want to permanently delete profile '{self.name_input.text().strip()}'?\n(All mods and settings will be removed)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.delete_requested = True
            self.reject()

    def get_data(self):
        return self.name_input.text().strip(), self.ram_input.value(), (self.current_icon or "").strip(), (self.current_banner or "").strip()

class AddProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        lang = "tr"
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            lang = parent.settings.get("language", "tr")
        en = (lang == "en")

        self.setWindowTitle("Add New Profile" if en else "Yeni Profil Ekle")
        self.resize(380, 240)
        if parent: self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        
        form_layout = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g.: Zombie Adventure" if en else "Örn: Zombi Macerası")
        
        self.version_input = QComboBox()
        self.load_versions()
        
        self.engine_combo = QComboBox()
        loaders = [
            ("Fabric (Önerilen)" if not en else "Fabric (Recommended)", "fabric"),
            ("NeoForge (1.20.2+)", "neoforge"),
            ("Forge", "forge"),
            ("Quilt", "quilt"),
            ("Vanilla (Saf Minecraft)" if not en else "Vanilla (Pure Minecraft)", "vanilla"),
        ]
        for label, val in loaders:
            self.engine_combo.addItem(label, val)

        def_ram = 4096
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            def_ram = int(parent.settings.get("default_ram", 4096) or 4096)
        self.ram_input = QSpinBox()
        self.ram_input.setRange(1024, 32768)
        self.ram_input.setSingleStep(512)
        self.ram_input.setValue(def_ram)
        self.ram_input.setSuffix(" MB")
        
        form_layout.addRow("Profile Name:" if en else "Profil Adı:", self.name_input)
        form_layout.addRow("Version:" if en else "Sürüm:", self.version_input)
        form_layout.addRow("Game Engine:" if en else "Oyun Motoru:", self.engine_combo)
        form_layout.addRow("RAM (MB):", self.ram_input)
        
        layout.addLayout(form_layout)
        
        button_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save" if en else "Kaydet")
        self.cancel_btn = QPushButton("Cancel" if en else "İptal")
        self.cancel_btn.setStyleSheet("background-color: #B22222; border-color: #8B0000;")
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

        self.save_btn.clicked.connect(self._on_save_clicked)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)

    def _on_save_clicked(self):
        try:
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.accept()

    def _on_cancel_clicked(self):
        try:
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.reject()

    def load_versions(self):
        self.version_input.clear()
        standard_versions = [
            "1.21.4", "1.21.3", "1.21.1", "1.21",
            "1.20.6", "1.20.4", "1.20.2", "1.20.1",
            "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5", "1.12.2"
        ]
        discovered = set()
        mc_dir = getattr(self.parent(), "mc_dir", None) or os.path.join(os.getenv("APPDATA", ""), ".minecraft")
        versions_dir = os.path.join(mc_dir, "versions")
        if os.path.exists(versions_dir):
            for d in os.listdir(versions_dir):
                if os.path.isdir(os.path.join(versions_dir, d)):
                    base_v = RuntimeProvisioner.extract_base_version(d, default=None)
                    if base_v:
                        discovered.add(base_v)
                    else:
                        discovered.add(d)

        all_versions = list(standard_versions)
        for v in sorted(discovered, reverse=True):
            if v not in all_versions:
                all_versions.append(v)

        self.version_input.addItems(all_versions)
        idx = self.version_input.findText("1.20.1")
        if idx >= 0:
            self.version_input.setCurrentIndex(idx)
        self.version_input.setEditable(True)

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "version": self.version_input.currentText().strip(),
            "loader": self.engine_combo.currentData() or "fabric",
            "ram": self.ram_input.value()
        }

class ProfileWidget(QWidget):
    update_clicked = Signal(str)
    
    def __init__(self, name, version, ram, profile_id, icon="", parent=None, lang="tr"):
        super().__init__(parent)
        self.profile_id = profile_id
        self.lang = lang
        self.setFixedHeight(72)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 7, 14, 13)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignVCenter)
        
        self.icon_box = QFrame()
        self.icon_box.setFixedSize(46, 46)
        self.icon_box.setStyleSheet("""
            QFrame {
                background: rgba(139, 92, 246, 0.16);
                border: 1px solid rgba(139, 92, 246, 0.35);
                border-radius: 8px;
            }
        """)
        icon_box_lay = QVBoxLayout(self.icon_box)
        icon_box_lay.setContentsMargins(0, 0, 0, 0)
        disp_icon = icon or "🎮"
        self.icon_lbl = QLabel(disp_icon)
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        is_emoji = any(ord(c) > 0x2000 for c in disp_icon)
        f_size = "22px" if is_emoji else "15px"
        self.icon_lbl.setStyleSheet(f"font-size: {f_size}; font-weight: bold; color: #EDE9FE; background: transparent; font-family: 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', 'Segoe UI', sans-serif;")
        icon_box_lay.addWidget(self.icon_lbl)
        layout.addWidget(self.icon_box)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        info_layout.setAlignment(Qt.AlignVCenter)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #F8FAFC; background: transparent;")
        info_layout.addWidget(name_lbl)
        
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(6)
        meta_layout.setAlignment(Qt.AlignVCenter)
        disp_version = str(version).replace("fabric-loader-", "fabric-")
        self.v_badge = QLabel(f"v {disp_version}")
        self.v_badge.setStyleSheet("color: #A78BFA; font-size: 12px; font-weight: 600; background: transparent;")
        
        sep = QLabel("·")
        sep.setStyleSheet("color: #475569; font-weight: bold; font-size: 12px; background: transparent;")
        
        r_badge = QLabel(f"{ram} MB RAM")
        r_badge.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 500; background: transparent;")
        
        meta_layout.addWidget(self.v_badge)
        meta_layout.addWidget(sep)
        meta_layout.addWidget(r_badge)
        
        self.update_btn = QPushButton("Update" if lang == "en" else "Güncelle")
        self.update_btn.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F59E0B, stop:1 #D97706); color: white; font-weight: 700; border-radius: 6px; padding: 2px 8px; font-size: 11px;")
        self.update_btn.setVisible(False)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(lambda checked=False: self.update_clicked.emit(self.profile_id))
        meta_layout.addWidget(self.update_btn)
        
        meta_layout.addStretch()
        
        info_layout.addLayout(meta_layout)
        layout.addLayout(info_layout)
        layout.addStretch()

        self.check_lbl = QLabel("✓")
        self.check_lbl.setStyleSheet("font-size: 18px; font-weight: 900; color: #C084FC; background: transparent; padding-right: 6px;")
        self.check_lbl.setVisible(False)
        layout.addWidget(self.check_lbl)

        init_th = "electric_amethyst"
        if parent:
            try:
                win = parent.window() if hasattr(parent, "window") else parent
                if win and hasattr(win, "settings") and isinstance(win.settings, dict):
                    init_th = win.settings.get("theme", "electric_amethyst")
            except Exception:
                pass
        self.set_theme(init_th)

    def set_selected(self, selected: bool):
        if hasattr(self, "check_lbl"):
            self.check_lbl.setVisible(bool(selected))

    def set_theme(self, theme_key):
        self._active_theme = theme_key
        try:
            t = theme_manager.get_theme(theme_key)
            r, g, b = t["rgb"]
            glow = t["glow"]
            self.setStyleSheet("ProfileWidget { background: transparent; border: none; }")
            if hasattr(self, "icon_box"):
                self.icon_box.setStyleSheet(f"""
                    QFrame {{
                        background: rgba({r}, {g}, {b}, 0.16);
                        border: 1px solid rgba({r}, {g}, {b}, 0.35);
                        border-radius: 8px;
                    }}
                """)
            if hasattr(self, "v_badge"):
                self.v_badge.setStyleSheet(f"color: {glow}; font-size: 12px; font-weight: 600; background: transparent;")
            if hasattr(self, "check_lbl"):
                self.check_lbl.setStyleSheet(f"font-size: 18px; font-weight: 900; color: {glow}; background: transparent; padding-right: 6px;")
        except Exception:
            pass

    def set_language(self, lang="tr"):
        self.lang = lang
        if hasattr(self, "update_btn"):
            self.update_btn.setText("Update" if lang == "en" else "Güncelle")

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(200, 72)

class DetailPanel(QWidget):
    download_requested = Signal(object)
    drawer_closed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Widget)
        self.setWindowFlags(Qt.Widget)
        self.setObjectName("DetailPanel")
        self.setMinimumWidth(320)
        self.setMaximumWidth(440)
        self.current_project = None
        self.img_threads = []
        self.image_cache = {}
        self.lang = "tr"
        self.selected_ram = 6144
        self._loaded_thumb_urls = set()
        self._current_gallery_urls = set()
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(10)
        
        # Header (Title + Close Button)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        
        self.title = QLabel("Seçim Bekleniyor", self)
        self.title.setWindowFlags(Qt.Widget)
        self.title.setStyleSheet("font-size: 18px; font-weight: 800; color: #C084FC;")
        self.title.setWordWrap(True)
        header_layout.addWidget(self.title, 1)
        
        self.close_btn = QPushButton("✕", self)
        self.close_btn.setWindowFlags(Qt.Widget)
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                color: #CBD5E1;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 14px;
                font-weight: bold;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 14px;
                padding: 0px;
                margin: 0px;
                text-align: center;
            }
            QPushButton:hover {
                background: rgba(239, 68, 68, 0.35);
                color: #FFFFFF;
                border-color: #EF4444;
            }
            QPushButton:pressed {
                background: rgba(220, 38, 38, 0.5);
                border-color: #DC2626;
            }
        """)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.clicked.connect(self.close_drawer)
        header_layout.addWidget(self.close_btn)
        main_layout.addLayout(header_layout)
        
        # Scrollable content area
        self.content_scroll = QScrollArea(self)
        self.content_scroll.setWindowFlags(Qt.Widget)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setStyleSheet("background: transparent; border: none;")
        
        self.content_widget = QWidget(self.content_scroll)
        self.content_widget.setWindowFlags(Qt.Widget)
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 6, 0)
        self.content_layout.setSpacing(10)
        
        # Author
        self.author_lbl = QLabel("", self.content_widget)
        self.author_lbl.setWindowFlags(Qt.Widget)
        self.author_lbl.setStyleSheet("font-size: 12px; color: #94A3B8; font-weight: 600;")
        self.author_lbl.setVisible(False)
        self.content_layout.addWidget(self.author_lbl)
        
        # Stats row
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(8)
        self.downloads_lbl = QLabel("0", self.content_widget)
        self.downloads_lbl.setWindowFlags(Qt.Widget)
        self.downloads_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #CBD5E1; background: rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 3px 8px;")
        self.follows_lbl = QLabel("0", self.content_widget)
        self.follows_lbl.setWindowFlags(Qt.Widget)
        self.follows_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #FBBF24; background: rgba(251, 191, 36, 0.12); border-radius: 6px; padding: 3px 8px;")
        self.stats_row.addWidget(self.downloads_lbl)
        self.stats_row.addWidget(self.follows_lbl)
        self.stats_row.addStretch()
        self.content_layout.addLayout(self.stats_row)
        
        # Tags row
        self.tags_row = QHBoxLayout()
        self.tags_row.setSpacing(6)
        self.tags_row.setAlignment(Qt.AlignLeft)
        self.content_layout.addLayout(self.tags_row)
        
        # Gallery Preview (Main large image)
        self.main_gallery_preview = QLabel("Görsel Bulunmuyor", self.content_widget)
        self.main_gallery_preview.setWindowFlags(Qt.Widget)
        self.main_gallery_preview.setFixedHeight(170)
        self.main_gallery_preview.setAlignment(Qt.AlignCenter)
        self.main_gallery_preview.setStyleSheet("""
            background-color: rgba(10, 10, 16, 0.9);
            border: 1px solid rgba(139, 92, 246, 0.25);
            border-radius: 10px;
            color: #64748B;
            font-size: 12px;
        """)
        self.content_layout.addWidget(self.main_gallery_preview)
        
        # Thumbnail strip
        self.thumb_scroll = QScrollArea(self.content_widget)
        self.thumb_scroll.setWindowFlags(Qt.Widget)
        self.thumb_scroll.setFixedHeight(54)
        self.thumb_scroll.setWidgetResizable(True)
        self.thumb_scroll.setStyleSheet("background: transparent; border: none;")
        self.thumb_container = QWidget(self.thumb_scroll)
        self.thumb_container.setWindowFlags(Qt.Widget)
        self.thumb_container.setStyleSheet("background: transparent;")
        self.thumb_layout = QHBoxLayout(self.thumb_container)
        self.thumb_layout.setContentsMargins(0, 2, 0, 2)
        self.thumb_layout.setSpacing(6)
        self.thumb_layout.setAlignment(Qt.AlignLeft)
        self.thumb_scroll.setWidget(self.thumb_container)
        self.content_layout.addWidget(self.thumb_scroll)
        
        # Modpack Settings (Version + RAM chips)
        self.modpack_settings_widget = QWidget(self.content_widget)
        self.modpack_settings_widget.setWindowFlags(Qt.Widget)
        self.modpack_settings_layout = QVBoxLayout(self.modpack_settings_widget)
        self.modpack_settings_layout.setContentsMargins(0, 0, 0, 0)
        self.modpack_settings_layout.setSpacing(8)
        
        self.lbl_ver_header = QLabel("Sürüm & Yükleyici:", self.modpack_settings_widget)
        self.lbl_ver_header.setWindowFlags(Qt.Widget)
        self.lbl_ver_header.setStyleSheet("font-size: 12px; font-weight: 700; color: #E2E8F0;")
        self.modpack_settings_layout.addWidget(self.lbl_ver_header)
        
        self.version_combo = QComboBox(self.modpack_settings_widget)
        self.version_combo.setWindowFlags(Qt.Widget)
        self.version_combo.setFixedHeight(36)
        self.modpack_settings_layout.addWidget(self.version_combo)
        
        self.lbl_ram_header = QLabel("Önerilen Bellek (RAM):", self.modpack_settings_widget)
        self.lbl_ram_header.setWindowFlags(Qt.Widget)
        self.lbl_ram_header.setStyleSheet("font-size: 12px; font-weight: 700; color: #E2E8F0; margin-top: 4px;")
        self.modpack_settings_layout.addWidget(self.lbl_ram_header)
        
        self.ram_chips_layout = QHBoxLayout()
        self.ram_chips_layout.setSpacing(8)
        self.ram_buttons = {}
        for amt, txt in [(4096, "4 GB"), (6144, "6 GB"), (8192, "8 GB")]:
            btn = QPushButton(txt, self.modpack_settings_widget)
            btn.setWindowFlags(Qt.Widget)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda ch=False, a=amt: self.set_ram(a))
            self.ram_buttons[amt] = btn
            self.ram_chips_layout.addWidget(btn)
        self.update_ram_chips()
        self.modpack_settings_layout.addLayout(self.ram_chips_layout)
        
        self.content_layout.addWidget(self.modpack_settings_widget)
        
        # Description
        self.desc_header = QLabel("Hakkında", self.content_widget)
        self.desc_header.setWindowFlags(Qt.Widget)
        self.desc_header.setStyleSheet("font-size: 13px; font-weight: 700; color: #F1F5F9; margin-top: 6px;")
        self.content_layout.addWidget(self.desc_header)
        
        self.desc = QLabel("", self.content_widget)
        self.desc.setWindowFlags(Qt.Widget)
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #94A3B8; font-size: 12px; line-height: 1.4;")
        self.content_layout.addWidget(self.desc)
        
        self.content_layout.addStretch()
        self.content_scroll.setWidget(self.content_widget)
        main_layout.addWidget(self.content_scroll, 1)
        
        # Pinned Action Button
        self.download_btn = QPushButton("Modpack'i Kur ve Profil Oluştur", self)
        self.download_btn.setWindowFlags(Qt.Widget)
        self.download_btn.setFixedHeight(46)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7C3AED, stop:1 #A855F7);
                border: 1px solid #C084FC;
                border-radius: 10px;
                color: #FFFFFF;
                font-size: 13px;
                font-weight: 800;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8B5CF6, stop:1 #C084FC);
                border-color: #E9D5FF;
            }
            QPushButton:disabled {
                background: rgba(255, 255, 255, 0.08);
                border-color: rgba(255, 255, 255, 0.1);
                color: #64748B;
            }
        """)
        self.download_btn.clicked.connect(self.on_download_click)
        self.download_btn.setEnabled(False)
        main_layout.addWidget(self.download_btn)

    def close_drawer(self):
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_enderchest_close()
        except Exception:
            pass
        self.hide()
        self.drawer_closed.emit()

    def set_ram(self, amount):
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.selected_ram = amount
        self.update_ram_chips()

    def update_ram_chips(self):
        for amt, btn in self.ram_buttons.items():
            if amt == self.selected_ram:
                btn.setStyleSheet("""
                    QPushButton {
                        background: #8B5CF6;
                        color: #FFFFFF;
                        border: 1px solid #C084FC;
                        font-weight: bold;
                        border-radius: 6px;
                        font-size: 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(255, 255, 255, 0.06);
                        color: #94A3B8;
                        border: 1px solid rgba(255, 255, 255, 0.12);
                        font-weight: 600;
                        border-radius: 6px;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background: rgba(139, 92, 246, 0.2);
                        color: #FFFFFF;
                        border-color: #8B5CF6;
                    }
                """)

    def set_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        self.lbl_ver_header.setText("Version & Loader:" if en else "Sürüm & Yükleyici:")
        self.lbl_ram_header.setText("Recommended RAM:" if en else "Önerilen Bellek (RAM):")
        self.desc_header.setText("About" if en else "Hakkında")
        cur_gal_txt = self.main_gallery_preview.text()
        if cur_gal_txt in ("Görsel Bulunmuyor", "No Images Available"):
            self.main_gallery_preview.setText("No Images Available" if en else "Görsel Bulunmuyor")
        elif cur_gal_txt in ("Görsel yükleniyor...", "Loading image..."):
            self.main_gallery_preview.setText("Loading image..." if en else "Görsel yükleniyor...")
        if self.version_combo.count() > 0:
            v0 = self.version_combo.itemText(0)
            if v0 in ("En Son Sürüm (Otomatik)", "Latest Version (Auto)"):
                self.version_combo.setItemText(0, "Latest Version (Auto)" if en else "En Son Sürüm (Otomatik)")
        if not self.current_project:
            self.title.setText("Waiting for Selection" if en else "Seçim Bekleniyor")
            self.download_btn.setText("Download to Active Profile" if en else "Aktif Profile İndir")
        else:
            ptype = self.current_project.get("project_type", "mod")
            if ptype == "modpack":
                self.download_btn.setText("Install Modpack as New Profile" if en else "Modpack'i Kur ve Profil Oluştur")
            else:
                self.download_btn.setText("Download to Active Profile" if en else "Aktif Profile İndir")

    def on_download_click(self):
        if self.current_project:
            project_copy = dict(self.current_project)
            project_copy["selected_ram"] = self.selected_ram
            selected_ver = self.version_combo.currentData()
            if selected_ver:
                project_copy["selected_version_obj"] = selected_ver
            self.download_requested.emit(project_copy)

    def clear_gallery(self):
        self._loaded_thumb_urls = set()
        self._current_gallery_urls.clear()
        self.main_gallery_preview.setPixmap(QPixmap())
        self.main_gallery_preview.setText("Görsel yükleniyor..." if self.lang != "en" else "Loading image...")
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def update_info(self, data):
        self.current_project = data
        ptype = data.get("project_type", "mod")
        en = getattr(self, "lang", "tr") == "en"
        
        self.title.setText(data.get("title", "Loading..." if en else "Yükleniyor..."))
        author = data.get("author") or ""
        self.author_lbl.setText(f"by {author}" if author else "")
        self.author_lbl.setVisible(bool(author))
        
        downloads = data.get("downloads", 0)
        follows = data.get("follows", 0)
        self.downloads_lbl.setText(format_number(downloads))
        self.follows_lbl.setText(format_number(follows))
        
        # Tags
        while self.tags_row.count():
            item = self.tags_row.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        categories = data.get("categories", [])
        for cat in categories[:4]:
            if cat.lower() in ("modpack", "minecraft"): continue
            pill = QLabel(cat.capitalize(), self.content_widget)
            pill.setWindowFlags(Qt.Widget)
            pill.setAttribute(Qt.WA_NativeWindow, False)
            pill.setStyleSheet("color: #A78BFA; font-size: 10px; font-weight: 600; background: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.25); border-radius: 5px; padding: 2px 6px;")
            self.tags_row.addWidget(pill)
            
        self.desc.setText(data.get("description", ""))
        self.clear_gallery()
        
        if ptype == "modpack":
            self.modpack_settings_widget.setVisible(True)
            self.download_btn.setText("Install Modpack as New Profile" if en else "Modpack'i Kur ve Profil Oluştur")
        else:
            self.modpack_settings_widget.setVisible(False)
            self.download_btn.setText("Download to Active Profile" if en else "Aktif Profile İndir")
            
        self.download_btn.setEnabled(True)
        
        project_id = data.get("project_id")
        if not project_id: return
        
        if not hasattr(self, '_api_threads'):
            self._api_threads = []
        self._api_threads = [t for t in self._api_threads if t.isRunning()]
            
        v_filter = data.get("filter_version")
        l_filter = data.get("filter_loader")
        thread = ProjectDetailsThread(project_id, version=v_filter, loader=l_filter)
        self._api_threads.append(thread)
        thread.task_finished.connect(self.on_details_loaded)
        thread.start()

    def on_details_loaded(self, details):
        if not self.current_project:
            return
        cur_id = self.current_project.get("project_id")
        cur_slug = self.current_project.get("slug")
        ret_id = details.get("id") or details.get("project_id")
        ret_slug = details.get("slug")
        if cur_id and ret_id and cur_id != ret_id and cur_slug != ret_slug:
            return

        en = getattr(self, "lang", "tr") == "en"
        self.title.setText(details.get("title", "Untitled" if en else "İsimsiz"))
        self.desc.setText(details.get("description", "No description available." if en else "Açıklama bulunmuyor."))
        
        # Populate versions if modpack
        versions_list = details.get("versions_list", [])
        self.version_combo.clear()
        if versions_list:
            for ver in versions_list[:30]:
                v_num = ver.get("version_number") or ver.get("name") or "v"
                mc_vers = ver.get("game_versions", [])
                mc_str = mc_vers[0] if mc_vers else ""
                loaders = [l.capitalize() for l in ver.get("loaders", [])]
                ldr_str = ", ".join(loaders) if loaders else ""
                
                label = f"{v_num}"
                extra = []
                if mc_str: extra.append(f"MC {mc_str}")
                if ldr_str: extra.append(ldr_str)
                if extra:
                    label += f" ({' • '.join(extra)})"
                    
                self.version_combo.addItem(label, ver)
        else:
            self.version_combo.addItem("En Son Sürüm (Otomatik)" if not en else "Latest Version (Auto)", None)
            
        # Gallery
        gallery = details.get("gallery", [])
        urls_to_load = []
        if gallery:
            for item in gallery:
                url = item.get("url")
                if url: urls_to_load.append(url)
        elif details.get("icon_url"):
            urls_to_load.append(details.get("icon_url"))
            
        if urls_to_load:
            capped_urls = urls_to_load[:6]
            self._current_gallery_urls = set(capped_urls)
            self.img_threads = [t for t in self.img_threads if t.isRunning()]
            for idx, url in enumerate(capped_urls):
                if url in self.image_cache:
                    pix = self.image_cache[url]
                    if idx == 0:
                        self.set_main_preview(pix)
                    if url not in self._loaded_thumb_urls:
                        self._loaded_thumb_urls.add(url)
                        self.add_thumbnail(pix)
                elif url in _ICON_CACHE:
                    pix = QPixmap()
                    pix.loadFromData(_ICON_CACHE[url])
                    self.image_cache[url] = pix
                    if idx == 0:
                        self.set_main_preview(pix)
                    if url not in self._loaded_thumb_urls:
                        self._loaded_thumb_urls.add(url)
                        self.add_thumbnail(pix)
                else:
                    thread = ImageLoaderThread(url)
                    thread.loaded_with_url.connect(self.on_image_loaded)
                    self.img_threads.append(thread)
                    thread.start()
        else:
            self.main_gallery_preview.setText("No Images Available" if en else "Görsel Bulunmuyor")

    def on_image_loaded(self, url, data_bytes):
        if url not in self._current_gallery_urls:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data_bytes)
        if len(self.image_cache) >= 30:
            excess = len(self.image_cache) - 29
            for k in list(self.image_cache.keys())[:excess]:
                del self.image_cache[k]
        self.image_cache[url] = pixmap
        
        if not self.main_gallery_preview.pixmap() or self.main_gallery_preview.pixmap().isNull():
            self.set_main_preview(pixmap)
            
        if url not in self._loaded_thumb_urls:
            self._loaded_thumb_urls.add(url)
            self.add_thumbnail(pixmap)
            
        self.img_threads = [t for t in self.img_threads if t.isRunning()]

    def set_main_preview(self, pixmap):
        w = max(self.main_gallery_preview.width(), 320)
        h = max(self.main_gallery_preview.height(), 170)
        scaled = pixmap.scaled(QSize(w, h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.main_gallery_preview.setText("")
        self.main_gallery_preview.setPixmap(scaled)

    def add_thumbnail(self, pixmap):
        thumb_btn = QPushButton(parent=self.thumb_container)
        thumb_btn.setWindowFlags(Qt.Widget)
        thumb_btn.setFixedSize(52, 36)
        thumb_btn.setCursor(Qt.PointingHandCursor)
        scaled_icon = pixmap.scaled(50, 34, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        thumb_btn.setIcon(QIcon(scaled_icon))
        thumb_btn.setIconSize(QSize(48, 32))
        thumb_btn.setStyleSheet("""
            QPushButton {
                background: rgba(20, 20, 30, 0.9);
                border: 1px solid rgba(139, 92, 246, 0.3);
                border-radius: 6px;
                padding: 1px;
            }
            QPushButton:hover {
                border: 2px solid #C084FC;
            }
        """)
        thumb_btn.clicked.connect(lambda ch=False, p=pixmap: self.set_main_preview(p))
        self.thumb_layout.addWidget(thumb_btn)


class ModrinthBrowser(QWidget):
    item_selected = Signal(object)
    update_item_requested = Signal(object)
    install_local_requested = Signal()
    selection_cleared = Signal()
    
    def __init__(self, project_type, parent=None):
        super().__init__(parent, Qt.Widget)
        self.setWindowFlags(Qt.Widget)
        self.project_type = project_type
        self.lang = "tr"
        self.current_version = None
        self.current_loader = None
        self.current_category = None
        self.columns = 4
        self.cards = []
        self.selected_card = None
        self._search_thread = None
        self._search_threads = []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        
        # Search Row
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        
        self.search_input = QLineEdit()
        self.search_input.setFixedHeight(38)
        self.search_input.setPlaceholderText(f"{project_type.capitalize()} ara... (Yazmaya başlayın)")
        self.search_input.textChanged.connect(self.on_text_changed)
        top_row.addWidget(self.search_input, 1)
        layout.addLayout(top_row)
        
        # Category Filter Chips (Modpack only)
        if self.project_type == "modpack":
            chips_layout = QHBoxLayout()
            chips_layout.setSpacing(8)
            self.category_chips = []
            
            categories_def = [
                ("TÜMÜ", None),
                ("FPS / PERFORMANS", "optimization"),
                ("MACERA RPG", "adventure"),
                ("TEKNOLOJİ", "technology"),
                ("VANILLA+", "lightweight")
            ]
            
            for label, cat_id in categories_def:
                btn = QPushButton(label, self)
                btn.setWindowFlags(Qt.Widget)
                btn.setAttribute(Qt.WA_NativeWindow, False)
                btn.setFixedHeight(30)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda ch=False, c=cat_id, b=btn: self.on_category_chip_clicked(c, b))
                chips_layout.addWidget(btn)
                self.category_chips.append((cat_id, btn))
                
            chips_layout.addStretch()
            layout.addLayout(chips_layout)
            self.update_chip_styles()
            
        # Filters Row
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        self.sort_combo = QComboBox(self)
        self.sort_combo.setWindowFlags(Qt.Widget)
        self.sort_combo.setFixedHeight(36)
        self.sort_combo.addItem("Sıralama: İlgiliye Göre", "relevance")
        self.sort_combo.addItem("Sıralama: İndirme Sayısı", "downloads")
        self.sort_combo.addItem("Sıralama: En Yeni", "newest")
        self.sort_combo.addItem("Sıralama: Son Güncellenen", "updated")
        self.sort_combo.currentIndexChanged.connect(lambda x=None: self.search())
        filter_layout.addWidget(self.sort_combo)
        
        self.version_combo = QComboBox(self)
        self.version_combo.setWindowFlags(Qt.Widget)
        self.version_combo.setFixedHeight(36)
        self.version_combo.addItem("Sürüm: Otomatik (Aktif Profil)", "detect")
        self.version_combo.addItem("Sürüm: Tüm Sürümler", "all")
        for v in ["1.21.1", "1.21", "1.20.4", "1.20.1", "1.19.4", "1.19.2", "1.18.2", "1.16.5", "1.12.2"]:
            self.version_combo.addItem(f"Sürüm: {v}", v)
        self.version_combo.currentIndexChanged.connect(lambda x=None: self.search())
        filter_layout.addWidget(self.version_combo)
        
        self.loader_combo = QComboBox(self)
        self.loader_combo.setWindowFlags(Qt.Widget)
        self.loader_combo.setFixedHeight(36)
        self.loader_combo.addItem("Yükleyici: Otomatik (Aktif Profil)", "detect")
        self.loader_combo.addItem("Yükleyici: Tümü", "all")
        for l in ["Forge", "NeoForge", "Fabric", "Quilt"]:
            self.loader_combo.addItem(f"Yükleyici: {l}", l.lower())
        self.loader_combo.currentIndexChanged.connect(lambda x=None: self.search())
        filter_layout.addWidget(self.loader_combo)
        
        layout.addLayout(filter_layout)
        
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.search)
        
        # Grid Area
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.grid_container = QWidget(self.scroll)
        self.grid_container.setObjectName("GridContainer")
        self.grid_container.setWindowFlags(Qt.Widget)
        self.grid_container.setStyleSheet("#GridContainer { background: transparent; }")
        
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setVerticalSpacing(8)
        self.grid_layout.setHorizontalSpacing(8)
        self.grid_layout.setAlignment(Qt.AlignTop)
        for c in range(self.columns):
            self.grid_layout.setColumnStretch(c, 1)
        
        self.scroll.setWidget(self.grid_container)
        layout.addWidget(self.scroll, 1)

    def on_category_chip_clicked(self, cat_id, btn):
        if self.current_category == cat_id:
            return
        self.current_category = cat_id
        self.update_chip_styles()
        self.search()

    def update_chip_styles(self):
        if not hasattr(self, 'category_chips'): return
        for cat_id, btn in self.category_chips:
            if cat_id == self.current_category:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #7C3AED;
                        color: #FFFFFF;
                        font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                        font-size: 11px;
                        font-weight: bold;
                        border: 1px solid #5B21B6;
                        border-top: 1.5px solid #A78BFA;
                        border-left: 1px solid #8B5CF6;
                        border-right: 1px solid #6D28D9;
                        border-bottom: 2.5px solid #4C1D95;
                        border-radius: 4px;
                        padding: 4px 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #222228;
                        color: #94A3B8;
                        font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                        font-size: 11px;
                        font-weight: 600;
                        border: 1px solid #18181C;
                        border-top: 1px solid #33333C;
                        border-bottom: 2px solid #141418;
                        border-left: 1px solid #282830;
                        border-right: 1px solid #1A1A1E;
                        border-radius: 4px;
                        padding: 4px 12px;
                    }
                    QPushButton:hover {
                        background-color: #2A2A32;
                        color: #FFFFFF;
                        border-top: 1px solid #444452;
                    }
                """)

    def set_columns(self, cols):
        if self.columns != cols:
            self.columns = cols
            self.reflow_grid()

    def reflow_grid(self):
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)
        for c in range(max(4, self.columns)):
            self.grid_layout.setColumnStretch(c, 1 if c < self.columns else 0)
        for i, card in enumerate(self.cards):
            row = i // self.columns
            col = i % self.columns
            self.grid_layout.addWidget(card, row, col)

    def clear_selection(self):
        if self.selected_card:
            self.selected_card.set_selected(False)
            self.selected_card = None

    def on_card_clicked(self, data, card):
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        if self.selected_card and self.selected_card != card:
            self.selected_card.set_selected(False)
        card.set_selected(True)
        self.selected_card = card
        payload = dict(data)
        payload["filter_version"] = self.get_active_version()
        payload["filter_loader"] = self.get_active_loader()
        self.item_selected.emit(payload)

    def set_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        self.search_input.setPlaceholderText(
            f"Search {self.project_type}... (Start typing)" if en else f"{self.project_type.capitalize()} ara... (Yazmaya başlayın)"
        )
        if hasattr(self, "category_chips"):
            chip_map = {
                None: "All" if en else "Tümü",
                "optimization": "FPS / Performance" if en else "FPS / Performans",
                "adventure": "Adventure & RPG" if en else "Macera & RPG",
                "technology": "Technology" if en else "Teknoloji",
                "lightweight": "Vanilla+",
            }
            for cat_id, btn in self.category_chips:
                if cat_id in chip_map:
                    btn.setText(chip_map[cat_id])

        self.sort_combo.blockSignals(True)
        labels = ["Sort: Relevance", "Sort: Downloads", "Sort: Newest", "Sort: Recently Updated"] if en else ["Sıralama: İlgiliye Göre", "Sıralama: İndirme Sayısı", "Sıralama: En Yeni", "Sıralama: Son Güncellenen"]
        for i, txt in enumerate(labels):
            self.sort_combo.setItemText(i, txt)
        self.sort_combo.blockSignals(False)
        
        self.version_combo.blockSignals(True)
        self.version_combo.setItemText(0, "Version: Auto (Active Profile)" if en else "Sürüm: Otomatik (Aktif Profil)")
        self.version_combo.setItemText(1, "Version: All Versions" if en else "Sürüm: Tüm Sürümler")
        for i in range(2, self.version_combo.count()):
            v = self.version_combo.itemData(i)
            if v:
                self.version_combo.setItemText(i, f"Version: {v}" if en else f"Sürüm: {v}")
        self.version_combo.blockSignals(False)
        
        self.loader_combo.blockSignals(True)
        self.loader_combo.setItemText(0, "Loader: Auto (Active Profile)" if en else "Yükleyici: Otomatik (Aktif Profil)")
        self.loader_combo.setItemText(1, "Loader: All" if en else "Yükleyici: Tümü")
        loader_names = {"forge": "Forge", "neoforge": "NeoForge", "fabric": "Fabric", "quilt": "Quilt"}
        for i in range(2, self.loader_combo.count()):
            l_key = self.loader_combo.itemData(i)
            l_disp = loader_names.get(l_key, str(l_key).capitalize())
            if l_key:
                self.loader_combo.setItemText(i, f"Loader: {l_disp}" if en else f"Yükleyici: {l_disp}")
        self.loader_combo.blockSignals(False)

        for card in getattr(self, "cards", []):
            if hasattr(card, "set_language"):
                card.set_language(lang)

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
        if self.current_version != v or getattr(self, 'current_loader', None) != ldr or len(self.cards) == 0:
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
        
        loading_lbl = QLabel("Loading..." if getattr(self, "lang", "tr") == "en" else "Yükleniyor...", parent=self.grid_container)
        loading_lbl.setAlignment(Qt.AlignCenter)
        loading_lbl.setStyleSheet("color: #C084FC; font-size: 15px; font-weight: 700; margin-top: 40px;")
        self.grid_layout.addWidget(loading_lbl, 0, 0, 1, self.columns)
        
        if not hasattr(self, '_search_threads'):
            self._search_threads = []
            
        self._search_threads = [t for t in self._search_threads if t.isRunning()]
        
        thread = ModrinthSearchThread("", self.project_type, sort_index, 24, version, loader, self.current_category)
        thread.search_finished.connect(self.on_search_finished)
        self._search_threads.append(thread)
        self._search_thread = thread
        thread.start()

    def search(self):
        query = self.search_input.text().strip()
        if not query and not self.current_category:
            self.load_trending()
            return
            
        self.clear_grid()
        version = self.get_active_version()
        loader = self.get_active_loader()
        sort_index = self.sort_combo.currentData() if hasattr(self, 'sort_combo') else "relevance"
        
        loading_lbl = QLabel("Loading..." if getattr(self, "lang", "tr") == "en" else "Yükleniyor...", parent=self.grid_container)
        loading_lbl.setAlignment(Qt.AlignCenter)
        loading_lbl.setStyleSheet("color: #C084FC; font-size: 15px; font-weight: 700; margin-top: 40px;")
        self.grid_layout.addWidget(loading_lbl, 0, 0, 1, self.columns)
        
        if not hasattr(self, '_search_threads'):
            self._search_threads = []
            
        self._search_threads = [t for t in self._search_threads if t.isRunning()]
        
        thread = ModrinthSearchThread(query, self.project_type, sort_index, 24, version, loader, self.current_category)
        thread.search_finished.connect(self.on_search_finished)
        self._search_threads.append(thread)
        self._search_thread = thread
        thread.start()

    def on_search_finished(self, results):
        sender = self.sender()
        if hasattr(self, '_search_thread') and sender != self._search_thread:
            return
            
        self.clear_grid()
        if results is None or not results:
            en = getattr(self, "lang", "tr") == "en"
            if results is None:
                msg = "Failed to load items, check your internet connection." if en else "Modlar yüklenemedi, internet bağlantınızı kontrol edin."
            else:
                msg = "No results found." if en else "Sonuç bulunamadı."
            error_lbl = QLabel(msg, parent=self.grid_container)
            error_lbl.setAlignment(Qt.AlignCenter)
            error_lbl.setStyleSheet("color: #F87171; font-size: 15px; font-weight: 600; margin-top: 40px;")
            self.grid_layout.addWidget(error_lbl, 0, 0, 1, self.columns)
            return
        self.populate(results)

    def clear_grid(self):
        had_selection = self.selected_card is not None
        if self.selected_card:
            self.selected_card.set_selected(False)
            self.selected_card = None
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                w = item.widget()
                if hasattr(w, 'cleanup'):
                    w.cleanup()
                w.hide()
                w.deleteLater()
        self.cards = []
        if self.columns != 4:
            self.columns = 4
        for c in range(max(4, self.columns)):
            self.grid_layout.setColumnStretch(c, 1 if c < self.columns else 0)
        if had_selection:
            self.selection_cleared.emit()

    def populate(self, results):
        self.clear_grid()
        self.cards = []
        self.selected_card = None
        for c in range(max(4, self.columns)):
            self.grid_layout.setColumnStretch(c, 1 if c < self.columns else 0)
        for i, data in enumerate(results):
            card = CardWidget(data, parent=self.grid_container, lang=getattr(self, "lang", "tr"))
            card.clicked.connect(lambda d=data, c=card: self.on_card_clicked(d, c))
            if hasattr(card, 'update_clicked'):
                card.update_clicked.connect(self.update_item_requested.emit)
            self.cards.append(card)
            row = i // self.columns
            col = i % self.columns
            self.grid_layout.addWidget(card, row, col)


class EndermanInstallModal(QDialog):
    canceled = Signal()

    def __init__(self, pack_name="Modpack", parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowModality(Qt.WindowModal)
        self.setFixedSize(520, 230)
        self._is_cancelled = False

        self.lang = "tr"
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            self.lang = parent.settings.get("language", "tr")
        elif parent and hasattr(parent, "lang"):
            self.lang = parent.lang
        en = self.lang == "en"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        theme_key = "electric_amethyst"
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            theme_key = parent.settings.get("theme", "electric_amethyst")
        t = theme_manager.get_theme(theme_key)
        r, g, b = t["rgb"]
        primary = t["primary"]
        glow = t["glow"]
        prim_light = t["primary_light"]
        grad_start = t["gradient_start"]
        secondary = t.get("secondary", "#06B6D4")

        self.container = QFrame(self)
        self.container.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(18, 18, 26, 0.98);
                border: 2px solid {primary};
                border-radius: 16px;
            }}
        """)
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(24, 20, 24, 20)
        c_layout.setSpacing(12)

        # Header: Icon + Title
        header = QHBoxLayout()
        header.setSpacing(10)
        icon_lbl = QLabel("")
        icon_lbl.setVisible(False)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel("Enderman Modpack Installer" if en else "Enderman Modpack Yükleyici")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #F8FAFC; background: transparent; border: none;")
        title_col.addWidget(title_lbl)

        self.pack_lbl = QLabel(pack_name)
        self.pack_lbl.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {glow}; background: transparent; border: none;")
        title_col.addWidget(self.pack_lbl)
        header.addLayout(title_col, 1)

        self.counter_lbl = QLabel("Preparing..." if en else "Hazırlanıyor...")
        self.counter_lbl.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {glow}; background: rgba({r}, {g}, {b}, 0.15); border: 1px solid rgba({r}, {g}, {b}, 0.3); border-radius: 6px; padding: 3px 10px;")
        header.addWidget(self.counter_lbl)
        c_layout.addLayout(header)

        # Status text
        self.status_lbl = QLabel("Inspecting modpack archive..." if en else "Modpack arşivi inceleniyor...")
        self.status_lbl.setStyleSheet("font-size: 12px; color: #94A3B8; background: transparent; border: none;")
        self.status_lbl.setWordWrap(True)
        c_layout.addWidget(self.status_lbl)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgba(255, 255, 255, 0.07);
                border: 1px solid rgba({r}, {g}, {b}, 0.3);
                border-radius: 7px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {grad_start}, stop:0.7 {prim_light}, stop:1 {secondary});
                border-radius: 6px;
            }}
        """)
        self.progress_bar.setRange(0, 0)
        c_layout.addWidget(self.progress_bar)

        # Footer (Cancel button)
        footer = QHBoxLayout()
        footer.addStretch()
        self.cancel_btn = QPushButton("Cancel" if en else "İptal Et")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(239, 68, 68, 0.12);
                color: #F87171;
                border: 1px solid rgba(239, 68, 68, 0.35);
                border-radius: 8px;
                padding: 6px 18px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: rgba(239, 68, 68, 0.25);
                border-color: #EF4444;
                color: #FFFFFF;
            }
        """)
        self.cancel_btn.clicked.connect(self.on_cancel)
        footer.addWidget(self.cancel_btn)
        c_layout.addLayout(footer)

        layout.addWidget(self.container)

        if parent:
            geom = parent.geometry()
            self.move(geom.center() - self.rect().center())

    def on_cancel(self):
        if not self._is_cancelled:
            self._is_cancelled = True
            en = getattr(self, "lang", "tr") == "en"
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_click()
            except Exception:
                pass
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("Cancelling..." if en else "İptal Ediliyor...")
            self.status_lbl.setText("Cancelling operation, please wait..." if en else "İşlem iptal ediliyor, lütfen bekleyin...")
            self.canceled.emit()

    def set_status(self, text):
        self.status_lbl.setText(text)

    def set_progress(self, current, total):
        en = getattr(self, "lang", "tr") == "en"
        if total <= 0:
            self.progress_bar.setRange(0, 0)
            self.counter_lbl.setText("Preparing..." if en else "Hazırlanıyor...")
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            pct = int((current / total) * 100) if total > 0 else 0
            self.counter_lbl.setText(f"{current} / {total} Mods ({pct}%)" if en else f"{current} / {total} Mod (%{pct})")


class CustomProgressOverlay(QDialog):
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(500, 150)

        self.lang = "tr"
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            self.lang = parent.settings.get("language", "tr")
        elif parent and hasattr(parent, "lang"):
            self.lang = parent.lang
        en = self.lang == "en"
        
        theme_key = "electric_amethyst"
        if parent and hasattr(parent, "settings") and isinstance(parent.settings, dict):
            theme_key = parent.settings.get("theme", "electric_amethyst")
        t = theme_manager.get_theme(theme_key)
        r, g, b = t["rgb"]
        primary = t["primary"]
        glow = t["glow"]
        prim_light = t["primary_light"]
        grad_start = t["gradient_start"]
        secondary = t.get("secondary", "#06B6D4")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        container = QWidget()
        container.setStyleSheet(f"""
            QWidget {{
                background-color: rgba(20, 20, 25, 240);
                border: 2px solid {primary};
                border-radius: 15px;
            }}
        """)
        clayout = QVBoxLayout(container)
        clayout.setContentsMargins(20, 20, 20, 20)
        
        self.title_lbl = QLabel("Installing Mod..." if en else "Mod Kuruluyor...")
        self.title_lbl.setStyleSheet(f"color: {glow}; font-size: 22px; font-weight: bold; border: none; background: transparent;")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        clayout.addWidget(self.title_lbl)
        
        self.desc_lbl = QLabel(f"Downloading {filename}..." if en else f"{filename} indiriliyor...")
        self.desc_lbl.setStyleSheet("color: #DDDDDD; font-size: 14px; border: none; background: transparent;")
        self.desc_lbl.setAlignment(Qt.AlignCenter)
        clayout.addWidget(self.desc_lbl)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid rgba({r}, {g}, {b}, 0.35);
                border-radius: 5px;
                text-align: center;
                color: white;
                font-weight: bold;
                background: #111;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {grad_start}, stop:0.7 {prim_light}, stop:1 {secondary});
                border-radius: 3px;
            }}
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


def load_custom_fonts(base_dir=None):
    """Loads bundled Minecraft pixel fonts (Minecraft Five, Minecraft) into QFontDatabase."""
    try:
        if not base_dir:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
        fonts_dir = os.path.join(base_dir, "assets", "fonts")
        if os.path.exists(fonts_dir):
            for fname in os.listdir(fonts_dir):
                if fname.lower().endswith((".ttf", ".otf")):
                    QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))
    except Exception:
        pass


class VegaLauncher(QMainWindow):
    def __init__(self, data_dir=None):
        super().__init__()
        self.setWindowTitle(f"Vega Launcher — by {__author__}")
        self.resize(1440, 810)
        self.center_on_screen()
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            
        load_custom_fonts(self.base_dir)
        self.setWindowIcon(QIcon(os.path.join(self.base_dir, "enderman_icon.ico")))
        self._active_threads = []
        self.active_profile_version = None
        self.active_profile_loader = None
        self._is_closing = False
        self._is_game_running = False

        try:
            with open(os.path.join(self.base_dir, "style.qss"), "r", encoding="utf-8") as f:
                self._base_qss = f.read()
        except Exception:
            self._base_qss = ""
        
        self.data_dir = data_dir if data_dir else os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), ".vega_launcher")
        os.makedirs(self.data_dir, exist_ok=True)
        self.profiles_dir = os.path.join(self.data_dir, "profiles")
        self.config_file = os.path.join(self.data_dir, "launcher_config.json")
        self.profiles = {}
        self.ms_login = {}
        self.settings = dict(DEFAULT_SETTINGS)
        
        self.mc_dir = os.path.join(os.getenv("APPDATA", ""), ".minecraft")
        self.launch_pipeline = GameLaunchPipeline(mc_dir=self.mc_dir)
        self.auth_vault = DEFAULT_AUTH_VAULT
        self.profile_store = ProfileAndConfigStore(
            data_dir=self.data_dir,
            config_file=self.config_file,
            profiles_dir=self.profiles_dir,
            mc_dir=self.mc_dir,
        )
        
        self.sound_mgr = SoundManager.get_instance()
        
        self.ensure_directories()
        self.load_config()
        
        if hasattr(self, "sound_mgr"):
            self.sound_mgr.set_enabled(self.settings.get("sound_enabled", True))
            self.sound_mgr.set_volume(self.settings.get("sound_volume", 70))

        self.init_ui()
        self.apply_theme(self.settings.get("theme", "electric_amethyst"))
        self.apply_window_size_setting(initial=True)
        self.apply_language(self.settings.get("language", "tr"))

    def _get_slider_qss(self, theme_key):
        t = theme_manager.get_theme(theme_key)
        prim = t["primary"]
        prim_light = t["primary_light"]
        grad_start = t["gradient_start"]
        return f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: rgba(255, 255, 255, 0.15);
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {grad_start}, stop:1 {prim_light});
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: 2px solid {prim};
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }}
        """

    def apply_theme(self, theme_key=None):
        if not theme_key:
            theme_key = (getattr(self, "settings", {}) or {}).get("theme", "electric_amethyst")
        self.settings["theme"] = theme_key

        base_qss = getattr(self, "_base_qss", "")
        themed_qss = theme_manager.generate_theme_qss(base_qss, theme_key)

        custom_bg = (getattr(self, "settings", {}) or {}).get("custom_bg", "")
        if custom_bg in ("none", "solid"):
            bg_path = ""
        elif custom_bg and os.path.exists(custom_bg):
            bg_path = custom_bg
        else:
            default_bg = os.path.join(self.base_dir, "bg.jpg")
            bg_path = default_bg if os.path.exists(default_bg) else ""

        if bg_path and os.path.exists(bg_path):
            bg_path_fwd = bg_path.replace("\\", "/")
            extra_css = f"\nQMainWindow {{ background-image: url('{bg_path_fwd}'); background-position: center; }}"
            themed_qss += extra_css
        else:
            themed_qss += "\nQMainWindow { background-color: #141416; }"

        self.setStyleSheet(themed_qss)

        t_data = theme_manager.get_theme(theme_key)
        glow = t_data.get("glow", "#C084FC")

        if hasattr(self, "combo_theme"):
            self.combo_theme.blockSignals(True)
            idx = self.combo_theme.findData(theme_key)
            if idx >= 0 and self.combo_theme.currentIndex() != idx:
                self.combo_theme.setCurrentIndex(idx)
            self.combo_theme.blockSignals(False)

        card_base = getattr(self, "_settings_card_base_qss", "")
        if card_base:
            card_themed_qss = theme_manager.generate_theme_qss(card_base, theme_key)
            for card in self.findChildren(QFrame, "SettingsCard"):
                try:
                    card.setStyleSheet(card_themed_qss)
                except Exception:
                    pass

        if hasattr(self, "slider_particle_opacity"):
            self.slider_particle_opacity.setStyleSheet(self._get_slider_qss(theme_key))
        if hasattr(self, "slider_volume"):
            self.slider_volume.setStyleSheet(self._get_slider_qss(theme_key))
        if hasattr(self, "lbl_part_opacity_val"):
            self.lbl_part_opacity_val.setStyleSheet(f"color: {glow}; font-weight: 700; font-size: 12px; min-width: 38px;")
        if hasattr(self, "lbl_vol_val"):
            self.lbl_vol_val.setStyleSheet(f"color: {glow}; font-weight: 700; font-size: 12px; min-width: 38px;")

        if hasattr(self, "particle_overlay") and self.particle_overlay:
            self.particle_overlay.set_palette(t_data.get("particles", []))

        if hasattr(self, "hero_card") and hasattr(self, "get_selected_profile"):
            pid, pdata = self.get_selected_profile()
            self._update_hero_card_banner(pdata)

        if hasattr(self, "nav_bar") and self.nav_bar and hasattr(self.nav_bar, "set_theme"):
            self.nav_bar.set_theme(theme_key)

        if hasattr(self, "action_bar") and self.action_bar and hasattr(self.action_bar, "set_theme"):
            self.action_bar.set_theme(theme_key)

        if hasattr(self, "server_page") and self.server_page and hasattr(self.server_page, "set_theme"):
            self.server_page.set_theme(theme_key)

        if hasattr(self, "installed_mods_panel") and self.installed_mods_panel and hasattr(self.installed_mods_panel, "set_theme"):
            self.installed_mods_panel.set_theme(theme_key)

        from card_widget import CardWidget
        for card in self.findChildren(CardWidget):
            try:
                card.set_theme(theme_key)
            except Exception:
                pass

        if hasattr(self, "profile_list"):
            for i in range(self.profile_list.count()):
                item = self.profile_list.item(i)
                w = self.profile_list.itemWidget(item)
                if w and hasattr(w, "set_theme"):
                    w.set_theme(theme_key)

        for lbl in self.findChildren(QLabel, "SettingsCardHeader"):
            try:
                lbl.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {glow}; background: transparent; border: none;")
            except Exception:
                pass

    def apply_background(self):
        self.apply_theme(self.settings.get("theme", "electric_amethyst"))

    def apply_window_size_setting(self, mode=None, initial=False):
        if mode is None:
            mode = (getattr(self, "settings", {}) or {}).get("window_size", "auto")
        size_map = {
            "1280x720": (1280, 720),
            "1350x755": (1350, 755),
            "1440x810": (1440, 810),
        }
        if mode == "maximized":
            self.showMaximized()
            return
        if self.isMaximized() and not initial:
            self.showNormal()
        if mode in size_map:
            w, h = size_map[mode]
            self.resize(w, h)
        elif mode == "remember":
            w = int(self.settings.get("last_width", 1350) or 1350)
            h = int(self.settings.get("last_height", 755) or 755)
            self.resize(max(960, w), max(600, h))
        else:
            screen = QApplication.primaryScreen()
            if screen:
                avail = screen.availableGeometry()
                if avail.width() > 1000 and avail.height() > 600:
                    target_w = min(1440, max(1024, int(avail.width() * 0.92)))
                    target_h = min(810, max(600, int(avail.height() * 0.92)))
                    self.resize(target_w, target_h)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            geo = self.frameGeometry()
            geo.moveCenter(avail.center())
            self.move(geo.topLeft())

    def center_on_screen(self):
        self.apply_window_size_setting(initial=True)

    def _get_profile_store(self) -> ProfileAndConfigStore:
        store = getattr(self, "profile_store", None)
        cfg_file = getattr(self, "config_file", None)
        prof_dir = getattr(self, "profiles_dir", None)
        if store is None or (cfg_file and store.config_file != cfg_file) or (prof_dir and store.profiles_dir != prof_dir):
            store = ProfileAndConfigStore(
                data_dir=getattr(self, "data_dir", None),
                config_file=cfg_file,
                profiles_dir=prof_dir,
                mc_dir=getattr(self, "mc_dir", None),
            )
            self.profile_store = store
        return store

    def ensure_directories(self):
        self._get_profile_store().ensure_directories(getattr(self, "settings", {}))

    def load_config(self):
        if __author__ != "Arcturus":
            sys.exit(1)
        self.profiles, self.ms_login, self.settings = self._get_profile_store().load()

    def save_config(self):
        self._get_profile_store().save(
            getattr(self, "profiles", {}),
            getattr(self, "ms_login", {}),
            getattr(self, "settings", {}),
            sync_standard=False,
        )
        try:
            self.sync_with_standard_launchers()
        except Exception as e:
            print(f"[Config] sync_with_standard_launchers error: {e}")

    def sync_with_standard_launchers(self):
        self._get_profile_store().sync_with_standard_launchers(
            getattr(self, "profiles", {}),
            getattr(self, "mc_dir", None),
        )

    def update_profile_runtime(self, profile_id, version, loader):
        if profile_id in getattr(self, "profiles", {}):
            self.profiles[profile_id]["version"] = version
            self.profiles[profile_id]["loader"] = str(loader).lower()
            self.save_config()
            self.on_profile_selected()


    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.nav_bar = NavBar()
        self.nav_bar.nav_clicked.connect(self.switch_tab)
        self.nav_bar.game_changed.connect(self.on_game_changed)
        self.nav_bar.login_clicked.connect(self._settings_login_microsoft)
        self.nav_bar.logout_clicked.connect(self._settings_logout_microsoft)
        if hasattr(self, "ms_login") and self.ms_login:
            self.nav_bar.update_user(self.ms_login.get("name"), bool(self.ms_login.get("name")))
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
        profile_layout.setContentsMargins(24, 20, 24, 16)
        profile_layout.setSpacing(14)

        # --- HERO VITRIN SHOWCASE ---
        self.hero_card = QFrame()
        self.hero_card.setObjectName("HeroCard")
        self.hero_card.setStyleSheet("""
            QFrame#HeroCard {
                background-color: #1A1A1E;
                border: 1px solid #282830;
                border-top: 1px solid #34343E;
                border-bottom: 2px solid #141416;
                border-radius: 6px;
            }
        """)
        hero_layout = QHBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(20, 16, 20, 16)
        hero_layout.setSpacing(16)

        self.hero_icon_box = QFrame()
        self.hero_icon_box.setFixedSize(62, 62)
        self.hero_icon_box.setCursor(Qt.PointingHandCursor)
        self.hero_icon_box.setToolTip("Profili Düzenle / Simgeyi Değiştir")
        self.hero_icon_box.setStyleSheet("QFrame { background: rgba(139, 92, 246, 0.18); border: 1px solid rgba(168, 85, 247, 0.45); border-radius: 12px; } QFrame:hover { background: rgba(139, 92, 246, 0.32); border-color: #C084FC; }")
        self.hero_icon_box.mousePressEvent = lambda e: self.edit_profile()
        hero_icon_lay = QVBoxLayout(self.hero_icon_box)
        hero_icon_lay.setContentsMargins(0, 0, 0, 0)
        self.hero_icon_lbl = QLabel("")
        self.hero_icon_lbl.setAlignment(Qt.AlignCenter)
        self.hero_icon_lbl.setStyleSheet("font-size: 30px; font-weight: bold; color: #EDE9FE; background: transparent; font-family: 'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', 'Segoe UI', sans-serif;")
        hero_icon_lay.addWidget(self.hero_icon_lbl)
        hero_layout.addWidget(self.hero_icon_box)

        hero_text_lay = QVBoxLayout()
        hero_text_lay.setSpacing(6)

        self.hero_eyebrow = QLabel("SEÇİLİ PROFİL")
        self.hero_eyebrow.setStyleSheet("font-family: 'Minecraft Five', 'Segoe UI', sans-serif; font-size: 11px; font-weight: 700; color: #C084FC; letter-spacing: 1px; background: transparent;")
        self.hero_eyebrow.setVisible(True)
        hero_text_lay.addWidget(self.hero_eyebrow)

        self.hero_title = QLabel("Profil Seçilmedi")
        self.hero_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #F8FAFC; background: transparent;")
        hero_text_lay.addWidget(self.hero_title)

        hero_badges_lay = QHBoxLayout()
        hero_badges_lay.setSpacing(6)
        hero_badges_lay.setAlignment(Qt.AlignVCenter)

        self.hero_badge_ver = QLabel("v --")
        self.hero_badge_ver.setStyleSheet("background: rgba(139, 92, 246, 0.16); color: #C084FC; border: 1px solid rgba(139, 92, 246, 0.28); border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700;")

        self.hero_badge_sep1 = QLabel("·")
        self.hero_badge_sep1.setStyleSheet("color: #475569; font-weight: bold; font-size: 13px; background: transparent;")

        self.hero_badge_loader = QLabel("Vanilla")
        self.hero_badge_loader.setStyleSheet("color: #CBD5E1; font-size: 12px; font-weight: 600; background: transparent;")

        self.hero_badge_sep2 = QLabel("·")
        self.hero_badge_sep2.setStyleSheet("color: #475569; font-weight: bold; font-size: 13px; background: transparent;")

        self.hero_badge_ram = QLabel("4096 MB")
        self.hero_badge_ram.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 500; background: transparent;")

        self.hero_badge_sep3 = QLabel("·")
        self.hero_badge_sep3.setStyleSheet("color: #475569; font-weight: bold; font-size: 13px; background: transparent;")

        self.hero_badge_play = QLabel("0s")
        self.hero_badge_play.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 500; background: transparent;")

        hero_badges_lay.addWidget(self.hero_badge_ver)
        hero_badges_lay.addWidget(self.hero_badge_sep1)
        hero_badges_lay.addWidget(self.hero_badge_loader)
        hero_badges_lay.addWidget(self.hero_badge_sep2)
        hero_badges_lay.addWidget(self.hero_badge_ram)
        hero_badges_lay.addWidget(self.hero_badge_sep3)
        hero_badges_lay.addWidget(self.hero_badge_play)
        hero_badges_lay.addStretch()

        hero_text_lay.addLayout(hero_badges_lay)
        hero_layout.addLayout(hero_text_lay, 1)

        hero_actions_lay = QVBoxLayout()
        hero_actions_lay.setSpacing(6)
        hero_actions_lay.setAlignment(Qt.AlignVCenter)

        btn_ghost_style = """
            QPushButton {
                background-color: #222228;
                color: #E4E4E7;
                border: 1px solid #18181C;
                border-top: 1.5px solid #3E3E48;
                border-bottom: 2.5px solid #141416;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2A2A32;
                border-top: 1.5px solid #525260;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                border-top: 2px solid #141416;
                border-bottom: 1px solid #3E3E48;
                padding-top: 7px;
            }
            QPushButton:disabled {
                background-color: #1A1A1E;
                color: #475569;
                border: 1px solid #222226;
            }
        """
        self.hero_edit_btn = QPushButton("Profili Düzenle")
        self.hero_edit_btn.setCursor(Qt.PointingHandCursor)
        self.hero_edit_btn.setStyleSheet(btn_ghost_style)
        self.hero_edit_btn.clicked.connect(self.edit_profile)

        self.hero_shortcut_btn = QPushButton("Masaüstü Kısayolu")
        self.hero_shortcut_btn.setCursor(Qt.PointingHandCursor)
        self.hero_shortcut_btn.setStyleSheet(btn_ghost_style)
        self.hero_shortcut_btn.clicked.connect(self.create_profile_shortcut)

        self.hero_open_folder = QPushButton("Klasörü Aç")
        self.hero_open_folder.setCursor(Qt.PointingHandCursor)
        self.hero_open_folder.setStyleSheet(btn_ghost_style)
        self.hero_open_folder.clicked.connect(self.open_profile_folder)

        hero_actions_lay.addWidget(self.hero_edit_btn)
        hero_actions_lay.addWidget(self.hero_shortcut_btn)
        hero_actions_lay.addWidget(self.hero_open_folder)
        hero_layout.addLayout(hero_actions_lay)

        profile_layout.addWidget(self.hero_card)

        # PROFiL EKLE TUŞLARI
        btn_layout = QHBoxLayout()
        self.add_profile_btn = QPushButton("+ YENİ PROFİL")
        self.add_profile_btn.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #5B21B6;
                border-top: 1.5px solid #A78BFA;
                border-left: 1px solid #8B5CF6;
                border-right: 1px solid #6D28D9;
                border-bottom: 3.5px solid #4C1D95;
                border-radius: 4px;
                padding: 7px 16px;
            }
            QPushButton:hover {
                background-color: #8B5CF6;
                border-top: 1.5px solid #C084FC;
            }
            QPushButton:pressed {
                border-top: 2.5px solid #4C1D95;
                border-bottom: 1px solid #A78BFA;
                padding-top: 9px;
            }
        """)
        self.add_profile_btn.setCursor(Qt.PointingHandCursor)
        self.add_profile_btn.clicked.connect(self.add_profile)
        btn_layout.addWidget(self.add_profile_btn)

        self.install_file_btn = QPushButton("ZİP'TEN KUR")
        self.install_file_btn.setStyleSheet("""
            QPushButton {
                background-color: #222228;
                color: #E4E4E7;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #18181C;
                border-top: 1.5px solid #3E3E48;
                border-left: 1px solid #282830;
                border-right: 1px solid #1A1A1E;
                border-bottom: 3.5px solid #141416;
                border-radius: 4px;
                padding: 7px 16px;
            }
            QPushButton:hover {
                background-color: #2A2A32;
                border-top: 1.5px solid #525260;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                border-top: 2.5px solid #141416;
                border-bottom: 1px solid #3E3E48;
                padding-top: 9px;
            }
        """)
        self.install_file_btn.setCursor(Qt.PointingHandCursor)
        self.install_file_btn.clicked.connect(self.install_from_file)
        btn_layout.addWidget(self.install_file_btn)
        profile_layout.addLayout(btn_layout)

        # ARAMA ÇUBUĞU
        self.profile_search = QLineEdit()
        self.profile_search.setPlaceholderText("Profillerde ara...")
        self.profile_search.setStyleSheet("""
            QLineEdit {
                background-color: #18181B;
                color: #F8FAFC;
                border: 1px solid #282830;
                border-radius: 4px;
                padding: 7px 12px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #8B5CF6;
            }
        """)
        self.profile_search.textChanged.connect(self.filter_profiles)
        profile_layout.addWidget(self.profile_search)

        from PySide6.QtGui import QShortcut, QKeySequence

        self.profile_list = QListWidget()
        self.profile_list.setObjectName("ProfileList")
        self.profile_list.itemClicked.connect(self._on_profile_item_clicked)
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

        profile_layout.addWidget(self.profile_list, 1)
        
        self.pack_browser = ModrinthBrowser("modpack", parent=self.stack)
        self.pack_browser.item_selected.connect(self.on_browser_item_selected)
        self.pack_browser.update_item_requested.connect(self.on_browser_update_requested)
        self.pack_browser.install_local_requested.connect(self.install_from_file)
        self.pack_browser.selection_cleared.connect(self.on_detail_panel_closed)
        
        self.mod_browser = ModrinthBrowser("mod", parent=self.stack)
        self.mod_browser.item_selected.connect(self.on_browser_item_selected)
        self.mod_browser.selection_cleared.connect(self.on_detail_panel_closed)
        
        self.shader_browser = ModrinthBrowser("shader", parent=self.stack)
        self.shader_browser.item_selected.connect(self.on_browser_item_selected)
        self.shader_browser.selection_cleared.connect(self.on_detail_panel_closed)
        
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
        self.bed_desc = QLabel("Windows 10/11 için optimize edilmiş, çapraz platform destekli sürüm.")
        self.bed_desc.setStyleSheet("font-size: 16px; color: #CCCCCC; margin-bottom: 40px;")
        self.bed_desc.setAlignment(Qt.AlignCenter)
        self.bed_btn = QPushButton("BEDROCK OYNA")
        self.bed_btn.setCursor(Qt.PointingHandCursor)
        self.bed_btn.setStyleSheet("""
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
        self.bed_btn.clicked.connect(lambda x=None: os.system("explorer.exe shell:AppsFolder\\Microsoft.MinecraftUWP_8wekyb3d8bbwe!App"))
        bed_layout.addStretch()
        bed_layout.addWidget(bed_lbl)
        bed_layout.addWidget(self.bed_desc)
        bed_layout.addWidget(self.bed_btn, alignment=Qt.AlignCenter)
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
        self.dun_desc = QLabel("Zindanları keşfet, efsanevi silahlar kuşan ve Arch-Illager'ı yen!")
        self.dun_desc.setStyleSheet("font-size: 16px; color: #DDDDDD; margin-bottom: 20px;")
        self.dun_desc.setAlignment(Qt.AlignCenter)
        
        self.dun_btn = QPushButton("ZİNDANA GİR")
        self.dun_btn.setCursor(Qt.PointingHandCursor)
        self.dun_btn.setStyleSheet("""
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
        self.dun_btn.clicked.connect(lambda x=None: os.system("explorer.exe shell:AppsFolder\\Microsoft.Lovika_8wekyb3d8bbwe!Game"))
        
        self.dun_mods_btn = QPushButton("Kurulu Modlar")
        self.dun_mods_btn.setCursor(Qt.PointingHandCursor)
        self.dun_mods_btn.setStyleSheet("""
            QPushButton {
                background: #333; color: white; font-size: 16px; font-weight: bold; border-radius: 8px; padding: 15px; border: 1px solid #555;
            }
            QPushButton:hover { background: #444; }
        """)
        self.dun_mods_btn.clicked.connect(self.show_dungeons_mods)
        
        h_dun = QHBoxLayout()
        h_dun.addStretch()
        h_dun.addWidget(self.dun_btn, 1)
        h_dun.addWidget(self.dun_mods_btn, 0)
        h_dun.addStretch()
        
        dun_top_layout.addWidget(dun_lbl)
        dun_top_layout.addWidget(self.dun_desc)
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
        
        self.server_page = ServerWidget(self)
        self.server_widget = self.server_page
        self.stack.addWidget(self.server_page)

        self.settings_page = self._build_settings_page()
        self.stack.addWidget(self.settings_page)
        
        self.splitter.addWidget(self.stack)
        
        self.right_stack = QStackedWidget(self.splitter)
        self.right_stack.setWindowFlags(Qt.Widget)
        
        self.detail_panel = DetailPanel(parent=self.right_stack)
        self.detail_panel.download_requested.connect(self.download_project)
        self.detail_panel.drawer_closed.connect(self.on_detail_panel_closed)
        self.right_stack.addWidget(self.detail_panel)
        
        self.installed_mods_panel = InstalledModsPanel()
        self.right_stack.addWidget(self.installed_mods_panel)
        
        self.splitter.addWidget(self.right_stack)
        self.splitter.setSizes([620, 600])
        self.right_stack.hide()
        
        content_layout.addWidget(self.splitter)
        
        self.action_bar = ActionBar()
        self.action_bar.play_clicked.connect(self.on_play)
        self.action_bar.folder_btn.clicked.connect(lambda x=None: os.startfile(self.mc_dir))
        content_layout.addWidget(self.action_bar)
        
        main_layout.addLayout(content_layout)
        
        self.nav_bar.on_nav_click("home", play_sound=False)
        self.on_profile_selected()
        self.detail_panel.hide()
        
        # Ambient Particle Canvas Overlay
        self.particle_overlay = ParticleOverlay(self)
        self.particle_overlay.set_enabled(self.settings.get("particles_enabled", False))
        t_key = self.settings.get("theme", "electric_amethyst")
        self.particle_overlay.set_palette(theme_manager.get_theme(t_key).get("particles", []))
        self.particle_overlay.set_preset(self.settings.get("particle_preset", "portal"))
        self.particle_overlay.set_opacity_percent(self.settings.get("particle_opacity", 50))
        self.particle_overlay.resize(self.size())

        # Durum çubuğu
        self.statusBar().setStyleSheet("color: #888; background: rgba(15,15,20,0.9); border-top: 1px solid #333;")
        self.statusBar().showMessage("Vega Launcher hazır — Profil seçip OYNA'ya basın!")
        self.start_update_checker()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'particle_overlay') and self.particle_overlay:
            self.particle_overlay.resize(self.size())

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, 'particle_overlay') and self.particle_overlay:
            if self.isMinimized() or not self.isVisible() or getattr(self, '_is_game_running', False):
                self.particle_overlay.pause()
            else:
                self.particle_overlay.resume()

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, 'particle_overlay') and self.particle_overlay:
            self.particle_overlay.pause()

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'particle_overlay') and self.particle_overlay:
            if not self.isMinimized() and not getattr(self, '_is_game_running', False):
                self.particle_overlay.resume()
        if not getattr(self, '_has_played_startup_sound', False):
            self._has_played_startup_sound = True
            if hasattr(self, 'sound_mgr') and self.sound_mgr and self.sound_mgr.is_enabled():
                QTimer.singleShot(150, self.sound_mgr.play_door_open)

    def _build_settings_page(self):
        from PySide6.QtWidgets import QGridLayout, QFileDialog, QFrame
        page = QWidget()
        outer_layout = QVBoxLayout(page)
        outer_layout.setContentsMargins(24, 20, 24, 20)
        outer_layout.setSpacing(14)

        self.lbl_settings_title = QLabel("UYGULAMA AYARLARI")
        self.lbl_settings_title.setStyleSheet("font-family: 'Minecraft Five', 'Segoe UI', sans-serif; font-size: 16px; font-weight: bold; color: #F8FAFC; letter-spacing: 0.5px; background: transparent;")
        outer_layout.addWidget(self.lbl_settings_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        card_qss = """
            QFrame#SettingsCard {
                background-color: #1A1A1E;
                border: 1px solid #282830;
                border-radius: 8px;
            }
        """
        input_qss = """
            QComboBox, QSpinBox, QLineEdit {
                background-color: #141416;
                color: #F8FAFC;
                padding: 8px 12px;
                border-radius: 4px;
                border: 1px solid #282830;
                font-size: 13px;
            }
            QComboBox:hover, QSpinBox:hover, QLineEdit:focus {
                border: 1px solid #A855F7;
                background-color: #18181D;
            }
        """
        btn_qss = """
            QPushButton {
                background-color: #222228;
                color: #E4E4E7;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                border: 1px solid #18181C;
                border-top: 1.5px solid #3E3E48;
                border-bottom: 3px solid #18181C;
                border-radius: 4px;
                padding: 8px 14px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #2A2A32;
                border-top: 1.5px solid #4C4C58;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                background-color: #18181C;
                border-top: 3px solid #141416;
                border-bottom: 1px solid #141416;
                padding-top: 10px;
                padding-bottom: 6px;
            }
        """
        chk_icon = os.path.join(self.base_dir, "assets", "check.png").replace("\\", "/")
        chk_qss = f"""
            QCheckBox {{
                color: #F8FAFC;
                font-size: 13px;
                font-weight: 600;
                spacing: 8px;
                background: transparent;
            }}
            QCheckBox:hover {{
                color: #FFFFFF;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid rgba(255, 255, 255, 0.25);
                background: rgba(26, 26, 38, 0.9);
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid #A855F7;
                background: rgba(139, 92, 246, 0.15);
            }}
            QCheckBox::indicator:checked {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7C3AED, stop:1 #A855F7);
                border: 1px solid #C084FC;
                image: url('{chk_icon}');
            }}
            QCheckBox::indicator:checked:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8B5CF6, stop:1 #C084FC);
                border: 1px solid #C084FC;
            }}
        """

        self._settings_card_base_qss = card_qss + input_qss + btn_qss + chk_qss

        def _make_settings_card(title_text):
            card = QFrame()
            card.setObjectName("SettingsCard")
            theme_key = getattr(self, "settings", {}).get("theme", "electric_amethyst")
            t_data = theme_manager.get_theme(theme_key)
            card_themed_qss = theme_manager.generate_theme_qss(self._settings_card_base_qss, theme_key)
            card.setStyleSheet(card_themed_qss)
            lay = QVBoxLayout(card)
            lay.setContentsMargins(18, 16, 18, 16)
            lay.setSpacing(10)
            hdr = QLabel(title_text)
            hdr.setObjectName("SettingsCardHeader")
            hdr.setStyleSheet(f"font-family: 'Minecraft Five', 'Segoe UI', sans-serif; font-size: 13px; font-weight: bold; color: {t_data.get('glow', '#C084FC')}; letter-spacing: 0.5px; background: transparent; border: none;")
            lay.addWidget(hdr)
            return card, lay, hdr

        # --- KART 1: Genel, Dil & Pencere Boyutu ---
        card_gen, lay_gen, self.lbl_card_gen_hdr = _make_settings_card("GENEL, DİL & PENCERE")

        self.lbl_lang_field = QLabel("Arayüz Dili / Language:")
        self.lbl_lang_field.setStyleSheet("color: #CCCCCC; font-size: 13px; background: transparent;")
        self.combo_lang = QComboBox()
        self.combo_lang.addItem("Türkçe (TR)", "tr")
        self.combo_lang.addItem("English (EN)", "en")
        idx_lang = self.combo_lang.findData(self.settings.get("language", "tr"))
        if idx_lang >= 0:
            self.combo_lang.setCurrentIndex(idx_lang)
        self.combo_lang.currentIndexChanged.connect(self._on_settings_changed)
        lay_gen.addWidget(self.lbl_lang_field)
        lay_gen.addWidget(self.combo_lang)

        self.lbl_winsize_field = QLabel("Açılış & Pencere Boyutu:")
        self.lbl_winsize_field.setStyleSheet("color: #CCCCCC; font-size: 13px; background: transparent;")
        self.combo_winsize = QComboBox()
        self.combo_winsize.addItem("Otomatik (Ekrana Göre)", "auto")
        self.combo_winsize.addItem("Kompakt (1280 x 720)", "1280x720")
        self.combo_winsize.addItem("Yarı Ekran / Orta (1350 x 755)", "1350x755")
        self.combo_winsize.addItem("Geniş (1440 x 810)", "1440x810")
        self.combo_winsize.addItem("Tam Ekran (Maksimize)", "maximized")
        self.combo_winsize.addItem("Son Boyutu Hatırla", "remember")
        idx_ws = self.combo_winsize.findData(self.settings.get("window_size", "auto"))
        if idx_ws >= 0:
            self.combo_winsize.setCurrentIndex(idx_ws)
        self.combo_winsize.currentIndexChanged.connect(self._on_winsize_changed)
        lay_gen.addWidget(self.lbl_winsize_field)
        lay_gen.addWidget(self.combo_winsize)

        self.lbl_onlaunch_field = QLabel("Oyun Başladığında Başlatıcı:")
        self.lbl_onlaunch_field.setStyleSheet("color: #CCCCCC; font-size: 13px; background: transparent;")
        self.combo_onlaunch = QComboBox()
        self.combo_onlaunch.addItem("Simge Durumuna Küçült", "minimize")
        self.combo_onlaunch.addItem("Açık Tut", "keep")
        self.combo_onlaunch.addItem("Tamamen Gizle (Oyun Kapanınca Aç)", "hide")
        idx_ol = self.combo_onlaunch.findData(self.settings.get("on_launch", "minimize"))
        if idx_ol >= 0:
            self.combo_onlaunch.setCurrentIndex(idx_ol)
        self.combo_onlaunch.currentIndexChanged.connect(self._on_settings_changed)
        lay_gen.addWidget(self.lbl_onlaunch_field)
        lay_gen.addWidget(self.combo_onlaunch)
        lay_gen.addStretch()

        # --- KART 2: Oyun & Performans (Java / RAM) ---
        card_perf, lay_perf, self.lbl_card_perf_hdr = _make_settings_card("OYUN & PERFORMANS (JAVA / RAM)")

        self.lbl_defram_field = QLabel("Varsayılan RAM Miktarı (MB):")
        self.lbl_defram_field.setStyleSheet("color: #CCCCCC; font-size: 13px; background: transparent;")
        ram_row = QHBoxLayout()
        self.spin_default_ram = QSpinBox()
        self.spin_default_ram.setRange(1024, 32768)
        self.spin_default_ram.setSingleStep(512)
        self.spin_default_ram.setValue(int(self.settings.get("default_ram", 4096) or 4096))
        self.spin_default_ram.valueChanged.connect(self._on_settings_changed)
        self.btn_apply_ram_all = QPushButton("TÜM PROFİLLERE UYGULA")
        self.btn_apply_ram_all.setCursor(Qt.PointingHandCursor)
        self.btn_apply_ram_all.clicked.connect(lambda checked=False: self._apply_ram_to_all_profiles())
        ram_row.addWidget(self.spin_default_ram, 1)
        ram_row.addWidget(self.btn_apply_ram_all)
        lay_perf.addWidget(self.lbl_defram_field)
        lay_perf.addLayout(ram_row)

        self.lbl_java_field = QLabel("Özel Java Yolu (Boş = Otomatik):")
        self.lbl_java_field.setStyleSheet("color: #CCCCCC; font-size: 13px; background: transparent;")
        java_row = QHBoxLayout()
        self.line_java_path = QLineEdit(self.settings.get("java_path", ""))
        self.line_java_path.setPlaceholderText("Otomatik (Varsayılan Java)")
        self.line_java_path.textChanged.connect(self._on_settings_changed)
        self.btn_browse_java = QPushButton("Gözat...")
        self.btn_browse_java.setCursor(Qt.PointingHandCursor)
        self.btn_browse_java.clicked.connect(lambda checked=False: self._browse_java_path())
        self.btn_reset_java = QPushButton("Sıfırla")
        self.btn_reset_java.setCursor(Qt.PointingHandCursor)
        self.btn_reset_java.clicked.connect(lambda checked=False: self.line_java_path.clear())
        java_row.addWidget(self.line_java_path, 1)
        java_row.addWidget(self.btn_browse_java)
        java_row.addWidget(self.btn_reset_java)
        lay_perf.addWidget(self.lbl_java_field)
        lay_perf.addLayout(java_row)

        self.lbl_jvm_field = QLabel("Ek JVM Argümanları:")
        self.lbl_jvm_field.setStyleSheet("color: #CCCCCC; font-size: 13px; background: transparent;")
        self.line_jvm_args = QLineEdit(self.settings.get("jvm_args", ""))
        self.line_jvm_args.setPlaceholderText("Örn: -XX:+UseG1GC -Dsun.rmi.dgc.server.gcInterval=2147483646")
        self.line_jvm_args.textChanged.connect(self._on_settings_changed)
        lay_perf.addWidget(self.lbl_jvm_field)
        lay_perf.addWidget(self.line_jvm_args)
        lay_perf.addStretch()

        # --- KART 3: Microsoft Hesabı, Görünüm & Sesler ---
        card_acc, lay_acc, self.lbl_card_acc_hdr = _make_settings_card("HESAP, GÖRÜNÜM & SESLER")

        self.lbl_acc_status = QLabel("")
        self.lbl_acc_status.setStyleSheet("font-size: 14px; font-weight: bold; color: white; background: transparent;")
        lay_acc.addWidget(self.lbl_acc_status)

        acc_btn_row = QHBoxLayout()
        self.btn_acc_login = QPushButton("Giriş Yap / Hesap Değiştir")
        self.btn_acc_login.setCursor(Qt.PointingHandCursor)
        self.btn_acc_login.setStyleSheet("""
            QPushButton {
                background-color: #3C8527;
                color: #FFFFFF;
                border: 1px solid #1E3F13;
                border-top: 1.5px solid #5EB836;
                border-bottom: 2.5px solid #1E3F13;
                border-radius: 4px;
                padding: 7px 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #46992E;
                border-top: 1.5px solid #6AC742;
            }
        """)
        self.btn_acc_login.clicked.connect(lambda checked=False: self._settings_login_microsoft())
        self.btn_acc_logout = QPushButton("Oturumu Kapat")
        self.btn_acc_logout.setCursor(Qt.PointingHandCursor)
        self.btn_acc_logout.setStyleSheet("""
            QPushButton {
                background-color: #C0392B;
                color: #FFFFFF;
                border: 1px solid #78281F;
                border-top: 1.5px solid #E74C3C;
                border-bottom: 2.5px solid #78281F;
                border-radius: 4px;
                padding: 7px 14px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #D32F2F;
            }
        """)
        self.btn_acc_logout.clicked.connect(lambda checked=False: self._settings_logout_microsoft())
        acc_btn_row.addWidget(self.btn_acc_login)
        acc_btn_row.addWidget(self.btn_acc_logout)
        lay_acc.addLayout(acc_btn_row)

        # Theme Selector
        self.lbl_theme_field = QLabel("Arayüz Teması / Vurgu:")
        self.lbl_theme_field.setStyleSheet("color: #CCCCCC; font-size: 13px; margin-top: 4px; background: transparent;")
        self.combo_theme = QComboBox()
        self.combo_theme.blockSignals(True)
        curr_lang = self.settings.get("language", "tr")
        for k, name in theme_manager.get_theme_names(curr_lang):
            self.combo_theme.addItem(name, k)
        cur_t = self.settings.get("theme", "electric_amethyst")
        idx_t = self.combo_theme.findData(cur_t)
        if idx_t >= 0:
            self.combo_theme.setCurrentIndex(idx_t)
        self.combo_theme.blockSignals(False)
        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)
        lay_acc.addWidget(self.lbl_theme_field)
        lay_acc.addWidget(self.combo_theme)

        # Ambient Particles Toggle & Preset Selector
        self.check_particles = QCheckBox("Ortam Parçacıkları (Akıllı Performans Modu)")
        self.check_particles.blockSignals(True)
        self.check_particles.setChecked(bool(self.settings.get("particles_enabled", False)))
        self.check_particles.blockSignals(False)
        self.check_particles.toggled.connect(self._on_particles_toggled)
        lay_acc.addWidget(self.check_particles)

        part_row = QHBoxLayout()
        part_row.setSpacing(8)
        self.lbl_particle_preset = QLabel("Parçacık Efekti:")
        self.lbl_particle_preset.setStyleSheet("color: #CCCCCC; font-size: 12px; background: transparent;")
        self.combo_particle_preset = QComboBox()
        presets_list = [
            ("portal", "Nether & Ender Portal (Varsayılan)", "Nether & Ender Portal (Default)"),
            ("runes", "Büyü Masası Rünleri (SGA)", "Enchanting Runes (SGA)"),
            ("stars", "End Çubuğu Yıldızları", "End Rod Stars"),
            ("souls", "Ruhlar & Sculk", "Souls & Sculk"),
            ("sparkles", "Kıvılcımlar & Alevler", "Sparkles & Flames"),
            ("all", "Karışık (Tümü)", "Mixed (All)"),
        ]
        curr_lang = self.settings.get("language", "tr")
        for k, tr_t, en_t in presets_list:
            self.combo_particle_preset.addItem(en_t if curr_lang == "en" else tr_t, k)
        cur_preset = self.settings.get("particle_preset", "portal")
        idx_p = self.combo_particle_preset.findData(cur_preset)
        if idx_p >= 0:
            self.combo_particle_preset.setCurrentIndex(idx_p)
        self.combo_particle_preset.currentIndexChanged.connect(self._on_particle_preset_changed)
        part_row.addWidget(self.lbl_particle_preset)
        part_row.addWidget(self.combo_particle_preset, 1)
        lay_acc.addLayout(part_row)

        part_opacity_row = QHBoxLayout()
        part_opacity_row.setSpacing(8)
        self.lbl_particle_opacity = QLabel("Saydamlık Düzeyi:" if curr_lang == "tr" else "Opacity Level:")
        self.lbl_particle_opacity.setStyleSheet("color: #CCCCCC; font-size: 12px; background: transparent;")
        t_data_initial = theme_manager.get_theme(cur_t)
        initial_glow = t_data_initial.get("glow", "#C084FC")

        self.slider_particle_opacity = QSlider(Qt.Horizontal)
        self.slider_particle_opacity.setRange(5, 100)
        self.slider_particle_opacity.setValue(int(self.settings.get("particle_opacity", 50)))
        self.slider_particle_opacity.setStyleSheet(self._get_slider_qss(cur_t))
        self.lbl_part_opacity_val = QLabel(f"%{self.slider_particle_opacity.value()}")
        self.lbl_part_opacity_val.setStyleSheet(f"color: {initial_glow}; font-weight: 700; font-size: 12px; min-width: 38px;")
        self.slider_particle_opacity.valueChanged.connect(self._on_particle_opacity_changed)
        part_opacity_row.addWidget(self.lbl_particle_opacity)
        part_opacity_row.addWidget(self.slider_particle_opacity, 1)
        part_opacity_row.addWidget(self.lbl_part_opacity_val)
        lay_acc.addLayout(part_opacity_row)

        # Sound Effects Toggle & Volume Slider
        self.check_sounds = QCheckBox("UI & Bildirim Ses Efektleri")
        self.check_sounds.blockSignals(True)
        self.check_sounds.setChecked(bool(self.settings.get("sound_enabled", True)))
        self.check_sounds.blockSignals(False)
        self.check_sounds.toggled.connect(self._on_sounds_toggled)
        lay_acc.addWidget(self.check_sounds)

        vol_row = QHBoxLayout()
        vol_row.setSpacing(8)
        self.lbl_volume_field = QLabel("Ses Düzeyi:")
        self.lbl_volume_field.setStyleSheet("color: #CCCCCC; font-size: 12px; background: transparent;")
        self.slider_volume = QSlider(Qt.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(int(self.settings.get("sound_volume", 70)))
        self.slider_volume.setStyleSheet(self._get_slider_qss(cur_t))
        self.lbl_vol_val = QLabel(f"%{self.slider_volume.value()}")
        self.lbl_vol_val.setStyleSheet(f"color: {initial_glow}; font-weight: 700; font-size: 12px; min-width: 38px;")
        self.slider_volume.valueChanged.connect(self._on_volume_changed)

        self.btn_test_sound = QPushButton("Test")
        self.btn_test_sound.setCursor(Qt.PointingHandCursor)
        self.btn_test_sound.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.btn_test_sound.clicked.connect(lambda checked=False: self._test_sound())

        vol_row.addWidget(self.lbl_volume_field)
        vol_row.addWidget(self.slider_volume, 1)
        vol_row.addWidget(self.lbl_vol_val)
        vol_row.addWidget(self.btn_test_sound)
        lay_acc.addLayout(vol_row)

        self.lbl_bg_field = QLabel("Özel Arka Plan Görseli:")
        self.lbl_bg_field.setStyleSheet("color: #CCCCCC; font-size: 13px; margin-top: 4px; background: transparent;")
        bg_row = QHBoxLayout()
        self.btn_choose_bg = QPushButton("Arka Plan Seç...")
        self.btn_choose_bg.setCursor(Qt.PointingHandCursor)
        self.btn_choose_bg.clicked.connect(lambda checked=False: self._choose_custom_bg())
        self.btn_reset_bg = QPushButton("Varsayılan Arka Plan")
        self.btn_reset_bg.setCursor(Qt.PointingHandCursor)
        self.btn_reset_bg.clicked.connect(lambda checked=False: self._reset_custom_bg())
        bg_row.addWidget(self.btn_choose_bg)
        bg_row.addWidget(self.btn_reset_bg)
        lay_acc.addWidget(self.lbl_bg_field)
        lay_acc.addLayout(bg_row)
        lay_acc.addStretch()

        # --- KART 4: Depolama & Güncelleme / Hakkında ---
        card_sys, lay_sys, self.lbl_card_sys_hdr = _make_settings_card("DEPOLAMA & GÜNCELLEME")

        folder_grid = QGridLayout()
        folder_grid.setSpacing(8)
        self.btn_f_mc = QPushButton(".minecraft Klasörü")
        self.btn_f_mc.setCursor(Qt.PointingHandCursor)
        self.btn_f_mc.clicked.connect(lambda checked=False: (os.makedirs(self.mc_dir, exist_ok=True), os.startfile(self.mc_dir)))
        self.btn_f_prof = QPushButton("Profiller Klasörü")
        self.btn_f_prof.setCursor(Qt.PointingHandCursor)
        self.btn_f_prof.clicked.connect(lambda checked=False: (os.makedirs(self.profiles_dir, exist_ok=True), os.startfile(self.profiles_dir)))
        self.btn_f_srv = QPushButton("Sunucular Klasörü")
        self.btn_f_srv.setCursor(Qt.PointingHandCursor)
        self.btn_f_srv.clicked.connect(lambda checked=False: (os.makedirs(os.path.join(self.data_dir, "servers"), exist_ok=True), os.startfile(os.path.join(self.data_dir, "servers"))))
        self.btn_clear_cache = QPushButton("Log & Önbellek Temizle")
        self.btn_clear_cache.setCursor(Qt.PointingHandCursor)
        self.btn_clear_cache.clicked.connect(lambda checked=False: self._clear_launcher_cache())
        folder_grid.addWidget(self.btn_f_mc, 0, 0)
        folder_grid.addWidget(self.btn_f_prof, 0, 1)
        folder_grid.addWidget(self.btn_f_srv, 1, 0)
        folder_grid.addWidget(self.btn_clear_cache, 1, 1)
        lay_sys.addLayout(folder_grid)

        ver_row = QHBoxLayout()
        self.lbl_version_info = QLabel(f"Vega Launcher v{__version__} — by {__author__}")
        self.lbl_version_info.setStyleSheet("color: #AAAAAA; font-size: 13px; font-weight: bold; background: transparent;")
        self.btn_check_updates = QPushButton("GÜNCELLEMELERİ KONTROL ET")
        self.btn_check_updates.setCursor(Qt.PointingHandCursor)
        self.btn_check_updates.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #5B21B6;
                border-top: 1.5px solid #A78BFA;
                border-left: 1px solid #8B5CF6;
                border-right: 1px solid #6D28D9;
                border-bottom: 3.5px solid #4C1D95;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #8B5CF6;
                border-top: 1.5px solid #C084FC;
            }
            QPushButton:pressed {
                border-top: 2.5px solid #4C1D95;
                border-bottom: 1px solid #A78BFA;
                padding-top: 10px;
            }
        """)
        self.btn_check_updates.clicked.connect(lambda checked=False: self._manual_check_updates())
        ver_row.addWidget(self.lbl_version_info)
        ver_row.addStretch()
        ver_row.addWidget(self.btn_check_updates)
        lay_sys.addSpacing(6)
        lay_sys.addLayout(ver_row)
        lay_sys.addStretch()

        grid.addWidget(card_gen, 0, 0)
        grid.addWidget(card_perf, 0, 1)
        grid.addWidget(card_acc, 1, 0)
        grid.addWidget(card_sys, 1, 1)

        scroll.setWidget(container)
        outer_layout.addWidget(scroll, 1)

        self._refresh_account_status_label()
        return page

    def _refresh_account_status_label(self):
        acc_name = (getattr(self, "ms_login", {}) or {}).get("name")
        if hasattr(self, "nav_bar") and hasattr(self.nav_bar, "update_user"):
            self.nav_bar.update_user(acc_name, bool(acc_name))
        if not hasattr(self, "lbl_acc_status"):
            return
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        if acc_name:
            self.lbl_acc_status.setText(f"{'Active Account' if lang == 'en' else 'Aktif Hesap'}: {acc_name}")
            self.lbl_acc_status.setStyleSheet("font-size: 14px; font-weight: bold; color: #2E8B57; background: transparent;")
        else:
            self.lbl_acc_status.setText("Not Logged In (Microsoft)" if lang == "en" else "Giriş Yapılmadı (Microsoft Hesabı Yok)")
            self.lbl_acc_status.setStyleSheet("font-size: 14px; font-weight: bold; color: #CD5C5C; background: transparent;")

    def _on_theme_changed(self):
        if not hasattr(self, "combo_theme"):
            return
        theme_key = self.combo_theme.currentData() or "electric_amethyst"
        self.settings["theme"] = theme_key
        self.save_config()
        self.apply_theme(theme_key)
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            self.sound_mgr.play_amethyst_shimmer()

    def _on_particles_toggled(self, checked):
        self.settings["particles_enabled"] = bool(checked)
        self.save_config()
        if hasattr(self, "particle_overlay") and self.particle_overlay:
            self.particle_overlay.set_enabled(bool(checked))
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            if checked:
                self.sound_mgr.play_lever_on()
            else:
                self.sound_mgr.play_lever_off()

    def _on_particle_preset_changed(self):
        if not hasattr(self, "combo_particle_preset"):
            return
        preset = self.combo_particle_preset.currentData() or "portal"
        self.settings["particle_preset"] = preset
        self.save_config()
        if hasattr(self, "particle_overlay") and self.particle_overlay:
            self.particle_overlay.set_preset(preset)
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            self.sound_mgr.play_enchant()

    def _on_particle_opacity_changed(self, value):
        self.settings["particle_opacity"] = int(value)
        if hasattr(self, "lbl_part_opacity_val"):
            self.lbl_part_opacity_val.setText(f"%{value}")
        self.save_config()
        if hasattr(self, "particle_overlay") and self.particle_overlay:
            self.particle_overlay.set_opacity_percent(int(value))

    def _on_sounds_toggled(self, checked):
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            if checked:
                self.sound_mgr.set_enabled(True)
                self.sound_mgr.play_lever_on(force=True)
            else:
                self.sound_mgr.play_lever_off(force=True)
                self.sound_mgr.set_enabled(False)
        self.settings["sound_enabled"] = bool(checked)
        self.save_config()

    def _on_volume_changed(self, value):
        self.settings["sound_volume"] = int(value)
        if hasattr(self, "lbl_vol_val"):
            self.lbl_vol_val.setText(f"%{value}")
        self.save_config()
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            self.sound_mgr.set_volume(int(value))

    def _test_sound(self):
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            self.sound_mgr.play_levelup(force=True)

    def _on_winsize_changed(self):
        self._on_settings_changed()
        self.apply_window_size_setting(self.settings.get("window_size", "auto"))

    def _on_settings_changed(self):
        if not hasattr(self, "combo_lang"):
            return
        old_lang = self.settings.get("language", "tr")
        new_lang = self.combo_lang.currentData() or "tr"
        self.settings["language"] = new_lang
        self.settings["window_size"] = self.combo_winsize.currentData() or "auto"
        self.settings["on_launch"] = self.combo_onlaunch.currentData() or "minimize"
        self.settings["default_ram"] = self.spin_default_ram.value()
        self.settings["java_path"] = self.line_java_path.text().strip()
        self.settings["jvm_args"] = self.line_jvm_args.text().strip()
        theme_val = self.combo_theme.currentData() if hasattr(self, "combo_theme") else None
        if theme_val:
            self.settings["theme"] = theme_val
        if hasattr(self, "check_particles"):
            self.settings["particles_enabled"] = self.check_particles.isChecked()
        if hasattr(self, "combo_particle_preset") and self.combo_particle_preset.currentData():
            self.settings["particle_preset"] = self.combo_particle_preset.currentData()
        if hasattr(self, "slider_particle_opacity"):
            self.settings["particle_opacity"] = self.slider_particle_opacity.value()
        if hasattr(self, "check_sounds"):
            self.settings["sound_enabled"] = self.check_sounds.isChecked()
        if hasattr(self, "slider_volume"):
            self.settings["sound_volume"] = self.slider_volume.value()
        self.save_config()
        if new_lang != old_lang:
            self.apply_language(new_lang)

    def apply_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        if hasattr(self, "nav_bar"):
            self.nav_bar.set_language(lang)
        if hasattr(self, "action_bar"):
            self.action_bar.set_language(lang)
        if hasattr(self, "hero_icon_box"):
            self.hero_icon_box.setToolTip("Edit Profile / Change Icon" if en else "Profili Düzenle / Simgeyi Değiştir")
        if hasattr(self, "hero_eyebrow"):
            self.hero_eyebrow.setText("SELECTED PROFILE" if en else "SEÇİLİ PROFİL")
            self.hero_edit_btn.setText("Edit Profile" if en else "Profili Düzenle")
            self.hero_shortcut_btn.setText("Desktop Shortcut" if en else "Masaüstü Kısayolu")
            self.hero_open_folder.setText("Open Folder" if en else "Klasörü Aç")
            self.add_profile_btn.setText("+ New Profile" if en else "+ Yeni Profil")
            self.install_file_btn.setText("Install Zip" if en else "Zip'ten Kur")
            self.profile_search.setPlaceholderText("Search profiles..." if en else "Profillerde ara...")
        if hasattr(self, "bed_desc"):
            self.bed_desc.setText(
                "Optimized for Windows 10/11 with cross-platform support."
                if en else
                "Windows 10/11 için optimize edilmiş, çapraz platform destekli sürüm."
            )
            self.bed_btn.setText("PLAY BEDROCK" if en else "BEDROCK OYNA")
        if hasattr(self, "dun_desc"):
            self.dun_desc.setText(
                "Explore dungeons, equip legendary weapons, and defeat the Arch-Illager!"
                if en else
                "Zindanları keşfet, efsanevi silahlar kuşan ve Arch-Illager'ı yen!"
            )
            self.dun_btn.setText("ENTER DUNGEON" if en else "ZİNDANA GİR")
            self.dun_mods_btn.setText("Installed Mods" if en else "Kurulu Modlar")
        if hasattr(self, "lbl_settings_title"):
            self.lbl_settings_title.setText("Application Settings" if en else "Uygulama Ayarları")
            self.lbl_card_gen_hdr.setText("General, Language & Window" if en else "Genel, Dil & Pencere")
            self.lbl_card_perf_hdr.setText("Game & Performance (Java / RAM)" if en else "Oyun & Performans (Java / RAM)")
            self.lbl_card_acc_hdr.setText("Microsoft Account & Appearance" if en else "Microsoft Hesabı & Görünüm")
            self.lbl_card_sys_hdr.setText("Storage & Updates" if en else "Depolama & Güncelleme")
            self.lbl_lang_field.setText("Interface Language:" if en else "Arayüz Dili / Language:")
            self.lbl_winsize_field.setText("Startup & Window Size:" if en else "Açılış & Pencere Boyutu:")
            self.lbl_onlaunch_field.setText("When Game Launches:" if en else "Oyun Başladığında Başlatıcı:")
            self.lbl_defram_field.setText("Default RAM (MB):" if en else "Varsayılan RAM Miktarı (MB):")
            self.lbl_java_field.setText("Custom Java Path (Empty = Auto):" if en else "Özel Java Yolu (Boş = Otomatik):")
            self.lbl_jvm_field.setText("Extra JVM Arguments:" if en else "Ek JVM Argümanları:")
            self.lbl_bg_field.setText("Custom Background Image:" if en else "Özel Arka Plan Görseli:")

            self.combo_winsize.blockSignals(True)
            ws_items = (
                ["Auto (Fit to Screen)", "Compact (1280 x 720)", "Medium (1350 x 755)", "Wide (1440 x 810)", "Fullscreen (Maximized)", "Remember Last Size"]
                if en else
                ["Otomatik (Ekrana Göre)", "Kompakt (1280 x 720)", "Yarı Ekran / Orta (1350 x 755)", "Geniş (1440 x 810)", "Tam Ekran (Maksimize)", "Son Boyutu Hatırla"]
            )
            for i, txt in enumerate(ws_items):
                self.combo_winsize.setItemText(i, txt)
            self.combo_winsize.blockSignals(False)

            self.combo_onlaunch.blockSignals(True)
            ol_items = (
                ["Minimize to Taskbar", "Keep Open", "Hide Completely (Reopen on Exit)"]
                if en else
                ["Simge Durumuna Küçült", "Açık Tut", "Tamamen Gizle (Oyun Kapanınca Aç)"]
            )
            for i, txt in enumerate(ol_items):
                self.combo_onlaunch.setItemText(i, txt)
            self.combo_onlaunch.blockSignals(False)

            self.line_java_path.setPlaceholderText("Auto (Default Java)" if en else "Otomatik (Varsayılan Java)")
            self.btn_browse_java.setText("Browse..." if en else "Gözat...")
            self.btn_reset_java.setText("Reset" if en else "Sıfırla")
            self.line_jvm_args.setPlaceholderText(
                "E.g.: -XX:+UseG1GC -Dsun.rmi.dgc.server.gcInterval=2147483646"
                if en else
                "Örn: -XX:+UseG1GC -Dsun.rmi.dgc.server.gcInterval=2147483646"
            )

            self.btn_apply_ram_all.setText("Apply to All Profiles" if en else "Tüm Profillere Uygula")
            self.btn_acc_login.setText("Sign In / Switch Account" if en else "Giriş Yap / Hesap Değiştir")
            self.btn_acc_logout.setText("Sign Out" if en else "Oturumu Kapat")
            self.btn_choose_bg.setText("Choose Image..." if en else "Arka Plan Seç...")
            self.btn_reset_bg.setText("Default Background" if en else "Varsayılan Arka Plan")
            self.btn_f_mc.setText(".minecraft Folder" if en else ".minecraft Klasörü")
            self.btn_f_prof.setText("Profiles Folder" if en else "Profiller Klasörü")
            self.btn_f_srv.setText("Servers Folder" if en else "Sunucular Klasörü")
            self.btn_clear_cache.setText("Clear Logs & Cache" if en else "Log & Önbellek Temizle")
            self.btn_check_updates.setText("Check for Updates" if en else "Güncellemeleri Kontrol Et")

            if hasattr(self, "lbl_theme_field"):
                self.lbl_card_acc_hdr.setText("Account, Appearance & Sounds" if en else "Hesap, Görünüm & Sesler")
                self.lbl_theme_field.setText("Interface Theme / Accent:" if en else "Arayüz Teması / Vurgu:")
                if hasattr(self, "check_particles"):
                    self.check_particles.blockSignals(True)
                    self.check_particles.setText("Ambient Particles (Smart Performance Mode)" if en else "Ortam Parçacıkları (Akıllı Performans Modu)")
                    self.check_particles.blockSignals(False)
                if hasattr(self, "lbl_particle_preset"):
                    self.lbl_particle_preset.setText("Particle Style:" if en else "Parçacık Efekti:")
                if hasattr(self, "combo_particle_preset"):
                    self.combo_particle_preset.blockSignals(True)
                    cur_p = self.settings.get("particle_preset", "portal")
                    presets_map = [
                        ("portal", "Nether & Ender Portal (Default)" if en else "Nether & Ender Portal (Varsayılan)"),
                        ("runes", "Enchanting Runes (SGA)" if en else "Büyü Masası Rünleri (SGA)"),
                        ("stars", "End Rod Stars" if en else "End Çubuğu Yıldızları"),
                        ("souls", "Souls & Sculk" if en else "Ruhlar & Sculk"),
                        ("sparkles", "Sparkles & Flames" if en else "Kıvılcımlar & Alevler"),
                        ("all", "Mixed (All)" if en else "Karışık (Tümü)"),
                    ]
                    self.combo_particle_preset.clear()
                    for k, label in presets_map:
                        self.combo_particle_preset.addItem(label, k)
                    idx = self.combo_particle_preset.findData(cur_p)
                    if idx >= 0:
                        self.combo_particle_preset.setCurrentIndex(idx)
                    self.combo_particle_preset.blockSignals(False)
                if hasattr(self, "lbl_particle_opacity"):
                    self.lbl_particle_opacity.setText("Opacity Level:" if en else "Saydamlık Düzeyi:")
                if hasattr(self, "check_sounds"):
                    self.check_sounds.blockSignals(True)
                    self.check_sounds.setText("UI & Alert Sound Effects" if en else "UI & Bildirim Ses Efektleri")
                    self.check_sounds.blockSignals(False)
                self.lbl_volume_field.setText("Volume:" if en else "Ses Düzeyi:")
                self.btn_test_sound.setText("Test")
                
                # Update theme combo names
                cur_data = self.settings.get("theme", "electric_amethyst")
                self.combo_theme.blockSignals(True)
                self.combo_theme.clear()
                for k, name in theme_manager.get_theme_names(lang):
                    self.combo_theme.addItem(name, k)
                idx = self.combo_theme.findData(cur_data)
                if idx >= 0:
                    self.combo_theme.setCurrentIndex(idx)
                self.combo_theme.blockSignals(False)

        if hasattr(self, "nav_bar"):
            self.nav_bar.set_language(lang)
        if hasattr(self, "installed_mods_panel"):
            self.installed_mods_panel.set_language(lang)
        if hasattr(self, "detail_panel"):
            self.detail_panel.set_language(lang)
        for b_attr in ("pack_browser", "mod_browser", "shader_browser"):
            if hasattr(self, b_attr):
                getattr(self, b_attr).set_language(lang)
        if hasattr(self, "server_page") and hasattr(self.server_page, "set_language"):
            self.server_page.set_language(lang)
        if hasattr(self, "profile_list"):
            for i in range(self.profile_list.count()):
                item = self.profile_list.item(i)
                w = self.profile_list.itemWidget(item)
                if w and hasattr(w, "set_language"):
                    w.set_language(lang)
            right_vis = self.right_stack.isVisible() if hasattr(self, "right_stack") else False
            self.on_profile_selected()
            if hasattr(self, "right_stack") and hasattr(self, "stack") and self.stack.currentIndex() != 0:
                self.right_stack.setVisible(right_vis)
        self._refresh_account_status_label()

    def _apply_ram_to_all_profiles(self):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        ram_val = self.spin_default_ram.value()
        for pdata in self.profiles.values():
            pdata["ram"] = ram_val
        self.save_config()
        self.refresh_profile_list()
        self.on_profile_selected()
        QMessageBox.information(
            self,
            "Info" if en else "Bilgi",
            f"RAM allocation for all profiles updated to {ram_val} MB."
            if en else
            f"Tüm profillerin RAM değeri {ram_val} MB olarak güncellendi."
        )

    def _browse_java_path(self):
        from PySide6.QtWidgets import QFileDialog
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Java (javaw.exe / java.exe)" if en else "Java Seç (javaw.exe / java.exe)",
            "",
            "Executable (*.exe);;All Files (*)"
        )
        if file_path:
            self.line_java_path.setText(file_path)

    def _settings_login_microsoft(self):
        dialog = MicrosoftLoginDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.ms_login = dialog.get_account_data()
            self.save_config()
            self._refresh_account_status_label()

    def _settings_logout_microsoft(self):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        self.ms_login = {}
        self.save_config()
        self._refresh_account_status_label()
        QMessageBox.information(
            self,
            "Info" if en else "Bilgi",
            "Signed out of Microsoft account." if en else "Microsoft oturumu kapatıldı."
        )

    def _choose_custom_bg(self):
        from PySide6.QtWidgets import QFileDialog
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image" if en else "Arka Plan Görseli Seç",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if file_path:
            self.settings["custom_bg"] = file_path
            self.save_config()
            self.apply_background()

    def _reset_custom_bg(self):
        self.settings["custom_bg"] = ""
        self.save_config()
        self.apply_background()

    def _clear_launcher_cache(self):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            self.sound_mgr.play_fizz()
        removed = 0
        logs_dir = os.path.join(self.mc_dir, "logs")
        crash_dir = os.path.join(self.mc_dir, "crash-reports")
        for d in (logs_dir, crash_dir):
            if os.path.exists(d):
                for f in os.listdir(d):
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp):
                        try:
                            os.remove(fp)
                            removed += 1
                        except Exception:
                            pass
        QMessageBox.information(
            self,
            "Cleared" if en else "Temizlendi",
            f"Cleared {removed} old log/crash report file(s)."
            if en else
            f"{removed} adet eski log/çökme raporu temizlendi."
        )

    def _manual_check_updates(self):
        if not hasattr(self, "_app_updater") or self._app_updater is None:
            from app_updater import AppUpdater
            self._app_updater = AppUpdater(self, __version__)
        self._app_updater.check(manual=True)

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

    def create_profile_shortcut(self):
        pid, pdata = self.get_selected_profile()
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        if not pid or not pdata:
            QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "Please select a profile first." if en else "Lütfen önce bir profil seçin."
            )
            return

        pname = pdata.get("name", "Profile" if en else "Profil").strip()
        desktop_dir = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
        if not os.path.exists(desktop_dir):
            try:
                os.makedirs(desktop_dir, exist_ok=True)
            except Exception:
                pass

        safe_name = re.sub(r'[\\/*?:"<>|]', "_", pname).strip() or "Minecraft Profile"
        shortcut_path = os.path.join(desktop_dir, f"{safe_name}.lnk")

        is_frozen = getattr(sys, "frozen", False)
        base_dir = os.path.dirname(sys.executable if is_frozen else os.path.abspath(__file__))

        icon_candidates = [
            os.path.join(base_dir, "assets", "ender_pearl.ico"),
            os.path.join(base_dir, "ender_pearl.ico"),
            os.path.join(base_dir, "enderman_icon.ico"),
        ]
        icon_path = next((ic for ic in icon_candidates if os.path.exists(ic)), sys.executable)

        if is_frozen:
            target_path = sys.executable
            arguments = f'--launch "{pid}"'
            work_dir = base_dir
        else:
            target_script = os.path.join(base_dir, "main.py")
            pythonw = sys.executable.replace("python.exe", "pythonw.exe")
            target_path = pythonw if os.path.exists(pythonw) else sys.executable
            arguments = f'"{target_script}" --launch "{pid}"'
            work_dir = base_dir

        try:
            created = False
            # Method 1: Direct Windows COM dispatch (fastest, in-process, zero temp files)
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                shortcut = shell.CreateShortcut(shortcut_path)
                shortcut.TargetPath = target_path
                shortcut.Arguments = arguments
                shortcut.Description = f"{safe_name} - Vega Launcher"
                shortcut.IconLocation = f"{icon_path}, 0"
                shortcut.WorkingDirectory = work_dir
                shortcut.Save()
                created = True
            except Exception:
                created = False

            # Method 2: Native PowerShell COM call (no temp file on disk, fully handles unicode)
            if not created:
                try:
                    import base64
                    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath = '{target_path}'
$s.Arguments = '{arguments}'
$s.Description = '{safe_name} - Vega Launcher'
$s.IconLocation = '{icon_path}, 0'
$s.WorkingDirectory = '{work_dir}'
$s.Save()
"""
                    enc = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
                    subprocess.run(
                        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                        check=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )
                    created = True
                except Exception:
                    created = False

            # Method 3: UTF-16LE VBScript fallback (standard Windows Script Host unicode encoding)
            if not created:
                vbs_args = arguments.replace('"', '""')
                vbs_safe_name = safe_name.replace('"', '""')
                vbs_shortcut_path = shortcut_path.replace('"', '""')
                vbs_target_path = target_path.replace('"', '""')
                vbs_icon_path = icon_path.replace('"', '""')
                vbs_work_dir = work_dir.replace('"', '""')
                vbs_script = f"""Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{vbs_shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{vbs_target_path}"
oLink.Arguments = "{vbs_args}"
oLink.Description = "{vbs_safe_name} - Vega Launcher"
oLink.IconLocation = "{vbs_icon_path}, 0"
oLink.WorkingDirectory = "{vbs_work_dir}"
oLink.Save
"""
                vbs_path = os.path.join(os.environ.get("TEMP", "."), f"create_shortcut_{uuid.uuid4().hex[:8]}.vbs")
                try:
                    with open(vbs_path, "w", encoding="utf-16le") as f:
                        f.write(vbs_script)
                    subprocess.run(["wscript", vbs_path], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    created = True
                finally:
                    if os.path.exists(vbs_path):
                        try:
                            os.remove(vbs_path)
                        except Exception:
                            pass

            if not os.path.exists(shortcut_path):
                raise RuntimeError("Shortcut file was not generated.")

            try:
                import ctypes
                ctypes.windll.shell32.SHChangeNotify(0x00002000, 0x0005, shortcut_path, None)
                ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
            except Exception:
                pass

            msg = (
                f"Desktop shortcut created for '{pname}'!\n\nLocation: {shortcut_path}"
                if en else
                f"'{pname}' için masaüstü kısayolu oluşturuldu!\n\nKonum: {shortcut_path}"
            )
            self.statusBar().showMessage(
                f"Shortcut created for {pname}." if en else f"{pname} kısayolu oluşturuldu.",
                4000
            )
            QMessageBox.information(self, "Success" if en else "Başarılı", msg)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error" if en else "Hata",
                f"Shortcut could not be created: {e}" if en else f"Kısayol oluşturulamadı: {e}"
            )

    def switch_tab(self, key):
        mapping = {"home": 0, "packs": 1, "mods": 2, "shaders": 3, "bedrock_home": 4, "dungeons_home": 5, "server": 6, "settings": 7}
        idx = mapping.get(key, 0)
        self.stack.setCurrentIndex(idx)
        
        if key == "home":
            # If a profile is selected, show its mod panel, else hide
            if self.profile_list.currentItem():
                self.right_stack.setCurrentWidget(self.installed_mods_panel)
                self.right_stack.show()
            else:
                self.right_stack.hide()
        elif key == "packs":
            # Modpack tab: drawer is closed unless a card is actively selected
            if getattr(self.pack_browser, 'selected_card', None) and self.right_stack.isVisible() and self.right_stack.currentWidget() == self.detail_panel:
                self.pack_browser.set_columns(3)
                self.right_stack.show()
            else:
                self.right_stack.hide()
                self.pack_browser.set_columns(4)
                if hasattr(self.pack_browser, 'clear_selection'):
                    self.pack_browser.clear_selection()
            self.pack_browser.refresh_if_needed()
        elif key in ["bedrock_home", "dungeons_home", "server", "settings"]:
            self.right_stack.hide()
            if key == "settings":
                self._refresh_account_status_label()
        else:
            # Store/search tabs (mods / shaders)
            browser = self.mod_browser if key == "mods" else self.shader_browser
            if getattr(browser, 'selected_card', None) and self.right_stack.isVisible() and self.right_stack.currentWidget() == self.detail_panel:
                browser.set_columns(3)
                self.right_stack.show()
            else:
                self.right_stack.hide()
                browser.set_columns(4)
                if hasattr(browser, 'clear_selection'):
                    browser.clear_selection()
            if key == "mods": self.mod_browser.refresh_if_needed()
            elif key == "shaders": self.shader_browser.refresh_if_needed()
        
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
        if hasattr(self, "sound_mgr") and self.sound_mgr:
            self.sound_mgr.play_enderchest_open()
        self.right_stack.setCurrentWidget(self.detail_panel)
        self.detail_panel.show()
        self.right_stack.show()
        total_w = self.splitter.width() or self.width() or 1440
        self.splitter.setSizes([max(total_w - 360, 600), 360])
        current_w = self.stack.currentWidget()
        if hasattr(current_w, 'set_columns'):
            current_w.set_columns(3)
        self.detail_panel.update_info(data)

    def on_detail_panel_closed(self):
        self.right_stack.hide()
        current_w = self.stack.currentWidget()
        if hasattr(current_w, 'set_columns'):
            current_w.set_columns(4)
        if hasattr(current_w, 'clear_selection'):
            current_w.clear_selection()

    def refresh_profile_list(self):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        unknown_txt = "Unknown" if en else "Bilinmiyor"
        self.profile_list.clear()
        for pid, pdata in self.profiles.items():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, pid)
            
            widget = ProfileWidget(
                pdata.get('name', unknown_txt),
                pdata.get('version', unknown_txt),
                pdata.get('ram', 4096),
                pid,
                icon=pdata.get('icon', ''),
                lang=lang,
            )
            widget.update_clicked.connect(self.on_profile_update_clicked)
            
            if hasattr(self, 'available_updates') and pid in self.available_updates:
                ver_id, url = self.available_updates[pid]
                widget.update_btn.setVisible(True)
                widget.new_version_id = ver_id
                widget.new_url = url
                
            from PySide6.QtCore import QSize
            item.setSizeHint(QSize(100, 74))
            
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
        return self._get_profile_store().generate_unique_profile_name(
            base_name, getattr(self, "profiles", {})
        )

    def get_active_profile_loader(self, pdata=None):
        if pdata is None:
            _, pdata = self.get_selected_profile()
        from mod_manager import detect_profile_loader
        return detect_profile_loader(pdata)

    def _update_hero_card_banner(self, pdata=None):
        if not hasattr(self, 'hero_card'):
            return
        if not pdata:
            self.hero_card.setStyleSheet("""
                QFrame#HeroCard {
                    background-color: #1A1A1E;
                    border: 1px solid #282830;
                    border-top: 1px solid #34343E;
                    border-bottom: 2px solid #141416;
                    border-radius: 6px;
                }
            """)
            return

        banner = pdata.get("banner", "")
        if banner and banner in theme_manager.BANNER_PRESETS:
            preset = theme_manager.BANNER_PRESETS[banner]
            self.hero_card.setStyleSheet(f"""
                QFrame#HeroCard {{
                    background: {preset['gradient']};
                    border: 1.5px solid {preset['accent']};
                    border-radius: 6px;
                }}
            """)
        elif banner and os.path.exists(banner):
            fwd = banner.replace("\\", "/")
            self.hero_card.setStyleSheet(f"""
                QFrame#HeroCard {{
                    background-image: url('{fwd}');
                    background-position: center;
                    border: 1.5px solid #282830;
                    border-radius: 6px;
                }}
            """)
        else:
            self.hero_card.setStyleSheet("""
                QFrame#HeroCard {
                    background-color: #1A1A1E;
                    border: 1px solid #282830;
                    border-top: 1px solid #34343E;
                    border-bottom: 2px solid #141416;
                    border-radius: 6px;
                }
            """)

    def _on_profile_item_clicked(self, item=None):
        if hasattr(self, 'sound_mgr') and self.sound_mgr:
            self.sound_mgr.play_click()
        self.on_profile_selected()

    def on_profile_selected(self):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        pid, pdata = self.get_selected_profile()
        if pdata:
            self.active_profile_version = pdata['version']
            self.active_profile_loader = self.get_active_profile_loader(pdata)
            self.action_bar.pack_name.setText(pdata['name'])
            playtime = pdata.get("playtime", 0)
            hours = playtime // 3600
            mins = (playtime % 3600) // 60
            if playtime > 0:
                pt_str = f" • Playtime: {hours}h {mins}m" if en else f" • Oynama: {hours}s {mins}dk"
            else:
                pt_str = ""
            self.action_bar.pack_size.setText(f"{pdata['version']} | {pdata['ram']} MB{pt_str}")
            if hasattr(self.action_bar, 'set_profile_badges'):
                self.action_bar.set_profile_badges(pdata['version'], self.active_profile_loader, pdata.get('ram', 4096))

            # Update Hero Showcase Card
            if hasattr(self, 'hero_title'):
                self.hero_title.setText(pdata['name'])
                if hasattr(self, 'hero_icon_lbl'):
                    disp_icon = pdata.get('icon') or '🎮'
                    self.hero_icon_lbl.setText(disp_icon)
                disp_v = str(pdata['version']).replace("fabric-loader-", "fabric-")
                self.hero_badge_ver.setText(f"v {disp_v}")
                self.hero_badge_loader.setText(self.active_profile_loader.capitalize() if self.active_profile_loader else "Vanilla")
                self.hero_badge_ram.setText(f"{pdata.get('ram', 4096)} MB")
                if playtime > 0:
                    self.hero_badge_play.setText(f"{hours}h {mins}m" if en else f"{hours}s {mins}dk")
                else:
                    self.hero_badge_play.setText("0h" if en else "0s")
            
            self._update_hero_card_banner(pdata)

            if hasattr(self, 'hero_edit_btn'):
                self.hero_edit_btn.setEnabled(True)
                self.hero_shortcut_btn.setEnabled(True)
                self.hero_open_folder.setEnabled(True)

            self.statusBar().showMessage(
                f"Active Profile: {pdata['name']} ({pdata['version']})"
                if en else
                f"Aktif Profil: {pdata['name']} ({pdata['version']})"
            )
            
            # Mod yöneticisini yükle ve göster
            mods_dir = os.path.join(pdata["path"], "mods")
            self.installed_mods_panel.load_mods(mods_dir, pdata, pid, self)
            self.right_stack.setCurrentWidget(self.installed_mods_panel)
            self.right_stack.show()

            if hasattr(self, "profile_list"):
                curr_row = self.profile_list.currentRow()
                for i in range(self.profile_list.count()):
                    it = self.profile_list.item(i)
                    w = self.profile_list.itemWidget(it)
                    if w and hasattr(w, "set_selected"):
                        w.set_selected(i == curr_row)
        else:
            no_prof_txt = "No Profile Selected" if en else "Profil Seçilmedi"
            self.active_profile_version = None
            self.active_profile_loader = None
            self.action_bar.pack_name.setText(no_prof_txt)
            self.action_bar.pack_size.setText("")
            if hasattr(self.action_bar, 'set_profile_badges'):
                self.action_bar.set_profile_badges("", "", "")
            if hasattr(self, 'hero_title'):
                self.hero_title.setText(no_prof_txt)
                if hasattr(self, 'hero_icon_lbl'):
                    self.hero_icon_lbl.setText("")
                self.hero_badge_ver.setText("v --")
                self.hero_badge_loader.setText("Vanilla")
                self.hero_badge_ram.setText("-- MB")
                self.hero_badge_play.setText("0h" if en else "0s")
            
            self._update_hero_card_banner(None)

            if hasattr(self, 'hero_edit_btn'):
                self.hero_edit_btn.setEnabled(False)
                self.hero_shortcut_btn.setEnabled(False)
                self.hero_open_folder.setEnabled(False)
            self.statusBar().showMessage("No profile selected" if en else "Profil seçilmedi")
            self.right_stack.hide()

    @staticmethod
    def resolve_dungeons_mods_dir(custom_path=None) -> str:
        """Dynamically resolve Minecraft Dungeons ~mods directory across drive letters and standard install trees."""
        if custom_path and os.path.exists(custom_path):
            return custom_path

        import string
        drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        candidates = []
        for d in drives:
            candidates.append(os.path.join(d, "XboxGames", "Minecraft Dungeons", "Content", "Dungeons", "Content", "Paks", "~mods"))
            candidates.append(os.path.join(d, "SteamLibrary", "steamapps", "common", "Minecraft Dungeons", "dungeons", "dungeons", "Content", "Paks", "~mods"))
            candidates.append(os.path.join(d, "Program Files (x86)", "Steam", "steamapps", "common", "Minecraft Dungeons", "dungeons", "dungeons", "Content", "Paks", "~mods"))
            candidates.append(os.path.join(d, "Program Files", "Steam", "steamapps", "common", "Minecraft Dungeons", "dungeons", "dungeons", "Content", "Paks", "~mods"))

        for c in candidates:
            if os.path.exists(os.path.dirname(c)):
                return c

        fallback_drive = drives[0] if drives else "C:\\"
        return os.path.join(fallback_drive, "XboxGames", "Minecraft Dungeons", "Content", "Dungeons", "Content", "Paks", "~mods")

    def show_dungeons_mods(self):
        dun_mods_dir = self.resolve_dungeons_mods_dir(getattr(self, "settings", {}).get("dungeons_mods_dir"))
        paks_dir = os.path.dirname(dun_mods_dir) if dun_mods_dir else ""
        if not os.path.exists(paks_dir) and not os.path.exists(dun_mods_dir):
            lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
            en = (lang == "en")
            try:
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            QMessageBox.warning(
                self,
                "Error" if en else "Hata",
                "Minecraft Dungeons installation was not found on your system." if en
                else "Minecraft Dungeons kurulumu sisteminizde bulunamadı."
            )
            return

        os.makedirs(dun_mods_dir, exist_ok=True)
        self.installed_mods_panel.load_mods(dun_mods_dir, main_window=self)
        self.right_stack.setCurrentWidget(self.installed_mods_panel)
        self.right_stack.show()

    def show_profile_context_menu(self, pos):
        item = self.profile_list.itemAt(pos)
        if not item: return
        self.profile_list.setCurrentItem(item)
        self.on_profile_selected()
        
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #12121A;
                color: #F8FAFC;
                border: 1px solid rgba(139, 92, 246, 0.45);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
                font-weight: 500;
            }
            QMenu::item:selected {
                background-color: #8B5CF6;
                color: #FFFFFF;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.1);
                margin: 4px 8px;
            }
        """)
        
        play_action = menu.addAction("Play" if en else "Oyna")
        folder_action = menu.addAction("Open Profile Folder" if en else "Profil Klasörünü Aç")
        shortcut_action = menu.addAction("Create Desktop Shortcut" if en else "Masaüstü Kısayolu Oluştur")
        menu.addSeparator()
        edit_action = menu.addAction("Edit Profile" if en else "Profili Düzenle")
        del_action = menu.addAction("Delete Profile" if en else "Sil")
        
        action = menu.exec(self.profile_list.mapToGlobal(pos))
        
        if action == play_action:
            self.on_play()
        elif action == folder_action:
            self.open_profile_folder()
        elif action == shortcut_action:
            self.create_profile_shortcut()
        elif action == edit_action:
            self.edit_profile()
        elif action == del_action:
            self.delete_profile()

    def get_selected_profile(self):
        current_item = self.profile_list.currentItem()
        if not current_item: return None, None
        pid = current_item.data(Qt.UserRole)
        return pid, self.profiles.get(pid)

    def _find_installed_engine_version(self, mc_version, loader):
        loader = (loader or "vanilla").lower().strip()
        versions_dir = os.path.join(self.mc_dir, "versions")
        if not os.path.exists(versions_dir):
            return None
        candidates = []
        for d in os.listdir(versions_dir):
            if not os.path.isdir(os.path.join(versions_dir, d)):
                continue
            d_lower = d.lower()
            if loader == "fabric" and "fabric" in d_lower and mc_version in d:
                candidates.append(d)
            elif loader == "neoforge" and "neoforge" in d_lower and mc_version in d:
                candidates.append(d)
            elif loader == "forge" and "forge" in d_lower and "neoforge" not in d_lower and mc_version in d:
                candidates.append(d)
            elif loader == "quilt" and "quilt" in d_lower and mc_version in d:
                candidates.append(d)
            elif loader == "vanilla" and d == mc_version:
                candidates.append(d)
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0]
        return None

    def install_engine_for_profile(self, profile_id, mc_version, loader="fabric"):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = (lang == "en")
        loader = (loader or "fabric").lower().strip()
        mc_version = RuntimeProvisioner.extract_base_version(mc_version, default=mc_version)
        existing = self._find_installed_engine_version(mc_version, loader)
        if existing:
            if profile_id in self.profiles:
                self.profiles[profile_id]["version"] = existing
                self.profiles[profile_id]["loader"] = loader
                self.save_config()
                self.refresh_profile_list()
                item = self._get_profile_item(profile_id)
                if item:
                    self.profile_list.setCurrentItem(item)
                    self.on_profile_selected()
            if hasattr(self, "sound_mgr") and self.sound_mgr:
                self.sound_mgr.play_levelup()
            self.statusBar().showMessage(
                f"{loader.capitalize()} engine ready ({existing})" if en else f"{loader.capitalize()} motoru hazır ({existing})",
                4000
            )
            return

        loader_title = loader.capitalize() if loader != "neoforge" else "NeoForge"

        progress_dlg = QProgressDialog(
            f"Downloading and installing {loader_title} {mc_version} engine..." if en
            else f"{loader_title} {mc_version} oyun motoru indiriliyor ve kuruluyor...",
            "Cancel" if en else "İptal",
            0,
            100,
            self
        )
        progress_dlg.setWindowTitle("Game Engine Installer" if en else "Oyun Motoru Kurulumu")
        progress_dlg.setWindowModality(Qt.WindowModal)
        progress_dlg.setMinimumDuration(0)
        progress_dlg.setValue(0)

        spec = RuntimeSpec(mc_version=mc_version, loader=loader)
        thread = RuntimeInstallThread(spec, mc_dir=self.mc_dir, lang=lang)
        self._active_threads = [t for t in getattr(self, "_active_threads", []) if t.isRunning()]
        self._active_threads.append(thread)

        thread.progress_val.connect(progress_dlg.setValue)
        thread.progress_update.connect(progress_dlg.setLabelText)
        thread.progress_update.connect(lambda s: self.statusBar().showMessage(s, 3000))
        progress_dlg.canceled.connect(thread.cancel)

        def _on_install_done(success, result):
            progress_dlg.close()
            if getattr(thread, "_is_cancelled", False):
                self.statusBar().showMessage("Cancelled" if en else "Motor indirme işlemi iptal edildi.", 3000)
                return
            if success:
                if hasattr(self, "sound_mgr") and self.sound_mgr:
                    self.sound_mgr.play_levelup()
                if profile_id in self.profiles:
                    self.profiles[profile_id]["version"] = result
                    self.profiles[profile_id]["loader"] = loader
                    self.save_config()
                    self.refresh_profile_list()
                    item = self._get_profile_item(profile_id)
                    if item:
                        self.profile_list.setCurrentItem(item)
                        self.on_profile_selected()
                self.statusBar().showMessage(
                    f"{loader_title} {result} ready!" if en else f"{loader_title} {result} hazır!",
                    5000
                )
                QMessageBox.information(
                    self,
                    "Success" if en else "Başarılı",
                    f"{'Game engine successfully installed and bound to profile!' if en else 'Oyun motoru başarıyla kuruldu ve profile bağlandı!'}\n\n"
                    f"{'Version:' if en else 'Sürüm:'} {result}"
                )
            else:
                if hasattr(self, "sound_mgr") and self.sound_mgr:
                    self.sound_mgr.play_error()
                self.statusBar().showMessage("Error" if en else "Motor kurulum hatası", 4000)
                QMessageBox.warning(
                    self,
                    "Installation Warning" if en else "Motor Kurulum Uyarısı",
                    f"{'Failed to install game engine:' if en else 'Oyun motoru kurulurken bir sorun oluştu:'}\n{result}\n\n"
                    f"{'Profile has been created. You can retry installing the engine anytime via the \"Install Engine\" button.' if en else 'Profil oluşturuldu. İnternet bağlantınızı kontrol edip sağ paneldeki \"Motor Kur\" butonundan tekrar deneyebilirsiniz.'}"
                )

        thread.task_finished.connect(_on_install_done)
        thread.start()
        progress_dlg.exec()

    def add_profile(self):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        dialog = AddProfileDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if not data['name'] or not data['version']:
                if hasattr(self, 'sound_mgr') and self.sound_mgr:
                    self.sound_mgr.play_error()
                QMessageBox.warning(
                    self,
                    "Error" if en else "Hata",
                    "Please fill in all fields." if en else "Lütfen tüm alanları doldurun."
                )
                return
            
            raw_version = data['version']
            loader_type = (data.get('loader') or 'fabric').lower()
            base_mc_version = RuntimeProvisioner.extract_base_version(raw_version, default=raw_version)

            pack_name, profile_path = self._generate_unique_profile_name(data['name'])
            os.makedirs(profile_path, exist_ok=True)
            profile_id = str(uuid.uuid4())
                
            self.profiles[profile_id] = {
                "name": pack_name,
                "version": raw_version,
                "loader": loader_type,
                "ram": data['ram'],
                "path": profile_path,
                "icon": ""
            }
            self.save_config()
            self.refresh_profile_list()
            item = self._get_profile_item(profile_id)
            if item:
                self.profile_list.setCurrentItem(item)
                self.on_profile_selected()
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_pop()

            # Otomatik motor indirme ve profil ile eşleştirme
            self.install_engine_for_profile(profile_id, base_mc_version, loader_type)

    def delete_profile(self, confirmed=False):
        pid, pdata = self.get_selected_profile()
        if not pid or not pdata: return
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        if not confirmed:
            reply = QMessageBox.question(
                self,
                'Confirm Delete' if en else 'Emin misiniz?', 
                f"'{pdata.get('name', 'Profil')}' profilini tamamen silmek (tüm modlar ve ayarlar dahil) istediğinize emin misiniz?"
                if not en else
                f"Are you sure you want to permanently delete profile '{pdata.get('name', 'Profile')}' (including all mods and settings)?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        profile_path = pdata.get("path", "")
        if profile_path and os.path.exists(profile_path):
            ok, reason = self._get_profile_store().delete_profile_directory(profile_path)
            if not ok:
                if reason == "outside_containment":
                    QMessageBox.warning(self, "Güvenlik Uyarısı" if not en else "Security Warning", 
                        f"Profil klasörü izin verilen profiller dizini dışında olduğu için silinemedi:\n{profile_path}"
                        if not en else
                        f"Profile folder could not be deleted because it is outside the profiles directory:\n{profile_path}")
                else:
                    real_target = os.path.realpath(profile_path)
                    QMessageBox.warning(self, "Silinemedi" if not en else "Failed to Delete", 
                        f"Profil klasörü silinemedi (başka bir program tarafından kullanılıyor olabilir):\n{real_target}\n\n"
                        "Lütfen klasörü manuel olarak silin, ardından tekrar deneyin."
                        if not en else
                        f"Profile folder could not be deleted (it may be in use by another program):\n{real_target}\n\n"
                        "Please delete the folder manually and try again.")
                return
        
        # Klasör başarıyla silindi (veya zaten yoktu) -> config'den de kaldır
        del self.profiles[pid]
        if hasattr(self, 'sound_mgr') and self.sound_mgr:
            self.sound_mgr.play_break()
        self.save_config()
        self.refresh_profile_list()
        if self.profile_list.count() > 0:
            self.profile_list.setCurrentRow(0)
            self.on_profile_selected()
        else:
            self.on_profile_selected()

    def edit_profile(self):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        pid, pdata = self.get_selected_profile()
        if not pid or not pdata:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "Please select a profile to edit." if en else "Lütfen düzenlemek için bir profil seçin."
            )
            return
            
        dialog = EditProfileDialog(
            pdata.get("name", "Profile" if en else "Profil"),
            pdata.get("ram", 4096),
            pdata.get("icon", ""),
            pdata.get("banner", ""),
            self
        )
        result = dialog.exec()
        if getattr(dialog, "delete_requested", False):
            self.delete_profile(confirmed=True)
            return

        if result == QDialog.Accepted:
            new_name, new_ram, new_icon, new_banner = dialog.get_data()
            if not new_name:
                if hasattr(self, 'sound_mgr') and self.sound_mgr:
                    self.sound_mgr.play_error()
                QMessageBox.warning(
                    self,
                    "Error" if en else "Hata",
                    "Profile name cannot be empty." if en else "Profil adı boş olamaz."
                )
                return
                
            if any(p.get("name") == new_name and p_id != pid for p_id, p in self.profiles.items()):
                if hasattr(self, 'sound_mgr') and self.sound_mgr:
                    self.sound_mgr.play_error()
                QMessageBox.warning(
                    self,
                    "Error" if en else "Hata",
                    "Another profile with this name already exists." if en else "Bu isimde başka bir profil zaten var."
                )
                return
            
            self.profiles[pid]["name"] = new_name
            self.profiles[pid]["ram"] = new_ram
            self.profiles[pid]["icon"] = new_icon
            self.profiles[pid]["banner"] = new_banner
            self.save_config()
            self.refresh_profile_list()
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_levelup()
            
            item = self._get_profile_item(pid)
            if item:
                self.profile_list.setCurrentItem(item)
                self.on_profile_selected()

    def install_from_file(self):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        try:
            from PySide6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Modpack Archive" if en else "Modpack Arşivi Seç",
                "",
                "Modpack Files (*.mrpack *.zip)" if en else "Modpack Dosyaları (*.mrpack *.zip)"
            )
            if not file_path: return
            
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            pack_name, profile_path = self._generate_unique_profile_name(base_name)
            os.makedirs(profile_path, exist_ok=True)
                
            self.pending_modpack = (pack_name, profile_path, None, None, None, 4096)
            
            self.install_modal = EndermanInstallModal(pack_name, self)
            self.install_modal.show()
            
            self.dl_thread = DownloadModpackThread(profile_path, file_path, is_local=True, lang=lang)
            self._active_threads = [t for t in self._active_threads if t.isRunning()]
            self._active_threads.append(self.dl_thread)
            self.install_modal.canceled.connect(self.dl_thread.cancel)
            self.dl_thread.progress_update.connect(self.install_modal.set_status)
            self.dl_thread.progress_val.connect(self.update_progress)
            self.dl_thread.task_finished.connect(self.on_modpack_finished)
            self.dl_thread.start()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error" if en else "Hata",
                f"install_from_file crashed:\n{str(e)}\n\n{traceback.format_exc()}"
                if en else
                f"install_from_file çöktü:\n{str(e)}\n\n{traceback.format_exc()}"
            )

    def update_progress(self, current, total):
        if hasattr(self, "install_modal") and self.install_modal.isVisible():
            self.install_modal.set_progress(current, total)
        elif hasattr(self, "progress_dialog") and self.progress_dialog.isVisible():
            if total == 0:
                self.progress_dialog.setMaximum(0)
                self.progress_dialog.setValue(0)
            else:
                self.progress_dialog.setMaximum(total)
                self.progress_dialog.setValue(current)

    def download_project(self, project):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        if hasattr(self, 'sound_mgr') and self.sound_mgr:
            self.sound_mgr.play_click()
        ptype = project.get("project_type", "mod")
        
        if ptype == "modpack":
            selected_ver = project.get("selected_version_obj")
            selected_ram = project.get("selected_ram", 6144)
            proj_id = project.get("project_id")
            version = self.pack_browser.get_active_version()
            loader = self.pack_browser.get_active_loader()
            policy = CompatibilityPolicy(content_type="modpack", game_version=version, loader=loader)
            
            self.detail_panel.download_btn.setText("Preparing modpack..." if en else "Modpack hazırlanıyor...")
            self.detail_panel.download_btn.setEnabled(False)
            
            safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', project.get("title", "Modpack")).strip()
            if not safe_name:
                safe_name = "Modpack"
            
            pack_name, new_path = self._generate_unique_profile_name(safe_name)
            os.makedirs(new_path, exist_ok=True)
            ver_id = selected_ver.get("id") if isinstance(selected_ver, dict) else None
            self.pending_modpack = (pack_name, new_path, proj_id, ver_id, None, selected_ram)
            
            self.install_modal = EndermanInstallModal(pack_name, self)
            self.install_modal.show()
            
            self.dl_thread = DownloadModpackThread(
                new_path,
                is_local=False,
                project_id=proj_id,
                policy=policy,
                selected_version_obj=selected_ver,
                lang=lang,
            )
            self._active_threads = [t for t in self._active_threads if t.isRunning()]
            self._active_threads.append(self.dl_thread)
            self.install_modal.canceled.connect(self.dl_thread.cancel)
            self.dl_thread.progress_update.connect(self.install_modal.set_status)
            self.dl_thread.progress_val.connect(self.update_progress)
            self.dl_thread.task_finished.connect(self.on_modpack_finished)
            self.dl_thread.start()
            return
            
        # MODS & SHADERS (requires active profile)
        pid, pdata = self.get_selected_profile()
        if not pid:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "Please select a profile from the Profiles tab." if en else "Lütfen Profiller sekmesinden bir profil seçin."
            )
            return
            
        policy = CompatibilityPolicy.for_profile(pdata, ptype)
        self.detail_panel.download_btn.setText("Downloading..." if en else "İndiriliyor...")
        self.detail_panel.download_btn.setEnabled(False)
        self.statusBar().showMessage(
            f"Downloading: {project.get('title', '')}..." if en else f"İndiriliyor: {project.get('title', '')}..."
        )
        
        self.dl_thread = DownloadModThread(
            project_id=project.get("project_id"),
            target_root=pdata["path"],
            policy=policy,
            lang=lang,
        )
        self._active_threads = [t for t in self._active_threads if t.isRunning()]
        self._active_threads.append(self.dl_thread)
        self.dl_thread.task_finished.connect(self.on_download_finished)
        self.dl_thread.start()

    def on_download_finished(self, success, msg):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        self.detail_panel.download_btn.setText("Download to Active Profile" if en else "Aktif Profile İndir")
        self.detail_panel.download_btn.setEnabled(True)
        last_res = getattr(getattr(self, "dl_thread", None), "last_result", None)
        if last_res and getattr(last_res, "already_exists", False):
            QMessageBox.information(self, "Already Installed" if en else "Zaten Mevcut", msg)
            return
        if success:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_levelup()
            self.statusBar().showMessage("Download complete!" if en else "İndirme işlemi tamamlandı!")
            QMessageBox.information(
                self,
                "Success" if en else "Başarılı",
                "Download complete!" if en else "İndirme işlemi tamamlandı!"
            )
        else:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            self.statusBar().showMessage(f"Download error: {msg}" if en else f"İndirme hatası: {msg}")
            QMessageBox.critical(self, "Error" if en else "Hata", msg)

    def on_modpack_finished(self, success, msg, new_version_id):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        try:
            if hasattr(self, "install_modal") and self.install_modal:
                self.install_modal.close()
            if hasattr(self, "progress_dialog") and self.progress_dialog:
                self.progress_dialog.close()
                
            self.detail_panel.download_btn.setText("Install Modpack as New Profile" if en else "Modpack'i Kur ve Profil Oluştur")
            self.detail_panel.download_btn.setEnabled(True)
            pending = getattr(self, "pending_modpack", ("Modpack", ""))
            existing_pid = None
            selected_ram = 6144
            if len(pending) >= 6:
                pack_name, pack_path, proj_id, ver_id, existing_pid, selected_ram = pending[:6]
            elif len(pending) == 5:
                pack_name, pack_path, proj_id, ver_id, existing_pid = pending
            elif len(pending) == 4:
                pack_name, pack_path, proj_id, ver_id = pending
            else:
                pack_name, pack_path = pending[:2]
                proj_id, ver_id = None, None

            resolved_vid = getattr(getattr(self, "dl_thread", None), "resolved_version_id", None)
            if resolved_vid:
                ver_id = resolved_vid

            if success:
                if hasattr(self, 'sound_mgr') and self.sound_mgr:
                    self.sound_mgr.play_challenge_complete()

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
                    new_prof = {
                        "name": pack_name,
                        "version": new_version_id if new_version_id else "1.20.1",
                        "ram": selected_ram if selected_ram else 4096,
                        "path": pack_path,
                        "icon": ""
                    }
                    if proj_id and ver_id:
                        new_prof["project_id"] = proj_id
                        new_prof["version_id"] = ver_id
                        new_prof["source"] = "modrinth"
                    det_loader = self.get_active_profile_loader(new_prof)
                    if det_loader:
                        new_prof["loader"] = det_loader

                    # Add new profile to the top of profiles dict
                    self.profiles = {profile_id: new_prof, **self.profiles}

                self.save_config()
                self.refresh_profile_list()
                
                # Select newly created profile
                item = self._get_profile_item(profile_id)
                if item:
                    self.profile_list.setCurrentItem(item)
                    self.on_profile_selected()
                    
                # Switch to home tab so user can play immediately
                if hasattr(self, "nav_bar"):
                    self.nav_bar.on_nav_click("home", play_sound=False)
                else:
                    self.switch_tab("home")
                    
                QMessageBox.information(self, "Success" if en else "Başarılı", msg)
            else:
                if hasattr(self, 'sound_mgr') and self.sound_mgr:
                    self.sound_mgr.play_error()
                if not existing_pid and pack_path and os.path.isdir(pack_path) and not os.listdir(pack_path):
                    shutil.rmtree(pack_path, ignore_errors=True)
                if "iptal" in msg.lower() or "cancel" in msg.lower():
                    self.statusBar().showMessage(msg, 5000)
                else:
                    QMessageBox.critical(self, "Installation Error" if en else "Kurulum Hatası", msg)
        except Exception as e:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            QMessageBox.critical(
                self,
                "Critical Error" if en else "Kritik Hata",
                f"on_modpack_finished crashed:\n{str(e)}\n\n{traceback.format_exc()}"
                if en else
                f"on_modpack_finished çöktü:\n{str(e)}\n\n{traceback.format_exc()}"
            )

    def update_modpack(self, profile_id, project_id, new_version_id, new_url):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        pdata = self.profiles.get(profile_id)
        if not pdata:
            return
        policy = CompatibilityPolicy.for_profile(pdata, "modpack_update")
        if not policy.effective_loaders:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            QMessageBox.warning(
                self,
                "Update Warning" if en else "Güncelleme Uyarısı",
                "Could not detect mod loader engine for this profile." if en else "Bu profilin mod yükleyici motoru tespit edilemedi."
            )
            return

        reply = QMessageBox.question(
            self,
            'Update' if en else 'Güncelleme',
            "The modpack will be updated. Old mods and config folders will be replaced. Do you want to proceed?"
            if en else
            "Modpaketi güncellenecek. Eski mods ve config klasörleri silinecek. Onaylıyor musunuz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
            
        if hasattr(self, 'sound_mgr') and self.sound_mgr:
            self.sound_mgr.play_click()
            
        self.pending_modpack = (pdata["name"], pdata["path"], project_id, new_version_id, profile_id)
        
        self.install_modal = EndermanInstallModal(
            f"{pdata['name']} ({'Update' if en else 'Güncelleme'})",
            self
        )
        self.install_modal.show()
        
        self.dl_thread = DownloadModpackThread(
            pdata["path"],
            new_url,
            is_local=False,
            is_update=True,
            project_id=project_id,
            policy=policy,
            lang=lang,
        )
        self._active_threads = [t for t in self._active_threads if t.isRunning()]
        self._active_threads.append(self.dl_thread)
        self.install_modal.canceled.connect(self.dl_thread.cancel)
        self.dl_thread.progress_update.connect(self.install_modal.set_status)
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
                for card in getattr(browser, 'cards', []):
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
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        try:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_click()
            pid, pdata = self.get_selected_profile()
            if not pid:
                if hasattr(self, 'sound_mgr') and self.sound_mgr:
                    self.sound_mgr.play_error()
                QMessageBox.warning(
                    self,
                    "Warning" if en else "Uyarı",
                    "Please select a profile." if en else "Lütfen bir profil seçin."
                )
                return
                
            if not hasattr(self, 'ms_login') or not self.ms_login:
                dialog = MicrosoftLoginDialog(self)
                if dialog.exec() == QDialog.Accepted:
                    self.ms_login = dialog.get_account_data()
                    self.save_config()
                    self._continue_launch(pid, pdata)
                return

            # Fast offline check: if network is down, avoid HTTP timeouts and launch immediately with cached session
            if hasattr(self, 'auth_vault') and not self.auth_vault.is_network_available():
                self.statusBar().showMessage(
                    "Offline mode: Launching with cached credentials..." if en
                    else "Çevrimdışı mod: Kayıtlı oturumla başlatılıyor...",
                    3000
                )
                self._continue_launch(pid, pdata)
                return

            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(False)
                self.action_bar.play_btn.setText("Validating login..." if en else "Giriş doğrulanıyor...")
            self.statusBar().showMessage("Validating login..." if en else "Giriş doğrulanıyor...")

            self._token_val_thread = TokenValidationThread(self.ms_login, parent=self)
            self._active_threads = [t for t in self._active_threads if t.isRunning()]
            self._active_threads.append(self._token_val_thread)
            self._token_val_thread.validation_finished.connect(lambda res: self._on_token_validated(res, pid, pdata))
            self._token_val_thread.start()
        except Exception as e:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(True)
                self.action_bar.play_btn.setText("PLAY" if en else "OYNA")
            QMessageBox.critical(self, "Critical Error" if en else "Kritik Hata", f"Error in on_play:\n{str(e)}\n\n{traceback.format_exc()}")

    def _on_token_validated(self, res, pid, pdata):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        self.statusBar().clearMessage()

        status = res.get("status")
        if status == "ok":
            if res.get("refreshed_login"):
                self.ms_login = res["refreshed_login"]
                self.save_config()
            self._continue_launch(pid, pdata)
        elif status == "network_error":
            self.statusBar().showMessage(
                "Network error: Session could not be verified, launching with existing credentials..." if lang == "en"
                else "Ağ hatası: Oturum doğrulanamadı, mevcut bilgilerle başlatılıyor...",
                4000
            )
            self._continue_launch(pid, pdata)
        elif status == "network_error_abort":
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(True)
                self.action_bar.play_btn.setText("PLAY" if lang == "en" else "OYNA")
            QMessageBox.warning(
                self,
                "Connection Error" if lang == "en" else "Bağlantı Hatası",
                f"{'Session expired and could not be refreshed because no internet connection could be established:' if lang == 'en' else 'Oturum süresi dolmuş ancak internet bağlantısı kurulamadığı için yenilenemedi:'}\n{res.get('error_msg')}"
            )
        elif status == "need_login":
            dialog = MicrosoftLoginDialog(self)
            if dialog.exec() == QDialog.Accepted:
                self.ms_login = dialog.get_account_data()
                self.save_config()
                self._continue_launch(pid, pdata)
            else:
                if hasattr(self, 'action_bar'):
                    self.action_bar.play_btn.setEnabled(True)
                    self.action_bar.play_btn.setText("PLAY" if lang == "en" else "OYNA")

    def _continue_launch(self, pid, pdata):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = (lang == "en")
        try:
            def_ram = int((getattr(self, "settings", {}) or {}).get("default_ram", 4096) or 4096)
            ram_mb = int(pdata.get("ram", def_ram) or def_ram)
            options = self.launch_pipeline.build_launch_options(
                auth_session=self.ms_login or {},
                game_directory=pdata["path"],
                ram_mb=ram_mb,
                extra_jvm=(getattr(self, "settings", {}) or {}).get("jvm_args", "").strip(),
                java_path=(getattr(self, "settings", {}) or {}).get("java_path", "").strip() or None,
            )
            
            mc_dir = self.mc_dir
            os.makedirs(mc_dir, exist_ok=True)
            version = pdata["version"]
            
            if not self.launch_pipeline.is_engine_installed(version):
                if self.launch_pipeline.is_loader_version(version):
                    if hasattr(self, 'sound_mgr') and self.sound_mgr:
                        self.sound_mgr.play_error()
                    reply = QMessageBox.question(
                        self,
                        "Engine Missing" if en else "Motor Eksik",
                        (f"The engine selected for this profile ({version}) was not found in the .minecraft folder.\n"
                         f"Would you like to download and install it automatically now?") if en
                        else (f"Bu profil için seçilen motor ({version}) .minecraft klasöründe bulunamadı.\n"
                              f"Şimdi otomatik olarak indirilip kurulsun mu?"),
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes
                    )
                    if reply == QMessageBox.Yes:
                        loader_guess = self.launch_pipeline.detect_loader_type(version)
                        loader_type = pdata.get("loader") or loader_guess
                        base_ver = RuntimeProvisioner.extract_base_version(version, default=version)
                        self.install_engine_for_profile(pid, base_ver, loader_type)
                    if hasattr(self, 'action_bar'):
                        self.action_bar.play_btn.setEnabled(True)
                        self.action_bar.play_btn.setText("PLAY" if en else "OYNA")
                    return
                self.vanilla_thread = DownloadVanillaThread(version, mc_dir, lang=lang)
                self._active_threads = [t for t in self._active_threads if t.isRunning()]
                self._active_threads.append(self.vanilla_thread)

                if hasattr(self, 'action_bar'):
                    self.action_bar.play_btn.setEnabled(False)
                    self.action_bar.play_btn.setText("Downloading..." if en else "İndiriliyor...")
                    self.action_bar.progress.setVisible(True)
                    self.action_bar.progress.setRange(0, 100)
                    self.action_bar.progress.setValue(0)
                    self.vanilla_thread.progress_val.connect(self.action_bar.progress.setValue)

                self.progress_dlg = QProgressDialog(
                    f"Downloading Minecraft {version}..." if en else f"Minecraft {version} indiriliyor...",
                    "Cancel" if en else "İptal",
                    0,
                    100,
                    self
                )
                self.progress_dlg.setWindowTitle("Download" if en else "İndirme")
                self.progress_dlg.setWindowModality(Qt.WindowModal)
                
                self.vanilla_thread.progress_update.connect(self.progress_dlg.setLabelText)
                self.vanilla_thread.progress_update.connect(
                    lambda s: self.statusBar().showMessage(f"Downloading: {s}" if en else f"İndiriliyor: {s}")
                )
                self.vanilla_thread.progress_val.connect(self.progress_dlg.setValue)
                self.progress_dlg.canceled.connect(self.vanilla_thread.cancel)
                
                def _launch_after_vanilla(success, msg):
                    self.progress_dlg.close()
                    if hasattr(self, 'action_bar'):
                        self.action_bar.progress.setVisible(False)
                    if getattr(self.vanilla_thread, '_is_cancelled', False):
                        if hasattr(self, 'action_bar'):
                            self.action_bar.play_btn.setEnabled(True)
                            self.action_bar.play_btn.setText("PLAY" if en else "OYNA")
                        self.statusBar().showMessage(
                            "Download cancelled by user." if en else "İndirme kullanıcı tarafından iptal edildi.",
                            3000
                        )
                        return
                    if success:
                        if hasattr(self, 'sound_mgr') and self.sound_mgr:
                            self.sound_mgr.play_levelup()
                        self._do_launch(options, version, mc_dir, pid, pdata)
                    else:
                        if hasattr(self, 'sound_mgr') and self.sound_mgr:
                            self.sound_mgr.play_error()
                        if hasattr(self, 'action_bar'):
                            self.action_bar.play_btn.setEnabled(True)
                            self.action_bar.play_btn.setText("PLAY" if en else "OYNA")
                        self.statusBar().showMessage(f"Download error: {msg}" if en else f"İndirme hatası: {msg}")
                        QMessageBox.critical(self, "Download Error" if en else "İndirme Hatası", msg)
                    
                self.vanilla_thread.task_finished.connect(_launch_after_vanilla)
                if hasattr(self, 'sound_mgr') and self.sound_mgr:
                    self.sound_mgr.play_click()
                self.vanilla_thread.start()
                self.progress_dlg.exec()
            else:
                self._do_launch(options, version, mc_dir, pid, pdata)
        except Exception as e:
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(True)
                self.action_bar.play_btn.setText("PLAY" if en else "OYNA")
            QMessageBox.critical(
                self,
                "Critical Error" if en else "Kritik Hata",
                f"Error during on_play:\n{str(e)}\n\n{traceback.format_exc()}"
                if en else
                f"on_play sırasında hata:\n{str(e)}\n\n{traceback.format_exc()}"
            )

    def _do_launch(self, options, version, mc_dir, pid, pdata):
        import minecraft_launcher_lib
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        try:
            self._is_game_running = True
            if hasattr(self, 'particle_overlay') and self.particle_overlay:
                self.particle_overlay.pause()
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_launch()

            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(False)
                self.action_bar.play_btn.setText("Starting..." if en else "Başlatılıyor...")
            self.statusBar().showMessage(
                f"Starting Minecraft {version}..." if en else f"Minecraft {version} başlatılıyor..."
            )

            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            session = self.launch_pipeline.launch(
                profile_id=pid,
                profile_data=pdata,
                auth_session=self.ms_login or {},
                settings=getattr(self, "settings", {}),
                creationflags=creationflags,
                options=options,
            )
            process = session.process
            
            self.tracker_thread = PlaytimeTrackerThread(process, pid)
            self._active_threads = [t for t in self._active_threads if t.isRunning()]
            self._active_threads.append(self.tracker_thread)
            self.tracker_thread.tracking_finished.connect(self.on_game_closed)
            self.tracker_thread.start()
            
            QTimer.singleShot(1500, self.on_game_started)
        except Exception as e:
            self._is_game_running = False
            if hasattr(self, 'particle_overlay') and self.particle_overlay:
                if self.isVisible() and not self.isMinimized():
                    self.particle_overlay.resume()
            if hasattr(self, 'sound_mgr') and self.sound_mgr:
                self.sound_mgr.play_error()
            if hasattr(self, 'action_bar'):
                self.action_bar.play_btn.setEnabled(True)
                self.action_bar.play_btn.setText("PLAY" if en else "OYNA")
            self.statusBar().showMessage(f"Launch error: {e}" if en else f"Başlatma hatası: {e}")
            QMessageBox.critical(
                self,
                "Launch Error" if en else "Başlatma Hatası",
                f"Failed to launch game:\n{str(e)}\n\n{traceback.format_exc()}"
                if en else
                f"Oyun başlatılamadı:\n{str(e)}\n\n{traceback.format_exc()}"
            )

    def on_game_started(self):
        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"
        self._is_game_running = True
        if hasattr(self, 'particle_overlay') and self.particle_overlay:
            self.particle_overlay.pause()
        if hasattr(self, '_launch_splash'):
            self._launch_splash.close()
        if hasattr(self, 'action_bar'):
            self.action_bar.play_btn.setText("IN GAME" if en else "OYUNDA")
        self.statusBar().showMessage("Game is running..." if en else "Oyun çalışıyor...")
        on_launch = (getattr(self, "settings", {}) or {}).get("on_launch", "minimize")
        if on_launch == "hide":
            self._hidden_for_game = True
            self.hide()
        elif on_launch == "minimize":
            self.showMinimized()
        
    def on_game_closed(self, pid, elapsed_seconds):
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = lang == "en"
        self._is_game_running = False
        if hasattr(self, 'particle_overlay') and self.particle_overlay:
            if self.isVisible() and not self.isMinimized() and not getattr(self, '_is_closing', False):
                self.particle_overlay.resume()
        if hasattr(self, 'action_bar'):
            self.action_bar.play_btn.setText("PLAY" if en else "OYNA")
            self.action_bar.play_btn.setEnabled(True)
            self.action_bar.progress.setVisible(False)
        self.statusBar().showMessage(
            "Game closed. Playtime saved." if en else "Oyun kapandı. Toplam oynama süresi kaydedildi."
        )

        was_hidden = getattr(self, "_hidden_for_game", False)
        self._hidden_for_game = False

        if (not self.isVisible() and not was_hidden) or getattr(self, '_is_closing', False):
            if pid in self.profiles:
                current = self.profiles[pid].get("playtime", 0)
                self.profiles[pid]["playtime"] = current + elapsed_seconds
                self.save_config()
            return

        self.showNormal()
        self.show()
        if pid in self.profiles:
            current = self.profiles[pid].get("playtime", 0)
            self.profiles[pid]["playtime"] = current + elapsed_seconds
            self.save_config()
            self.on_profile_selected()
            exit_code = getattr(getattr(self, "tracker_thread", None), "exit_code", 0) or 0
            if exit_code != 0 and hasattr(self, "installed_mods_panel"):
                self.installed_mods_panel.show_crash_analysis(exit_code=exit_code)
                self.statusBar().showMessage(
                    f"Game crashed (Code: {exit_code}) — Crash Diagnosis opened."
                    if en else
                    f"Oyun hata ile kapandı (Kod: {exit_code}) — Çökme Analizi açıldı."
                )


    def handle_dungeons_download(self, download):
        # QWebEngineDownloadRequest (PySide6)
        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
        en = (lang == "en")

        raw_name = (download.suggestedFileName() or "").strip()
        filename = os.path.basename(raw_name)
        
        if not filename or not filename.lower().endswith((".pak", ".zip")):
            try:
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            QMessageBox.warning(
                self,
                "Invalid File" if en else "Geçersiz Dosya",
                "This file is not a Dungeons mod (.pak or .zip)!" if en else "Bu dosya bir Dungeons modu (.pak veya .zip) değil!"
            )
            download.cancel()
            return

        resolver = getattr(type(self), "resolve_dungeons_mods_dir", VegaLauncher.resolve_dungeons_mods_dir)
        custom_dir = getattr(self, "settings", {}).get("dungeons_mods_dir")
        target_dir = resolver(custom_dir)
        if not target_dir or not isinstance(target_dir, str):
            target_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "DungeonsMods")

        paks_dir = os.path.dirname(target_dir)
        if not os.path.exists(paks_dir) and not os.path.exists(target_dir):
            try:
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            QMessageBox.warning(
                self,
                "Error" if en else "Hata",
                "Minecraft Dungeons installation was not found on your system." if en else "Minecraft Dungeons kurulumu sisteminizde bulunamadı."
            )
            download.cancel()
            return

        os.makedirs(target_dir, exist_ok=True)
        
        dest_path = os.path.join(target_dir, filename)
        download.setDownloadDirectory(target_dir)
        download.setDownloadFileName(filename)
        
        try:
            SoundManager.get_instance().play_click()
        except Exception:
            pass

        # Setup sleek progress overlay
        self.dun_overlay = CustomProgressOverlay(filename, self)
        self.dun_overlay.show()
        
        def update_dl(received, total):
            if total > 0:
                pct = int((received/total)*100)
                msg = f"Downloading {filename}... %{pct}" if en else f"{filename} indiriliyor... %{pct}"
                self.dun_overlay.update_progress(pct, msg)
                
        download.downloadProgress.connect(update_dl)
        
        def on_finished():
            if download.isFinished():
                self.dun_overlay.title_lbl.setText("Processing..." if en else "İşleniyor...")
                self.dun_overlay.update_progress(100, "Extracting and installing..." if en else "Ayıklanıyor ve kuruluyor...")
                QApplication.processEvents()
                
                if filename.lower().endswith(".zip"):
                    try:
                        extracted_paks = []
                        with zipfile.ZipFile(dest_path, 'r') as zip_ref:
                            real_target = os.path.realpath(target_dir)
                            for zip_info in zip_ref.infolist():
                                if zip_info.filename.lower().endswith('.pak'):
                                    base_name = os.path.basename(zip_info.filename)
                                    if not base_name or ".." in base_name:
                                        continue
                                    target_file_path = os.path.realpath(os.path.join(real_target, base_name))
                                    if not target_file_path.startswith(real_target + os.sep):
                                        continue
                                    zip_info.filename = base_name
                                    zip_ref.extract(zip_info, target_dir)
                                    extracted_paks.append(base_name)
                        os.remove(dest_path)
                        
                        self.dun_overlay.close()
                        if extracted_paks:
                            try:
                                SoundManager.get_instance().play_levelup()
                            except Exception:
                                pass
                            pak_names = "\n".join(extracted_paks)
                            QMessageBox.information(
                                self,
                                "Installation Successful!" if en else "Kurulum Başarılı!",
                                f"PAK files extracted from ZIP and installed to game!\n\nInstalled Mods:\n{pak_names}" if en
                                else f"ZIP içinden PAK dosyaları başarıyla çıkarıldı ve oyuna kuruldu!\n\nKurulan Modlar:\n{pak_names}"
                            )
                        else:
                            try:
                                SoundManager.get_instance().play_error()
                            except Exception:
                                pass
                            QMessageBox.warning(
                                self,
                                "Warning" if en else "Uyarı",
                                f"No '.pak' mods found inside downloaded ZIP {filename}!" if en
                                else f"İndirilen {filename} ZIP dosyasının içinden hiçbir '.pak' uzantılı mod çıkmadı! Bu dosya Dungeons modu olmayabilir."
                            )
                    except Exception as e:
                        self.dun_overlay.close()
                        try:
                            SoundManager.get_instance().play_error()
                        except Exception:
                            pass
                        QMessageBox.critical(
                            self,
                            "Extraction Error" if en else "Çıkarma Hatası",
                            f"Error extracting ZIP archive:\n{e}" if en
                            else f"ZIP dosyası çıkartılırken hata oluştu:\n{e}"
                        )
                else:
                    self.dun_overlay.close()
                    try:
                        SoundManager.get_instance().play_levelup()
                    except Exception:
                        pass
                    QMessageBox.information(
                        self,
                        "Installation Successful!" if en else "Kurulum Başarılı!",
                        f"Mod successfully installed!\n\nFile: {filename}" if en
                        else f"Mod başarıyla kuruldu ve aktif edildi!\n\nDosya: {filename}"
                    )
            else:
                self.dun_overlay.close()

        def _on_download_state(state):
            if state == QWebEngineDownloadRequest.DownloadCompleted:
                on_finished()
            elif state in (QWebEngineDownloadRequest.DownloadCancelled, QWebEngineDownloadRequest.DownloadInterrupted):
                if hasattr(self, 'dun_overlay') and self.dun_overlay:
                    self.dun_overlay.close()
                if state == QWebEngineDownloadRequest.DownloadInterrupted:
                    try:
                        SoundManager.get_instance().play_error()
                    except Exception:
                        pass
                    QMessageBox.warning(
                        self,
                        "Download Interrupted" if en else "İndirme Kesintiye Uğradı",
                        f"Download of {filename} failed or was interrupted." if en else f"{filename} indirmesi kesintiye uğradı veya başarısız oldu."
                    )

        download.stateChanged.connect(_on_download_state)
        download.accept()

    def closeEvent(self, event):
        proc = getattr(getattr(self, 'tracker_thread', None), 'process', None)
        if getattr(self, "_is_game_running", False) and proc and hasattr(proc, 'poll') and proc.poll() is None:
            lang = (getattr(self, "settings", {}) or {}).get("language", "tr")
            en = (lang == "en")
            ans = QMessageBox.question(
                self,
                "Game Running" if en else "Oyun Çalışıyor",
                (
                    "Minecraft is currently running. Closing the launcher will forcefully terminate the game and unsaved progress will be lost.\n\n"
                    "Are you sure you want to exit?"
                ) if en else (
                    "Minecraft şu anda çalışıyor. Başlatıcıyı kapatmak oyunu aniden sonlandıracak ve kaydedilmemiş ilerleme kaybolacaktır.\n\n"
                    "Yine de çıkmak istiyor musunuz?"
                ),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if ans != QMessageBox.Yes:
                if event is not None and hasattr(event, 'ignore'):
                    event.ignore()
                return

        self._is_closing = True
        self.hide()
        close_timer = None
        if hasattr(self, "sound_mgr") and self.sound_mgr and self.sound_mgr.is_enabled():
            try:
                self.sound_mgr.play_door_close()
                from PySide6.QtCore import QElapsedTimer
                close_timer = QElapsedTimer()
                close_timer.start()
            except Exception:
                pass
        if hasattr(self, "settings") and isinstance(self.settings, dict):
            try:
                server_w = getattr(self, 'server_widget', None) or getattr(self, 'server_page', None)
                if server_w and hasattr(server_w, 'server_selector'):
                    curr = server_w.server_selector.currentText()
                    if curr:
                        self.settings["last_server"] = curr
                if not self.isMaximized():
                    self.settings["last_width"] = self.width()
                    self.settings["last_height"] = self.height()
                self.save_config()
            except Exception:
                pass
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
        if hasattr(self, '_api_threads') and isinstance(self._api_threads, (list, set)):
            threads_to_stop.extend(list(self._api_threads))

        dp = getattr(self, 'detail_panel', None)
        if dp:
            threads_to_stop.extend(getattr(dp, 'img_threads', []) + getattr(dp, '_api_threads', []))
        imp = getattr(self, 'installed_mods_panel', None)
        if imp and getattr(imp, '_world_backup_thread', None):
            threads_to_stop.append(imp._world_backup_thread)
        for browser_attr in ['pack_browser', 'mod_browser', 'shader_browser']:
            b = getattr(self, browser_attr, None)
            if b:
                threads_to_stop.extend(getattr(b, '_search_threads', []))

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
                    elif hasattr(th, 'terminate_process'):
                        try:
                            th.terminate_process(timeout=2)
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

        if close_timer is not None:
            while close_timer.elapsed() < 380:
                QApplication.processEvents()
                time.sleep(0.01)

        if hasattr(self, '_single_instance_server') and self._single_instance_server:
            try:
                self._single_instance_server.close()
                from PySide6.QtNetwork import QLocalServer
                QLocalServer.removeServer("vega_launcher_single_instance_ipc")
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


def handle_cli_args(window, args):
    """Parses and executes command line arguments (e.g. --launch or --profile)."""
    if not args or not isinstance(args, list):
        return
    for i, arg in enumerate(args):
        if arg in ("--launch", "-l") and i + 1 < len(args):
            target_pid = args[i + 1]
            item = window._get_profile_item(target_pid)
            if item:
                window.profile_list.setCurrentItem(item)
                window.on_profile_selected()
                QTimer.singleShot(600, window.on_play)
            break
        elif arg in ("--profile", "-p") and i + 1 < len(args):
            target_pid = args[i + 1]
            item = window._get_profile_item(target_pid)
            if item:
                window.profile_list.setCurrentItem(item)
                window.on_profile_selected()
            break


def activate_window(window):
    """Restores from minimized state if needed and brings window to foreground."""
    try:
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()
    except Exception:
        pass


def cleanup_single_instance(server_name="vega_launcher_single_instance_ipc"):
    """Removes the local server socket/named pipe."""
    try:
        from PySide6.QtNetwork import QLocalServer
        QLocalServer.removeServer(server_name)
    except Exception:
        pass


def setup_single_instance(window, server_name="vega_launcher_single_instance_ipc"):
    """
    Sets up a QLocalServer to listen for subsequent launcher launches.
    When a second instance starts, it connects, sends arguments, and this server
    activates the existing window and handles forwarded arguments.
    """
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtCore import QObject
    parent = window if isinstance(window, QObject) else None
    server = QLocalServer(parent)
    QLocalServer.removeServer(server_name)
    if not server.listen(server_name):
        return None

    def on_new_connection():
        conn = server.nextPendingConnection()
        if not conn:
            return

        def on_ready():
            try:
                raw_data = conn.readAll().data()
                if raw_data:
                    args = json.loads(raw_data.decode("utf-8"))
                    handle_cli_args(window, args)
            except Exception as e:
                print(f"[SingleInstance] Argument forwarding error: {e}")
            activate_window(window)
            conn.disconnectFromServer()
            conn.deleteLater()

        conn.readyRead.connect(on_ready)
        if conn.bytesAvailable() > 0:
            on_ready()

    server.newConnection.connect(on_new_connection)
    return server


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName('Vega Launcher')
    app.setOrganizationName('Arcturus')

    SINGLE_INSTANCE_SERVER = "vega_launcher_single_instance_ipc"
    if os.environ.get("VEGA_ALLOW_MULTIPLE") != "1":
        from PySide6.QtNetwork import QLocalSocket
        sock = QLocalSocket()
        sock.connectToServer(SINGLE_INSTANCE_SERVER)
        if sock.waitForConnected(400):
            # Another instance already running: forward CLI arguments and exit cleanly
            payload = json.dumps(sys.argv[1:]).encode("utf-8")
            sock.write(payload)
            sock.waitForBytesWritten(1000)
            sock.disconnectFromServer()
            sys.exit(0)
    
    if getattr(sys, 'frozen', False):
        app_base_dir = os.path.dirname(sys.executable)
    else:
        app_base_dir = os.path.dirname(os.path.abspath(__file__))
    load_custom_fonts(app_base_dir)
    app.setWindowIcon(QIcon(os.path.join(app_base_dir, 'enderman_icon.ico')))
    
    import integrity_check
    is_ok, tampered = integrity_check.verify_integrity()
    if not is_ok:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Güvenlik Uyarısı", f"Bu uygulama yetkisiz olarak değiştirilmiş! Orijinal sürümü indirin: {__author__}")
        sys.exit(1)
        
    window = VegaLauncher()
    window.show()
    window.center_on_screen()

    # CLI arguman kontrolu: Masaustu kisayolundan profile hizli baslatma
    if len(sys.argv) > 1:
        handle_cli_args(window, sys.argv[1:])

    # Tek ornek (Single instance) IPC dinleyicisini baslat
    if os.environ.get("VEGA_ALLOW_MULTIPLE") != "1":
        window._single_instance_server = setup_single_instance(window, SINGLE_INSTANCE_SERVER)
        app.aboutToQuit.connect(lambda: cleanup_single_instance(SINGLE_INSTANCE_SERVER))

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

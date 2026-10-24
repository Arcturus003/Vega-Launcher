__app_name__ = "Vega Launcher"

__author__ = "Arcturus"

__version__ = "2.0.2"

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



# QtWebEngineWidgets deferred to eliminate 0.8s startup freeze and 150MB RAM overhead

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QSizePolicy, 

                               QHBoxLayout, QPushButton, QLabel, QLineEdit, QScrollArea,

                               QStackedWidget, QSplitter, QComboBox, QMessageBox, QDialog, QFormLayout, QSpinBox, QListWidget, QListWidgetItem, QProgressDialog, QProgressBar,

                               QFrame, QGridLayout, QFileDialog, QMenu, QCheckBox, QSlider, QTabWidget)

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

    DEFAULT_CATALOG,

    DEFAULT_CURSEFORGE_CATALOG,

)

from curseforge_api import CurseForgeAPI

from ui_components import NavBar, ActionBar, InstalledModsPanel, safe_open_path

from card_widget import CardWidget, ImageLoaderThread, format_number, _ICON_CACHE

from auth_window import MicrosoftLoginDialog

from vanilla_thread import DownloadVanillaThread

from runtime_provisioner import RuntimeProvisioner, RuntimeSpec, RuntimeInstallThread

from playtime_tracker import PlaytimeTrackerThread

from profile_store import ProfileAndConfigStore, DEFAULT_SETTINGS, ProfileSessionManager

from server_widget import ServerWidget

from sound_manager import SoundManager

from particle_overlay import ParticleOverlay

from launch_pipeline import GameLaunchPipeline, DEFAULT_LAUNCH_PIPELINE

from auth_vault import AuthenticationVault, DEFAULT_AUTH_VAULT

import theme_manager

from prism_meta_provider import DEFAULT_META_PROVIDER, MetaFetchWorker

from prism_instance_importer import PrismInstanceImporter, InstanceImportWorkerThread, PrismInstanceInfo



class TokenValidationThread(QThread):

    validation_finished = Signal(dict)



    def __init__(self, ms_login, parent=None):

        super().__init__(parent)

        self.ms_login = ms_login



    def run(self):

        res = AuthenticationVault.validate_or_refresh_session(self.ms_login)

        self.validation_finished.emit(res)



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

        if getattr(self, "current_banner", None) == preset_key:

            return

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

        if getattr(self, "current_icon", None) == sym:

            return

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

        self.lang = lang

        en = (lang == "en")



        self.setWindowTitle("Add New Profile" if en else "Yeni Profil Ekle")

        self.resize(480, 420)

        if parent:

            self.setStyleSheet(parent.styleSheet())

        layout = QVBoxLayout(self)



        self.tabs = QTabWidget()

        layout.addWidget(self.tabs)



        # Tab 1: Manual Create

        manual_widget = QWidget()

        manual_layout = QVBoxLayout(manual_widget)

        manual_layout.setContentsMargins(8, 8, 8, 8)



        form_layout = QFormLayout()

        self.name_input = QLineEdit()

        self.name_input.setPlaceholderText("e.g.: Zombie Adventure" if en else "Örn: Zombi Macerası")



        self.version_input = QComboBox()

        self.engine_combo = QComboBox()



        filter_layout = QHBoxLayout()

        self.check_snapshots = QCheckBox("Snapshots" if en else "Snapshot'lar")

        self.check_old_versions = QCheckBox("Beta / Alpha" if en else "Eski (Beta/Alpha)")

        filter_layout.addWidget(self.check_snapshots)

        filter_layout.addWidget(self.check_old_versions)

        filter_layout.addStretch()



        self.load_versions()



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

        form_layout.addRow("" if en else "", filter_layout)

        form_layout.addRow("Game Engine:" if en else "Oyun Motoru:", self.engine_combo)

        form_layout.addRow("RAM (MB):", self.ram_input)



        manual_layout.addLayout(form_layout)

        manual_layout.addStretch()

        self.tabs.addTab(manual_widget, "Manual Create" if en else "Manuel Oluştur")



        # Tab 2: Prism / MultiMC Import

        import_widget = QWidget()

        import_layout = QVBoxLayout(import_widget)

        import_layout.setContentsMargins(8, 8, 8, 8)



        import_desc = QLabel(

            "Detected Prism Launcher / MultiMC instances:" if en 

            else "Tespit edilen Prism Launcher / MultiMC profilleri:"

        )

        import_desc.setStyleSheet("color: #AAAAAA; font-size: 12px; margin-bottom: 2px;")

        import_layout.addWidget(import_desc)



        self.instance_list = QListWidget()

        self.instance_list.setSelectionMode(QListWidget.SingleSelection)

        self.instance_list.setStyleSheet("""

            QListWidget {

                background-color: #1A1A22;

                border: 1px solid #333342;

                border-radius: 6px;

                padding: 4px;

            }

            QListWidget::item {

                background-color: #232330;

                border: 1px solid #353545;

                border-radius: 4px;

                padding: 6px 10px;

                margin-bottom: 4px;

                color: #FFFFFF;

            }

            QListWidget::item:selected {

                background-color: #383850;

                border: 1px solid #6E44FF;

            }

            QListWidget::item:hover {

                background-color: #2B2B3B;

            }

        """)

        import_layout.addWidget(self.instance_list)



        self.import_status_lbl = QLabel("")

        self.import_status_lbl.setStyleSheet("color: #00E676; font-size: 11px;")

        self.import_status_lbl.setVisible(False)

        import_layout.addWidget(self.import_status_lbl)



        self.import_progress = QProgressBar()

        self.import_progress.setRange(0, 100)

        self.import_progress.setVisible(False)

        self.import_progress.setFixedHeight(12)

        import_layout.addWidget(self.import_progress)



        import_action_layout = QHBoxLayout()

        self.btn_refresh_instances = QPushButton("Refresh" if en else "Yenile")

        self.btn_do_import = QPushButton("Import Selected" if en else "Seçileni İçe Aktar")

        self.btn_do_import.setStyleSheet("background-color: #6E44FF; color: white; font-weight: bold; padding: 6px 14px;")

        self.btn_do_import.setEnabled(False)

        import_action_layout.addWidget(self.btn_refresh_instances)

        import_action_layout.addStretch()

        import_action_layout.addWidget(self.btn_do_import)

        import_layout.addLayout(import_action_layout)



        self.tabs.addTab(import_widget, "Import from Prism / MultiMC" if en else "Prism / MultiMC'den İçe Aktar")



        # Dialog bottom buttons

        button_layout = QHBoxLayout()

        self.save_btn = QPushButton("Save" if en else "Kaydet")

        self.cancel_btn = QPushButton("Cancel" if en else "İptal")

        self.cancel_btn.setStyleSheet("background-color: #B22222; border-color: #8B0000;")

        button_layout.addWidget(self.save_btn)

        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)



        # Tab events

        self.tabs.currentChanged.connect(self._on_tab_changed)



        self.save_btn.clicked.connect(self._on_save_clicked)

        self.cancel_btn.clicked.connect(self._on_cancel_clicked)

        self.check_snapshots.stateChanged.connect(lambda checked=False: self.load_versions())

        self.check_old_versions.stateChanged.connect(lambda checked=False: self.load_versions())

        self.version_input.currentTextChanged.connect(self._update_compatible_loaders)



        self.btn_refresh_instances.clicked.connect(self.populate_instances)

        self.btn_do_import.clicked.connect(self._start_instance_import)

        self.instance_list.itemSelectionChanged.connect(self._on_instance_selection_changed)

        self.instance_list.itemDoubleClicked.connect(lambda _item: self._start_instance_import())



        # Workers & state

        self._meta_worker = None

        self._import_worker = None

        self.imported_data = None



    def _on_tab_changed(self, index: int):

        if index == 1:

            self.save_btn.setVisible(False)

            if self.instance_list.count() == 0:

                self.populate_instances()

        else:

            self.save_btn.setVisible(True)



    def populate_instances(self):

        self.instance_list.clear()

        en = (self.lang == "en")

        try:

            instances = PrismInstanceImporter.discover_instances()

        except Exception:

            instances = []



        if not instances:

            empty_item = QListWidgetItem("No Prism / MultiMC instances found." if en else "Prism veya MultiMC profili bulunamadı.")

            empty_item.setFlags(Qt.NoItemFlags)

            empty_item.setForeground(QColor("#888888"))

            self.instance_list.addItem(empty_item)

            self.btn_do_import.setEnabled(False)

            return



        for inst in instances:

            item = QListWidgetItem()

            mods_str = f"{inst.mod_count} mods" if en else f"{inst.mod_count} mod"

            worlds_str = f"{inst.world_count} worlds" if en else f"{inst.world_count} dünya"

            loader_cap = inst.loader.capitalize() if inst.loader else "Vanilla"

            item.setText(f"📦 {inst.name}\n   {inst.version} • {loader_cap} • {mods_str} • {worlds_str} • {inst.ram} MB")

            item.setData(Qt.UserRole, inst)

            self.instance_list.addItem(item)



        if self.instance_list.count() > 0:

            self.instance_list.setCurrentRow(0)

            self.btn_do_import.setEnabled(True)



    def _on_instance_selection_changed(self):

        item = self.instance_list.currentItem()

        valid = bool(item and item.data(Qt.UserRole))

        self.btn_do_import.setEnabled(valid)



    def _start_instance_import(self):

        item = self.instance_list.currentItem()

        if not item:

            return

        info = item.data(Qt.UserRole)

        if not info or not isinstance(info, PrismInstanceInfo):

            return



        parent = self.parent()

        if parent and hasattr(parent, "_get_profile_store"):

            target_dir = parent._get_profile_store().profiles_dir

        else:

            target_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), ".vega_launcher", "profiles")

        os.makedirs(target_dir, exist_ok=True)



        self.btn_do_import.setEnabled(False)

        self.btn_refresh_instances.setEnabled(False)

        self.import_progress.setValue(0)

        self.import_progress.setVisible(True)

        self.import_status_lbl.setVisible(True)

        en = (self.lang == "en")

        self.import_status_lbl.setText("Starting import..." if en else "İçe aktarma başlatılıyor...")



        self._import_worker = InstanceImportWorkerThread(info, target_dir, parent=self)

        self._import_worker.progress.connect(self._on_import_progress)

        self._import_worker.finished_import.connect(self._on_import_finished)

        self._import_worker.start()



    def _on_import_progress(self, current: int, total: int, msg: str):

        pct = int((current / max(1, total)) * 100)

        self.import_progress.setValue(pct)

        self.import_status_lbl.setText(msg)



    def _on_import_finished(self, success: bool, profile_dict: object, err_msg: str):

        en = (self.lang == "en")

        if success and isinstance(profile_dict, dict):

            self.imported_data = profile_dict

            self._cleanup_workers()

            try:

                SoundManager.get_instance().play_levelup()

            except Exception:

                pass

            self.accept()

        else:

            self.btn_do_import.setEnabled(True)

            self.btn_refresh_instances.setEnabled(True)

            self.import_status_lbl.setText(f"Error: {err_msg}" if en else f"Hata: {err_msg}")

            self.import_status_lbl.setStyleSheet("color: #FF5252; font-size: 11px;")

            QMessageBox.warning(self, "Import Error" if en else "İçe Aktarma Hatası", err_msg)



    def showEvent(self, event):

        super().showEvent(event)

        if self._meta_worker is None:

            self._start_meta_fetch()



    def _start_meta_fetch(self):

        self._meta_worker = MetaFetchWorker(DEFAULT_META_PROVIDER, parent=self)

        self._meta_worker.versions_ready.connect(self._on_meta_versions_ready)

        self._meta_worker.start()



    def _on_meta_versions_ready(self, _versions):

        self.load_versions()



    def _cleanup_workers(self):

        if self._meta_worker and self._meta_worker.isRunning():

            try:

                self._meta_worker.versions_ready.disconnect()

            except Exception:

                pass

            self._meta_worker.quit()

            self._meta_worker.wait(500)

            self._meta_worker = None



        if self._import_worker and self._import_worker.isRunning():

            try:

                self._import_worker.progress.disconnect()

                self._import_worker.finished_import.disconnect()

            except Exception:

                pass

            self._import_worker.cancel()

            self._import_worker.quit()

            self._import_worker.wait(500)

            self._import_worker = None



    def _on_save_clicked(self):

        self._cleanup_workers()

        try:

            SoundManager.get_instance().play_click()

        except Exception:

            pass

        self.accept()



    def _on_cancel_clicked(self):

        self._cleanup_workers()

        try:

            SoundManager.get_instance().play_click()

        except Exception:

            pass

        self.reject()



    def reject(self):

        self._cleanup_workers()

        super().reject()



    def closeEvent(self, event):

        self._cleanup_workers()

        super().closeEvent(event)



    def load_versions(self):

        curr = self.version_input.currentText().strip()

        self.version_input.blockSignals(True)

        self.version_input.clear()



        discovered = []

        mc_dir = getattr(self.parent(), "mc_dir", None) or os.path.join(os.getenv("APPDATA", ""), ".minecraft")

        versions_dir = os.path.join(mc_dir, "versions")

        if os.path.exists(versions_dir):

            for d in os.listdir(versions_dir):

                if os.path.isdir(os.path.join(versions_dir, d)):

                    base_v = RuntimeProvisioner.extract_base_version(d, default=None)

                    if base_v and base_v not in discovered:

                        discovered.append(base_v)



        show_snaps = getattr(self, "check_snapshots", None) and self.check_snapshots.isChecked()

        show_old = getattr(self, "check_old_versions", None) and self.check_old_versions.isChecked()



        versions = DEFAULT_META_PROVIDER.filter_versions(

            show_snapshots=bool(show_snaps),

            show_old=bool(show_old),

            local_versions=discovered,

        )



        self.version_input.addItems(versions)



        # Restore previous selection or default to 1.20.1

        if curr and self.version_input.findText(curr) >= 0:

            self.version_input.setCurrentIndex(self.version_input.findText(curr))

        else:

            idx = self.version_input.findText("1.20.1")

            if idx >= 0:

                self.version_input.setCurrentIndex(idx)



        self.version_input.setEditable(True)

        self.version_input.blockSignals(False)

        self._update_compatible_loaders()



    def _update_compatible_loaders(self, _text: str = ""):

        mc_ver = self.version_input.currentText().strip()

        curr_loader = self.engine_combo.currentData() or "fabric"

        self.engine_combo.blockSignals(True)

        self.engine_combo.clear()



        loaders = DEFAULT_META_PROVIDER.get_compatible_loaders(mc_ver, lang=getattr(self, "lang", "tr"))

        for label, val in loaders:

            self.engine_combo.addItem(label, val)



        idx = self.engine_combo.findData(curr_loader)

        if idx >= 0:

            self.engine_combo.setCurrentIndex(idx)

        else:

            self.engine_combo.setCurrentIndex(0)

        self.engine_combo.blockSignals(False)



    def get_data(self):

        if self.imported_data:

            return {

                "name": self.imported_data.get("name", ""),

                "version": self.imported_data.get("version", ""),

                "loader": self.imported_data.get("loader", "vanilla"),

                "ram": self.imported_data.get("ram", 4096),

                "imported_path": self.imported_data.get("path", "")

            }

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



# Content browser decoupled into content_browser.py (capped_urls = urls_to_load[:6])

from content_browser import (

    DetailPanel,

    ModrinthBrowser,

    ContentBrowserPanel,

    _MODRINTH_CACHE,

    _MODRINTH_CACHE_TTL,

)





class VegaInstallModal(QDialog):

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

        title_lbl = QLabel("Vega Modpack Installer" if en else "Vega Modpack Yükleyici")

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





EndermanInstallModal = VegaInstallModal





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





_MAIN_FONTS_LOADED = False



def load_custom_fonts(base_dir=None):

    """Loads bundled Minecraft pixel fonts (Minecraft Five, Minecraft) into QFontDatabase."""

    global _MAIN_FONTS_LOADED

    if _MAIN_FONTS_LOADED:

        return

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

        _MAIN_FONTS_LOADED = True

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

        self._is_launching = False

        self._active_selected_profile_id = None

        self._current_tab_key = None



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

        if not hasattr(self, "profile_session"):

            self.profile_session = ProfileSessionManager(self._get_profile_store(), self.profiles, self)

        else:

            self.profile_session.set_profiles(self.profiles)



    def save_config(self):

        if hasattr(self, "profile_session"):

            self.profile_session.save(

                getattr(self, "ms_login", {}),

                getattr(self, "settings", {}),

                sync_standard=False,

            )

        else:

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

        if hasattr(self, "profile_session"):

            self.profile_session.update_runtime(

                profile_id, version, loader, getattr(self, "ms_login", {}), getattr(self, "settings", {})

            )

            self.on_profile_selected(force=True)

        elif profile_id in getattr(self, "profiles", {}):

            self.profiles[profile_id]["version"] = version

            self.profiles[profile_id]["loader"] = str(loader).lower()

            self.save_config()

            self.on_profile_selected(force=True)





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

        profile_layout.setSpacing(16)



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

        hero_layout.setContentsMargins(24, 16, 24, 16)

        hero_layout.setSpacing(16)



        self.hero_icon_box = QFrame()

        self.hero_icon_box.setFixedSize(62, 62)

        self.hero_icon_box.setCursor(Qt.PointingHandCursor)

        self.hero_icon_box.setToolTip("Profili Düzenle / Simgeyi Değiştir")

        self.hero_icon_box.setStyleSheet("QFrame { background: rgba(139, 92, 246, 0.18); border: 1px solid rgba(168, 85, 247, 0.45); border-radius: 12px; } QFrame:hover { background: rgba(139, 92, 246, 0.32); border-color: #C084FC; }")

        self.hero_icon_box.mousePressEvent = lambda e: self.edit_profile() if e.button() == Qt.LeftButton else None

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

        self.bed_btn.clicked.connect(lambda x=None: safe_open_path("shell:AppsFolder\\Microsoft.MinecraftUWP_8wekyb3d8bbwe!App"))

        bed_layout.addStretch()

        bed_layout.addWidget(bed_lbl)

        bed_layout.addWidget(self.bed_desc)

        bed_layout.addWidget(self.bed_btn, alignment=Qt.AlignCenter)

        bed_layout.addStretch()

        self.stack.addWidget(self.bedrock_page)

        

        # Dungeons placeholders (compatibility & localization)

        self.dun_desc = QLabel("Zindanları keşfet, efsanevi silahlar kuşan ve Arch-Illager'ı yen!")

        self.dun_btn = QPushButton("ZİNDANA GİR")

        self.dun_mods_btn = QPushButton("Kurulu Modlar")

        

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

        self.action_bar.folder_btn.clicked.connect(lambda x=None: safe_open_path(self.mc_dir))

        content_layout.addWidget(self.action_bar)

        

        main_layout.addLayout(content_layout)

        

        self.nav_bar.on_nav_click("home", play_sound=False)

        self.switch_tab("home")

        self.on_profile_selected()

        self.detail_panel.hide()

        

        # Ambient Particle Canvas Overlay

        self.particle_overlay = ParticleOverlay(self)

        self.particle_overlay.set_enabled(self.settings.get("particles_enabled", True))

        t_key = self.settings.get("theme", "electric_amethyst")

        self.particle_overlay.set_palette(theme_manager.get_theme(t_key).get("particles", []))

        self.particle_overlay.set_preset(self.settings.get("particle_preset", "portal"))

        self.particle_overlay.set_opacity_percent(self.settings.get("particle_opacity", 50))

        self.particle_overlay.resize(self.size())

        self.particle_overlay.raise_()



        # Durum çubuğu

        self.statusBar().setStyleSheet("color: #888; background: rgba(15,15,20,0.9); border-top: 1px solid #333;")

        self.statusBar().showMessage("Vega Launcher hazır — Profil seçip OYNA'ya basın!")

        self.start_update_checker()



    def resizeEvent(self, event):

        super().resizeEvent(event)

        if hasattr(self, 'particle_overlay') and self.particle_overlay:

            self.particle_overlay.resize(self.size())

            self.particle_overlay.raise_()



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

        from PySide6.QtWidgets import QGridLayout, QFileDialog, QFrame, QLayout

        page = QWidget()

        outer_layout = QVBoxLayout(page)

        outer_layout.setContentsMargins(24, 20, 24, 20)

        outer_layout.setSpacing(16)



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

                border-top: 1px solid #34343E;

                border-bottom: 2px solid #141416;

                border-radius: 6px;

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

            QPushButton#BtnAccLogin {

                background-color: #7C3AED;

                color: #FFFFFF;

                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;

                font-size: 11px;

                font-weight: 700;

                border-radius: 4px;

                padding: 7px 14px;

                border: 1px solid #5B21B6;

                border-top: 1.5px solid #A78BFA;

                border-left: 1px solid #8B5CF6;

                border-right: 1px solid #6D28D9;

                border-bottom: 2.5px solid #4C1D95;

            }

            QPushButton#BtnAccLogin:hover {

                background-color: #8B5CF6;

                border-top: 1.5px solid #C084FC;

            }

            QPushButton#BtnAccLogin:pressed {

                background-color: #6D28D9;

                padding-top: 8px;

                padding-bottom: 6px;

            }

            QPushButton#BtnAccLogout {

                background-color: #222228;

                color: #CBD5E1;

                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;

                font-size: 11px;

                font-weight: 700;

                border-radius: 4px;

                padding: 7px 14px;

                border: 1px solid #282830;

                border-top: 1.5px solid #3E3E48;

                border-bottom: 2.5px solid #18181C;

            }

            QPushButton#BtnAccLogout:hover {

                background-color: rgba(239, 68, 68, 0.12);

                border: 1px solid #EF4444;

                border-top: 1.5px solid #F87171;

                border-bottom: 2.5px solid #7F1D1D;

                color: #FCA5A5;

            }

            QPushButton#BtnAccLogout:pressed {

                background-color: #18181C;

                padding-top: 8px;

                padding-bottom: 6px;

            }

            QPushButton#BtnCheckUpdates {

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

            QPushButton#BtnCheckUpdates:hover {

                background-color: #8B5CF6;

                border-top: 1.5px solid #C084FC;

            }

            QPushButton#BtnCheckUpdates:pressed {

                background-color: #6D28D9;

                border-top: 2.5px solid #4C1D95;

                border-bottom: 1px solid #A78BFA;

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

            lay.setSpacing(14)

            hdr = QLabel(title_text)

            hdr.setObjectName("SettingsCardHeader")

            hdr.setStyleSheet(f"font-family: 'Minecraft Five', 'Segoe UI', sans-serif; font-size: 12px; font-weight: bold; color: {t_data.get('glow', '#C084FC')}; letter-spacing: 0.8px; background: transparent; border: none; margin-bottom: 2px;")

            lay.addWidget(hdr)

            return card, lay, hdr



        label_style = "color: #94A3B8; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; background: transparent; border: none;"



        def _add_field(parent_layout, label_widget, control_or_layout):

            box = QVBoxLayout()

            box.setSpacing(4)

            box.setContentsMargins(0, 0, 0, 0)

            if label_widget is not None:

                label_widget.setStyleSheet(label_style)

                box.addWidget(label_widget)

            if isinstance(control_or_layout, QLayout):

                box.addLayout(control_or_layout)

            elif control_or_layout is not None:

                box.addWidget(control_or_layout)

            parent_layout.addLayout(box)



        # --- KART 1: Genel, Dil & Pencere Boyutu ---

        card_gen, lay_gen, self.lbl_card_gen_hdr = _make_settings_card("GENEL, DİL & PENCERE")



        self.lbl_lang_field = QLabel("Arayüz Dili / Language:")

        self.combo_lang = QComboBox()

        self.combo_lang.addItem("Türkçe (TR)", "tr")

        self.combo_lang.addItem("English (EN)", "en")

        idx_lang = self.combo_lang.findData(self.settings.get("language", "tr"))

        if idx_lang >= 0:

            self.combo_lang.setCurrentIndex(idx_lang)

        self.combo_lang.currentIndexChanged.connect(self._on_settings_changed)

        _add_field(lay_gen, self.lbl_lang_field, self.combo_lang)



        self.lbl_winsize_field = QLabel("Açılış & Pencere Boyutu:")

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

        _add_field(lay_gen, self.lbl_winsize_field, self.combo_winsize)



        self.lbl_onlaunch_field = QLabel("Oyun Başladığında Başlatıcı:")

        self.combo_onlaunch = QComboBox()

        self.combo_onlaunch.addItem("Simge Durumuna Küçült", "minimize")

        self.combo_onlaunch.addItem("Açık Tut", "keep")

        self.combo_onlaunch.addItem("Tamamen Gizle (Oyun Kapanınca Aç)", "hide")

        idx_ol = self.combo_onlaunch.findData(self.settings.get("on_launch", "minimize"))

        if idx_ol >= 0:

            self.combo_onlaunch.setCurrentIndex(idx_ol)

        self.combo_onlaunch.currentIndexChanged.connect(self._on_settings_changed)

        _add_field(lay_gen, self.lbl_onlaunch_field, self.combo_onlaunch)

        lay_gen.addStretch()



        # --- KART 2: Oyun & Performans (Java / RAM) ---

        card_perf, lay_perf, self.lbl_card_perf_hdr = _make_settings_card("OYUN & PERFORMANS (JAVA / RAM)")



        self.lbl_defram_field = QLabel("Varsayılan RAM Miktarı (MB):")

        ram_row = QHBoxLayout()

        ram_row.setSpacing(8)

        self.spin_default_ram = QSpinBox()

        self.spin_default_ram.setRange(1024, 32768)

        self.spin_default_ram.setSingleStep(512)

        self.spin_default_ram.setValue(int(self.settings.get("default_ram", 4096) or 4096))

        self.spin_default_ram.valueChanged.connect(self._on_settings_changed)

        self.btn_apply_ram_all = QPushButton("Tüm Profillere Uygula")

        self.btn_apply_ram_all.setCursor(Qt.PointingHandCursor)

        self.btn_apply_ram_all.clicked.connect(lambda checked=False: self._apply_ram_to_all_profiles())

        ram_row.addWidget(self.spin_default_ram, 1)

        ram_row.addWidget(self.btn_apply_ram_all)

        _add_field(lay_perf, self.lbl_defram_field, ram_row)



        self.lbl_java_field = QLabel("Özel Java Yolu (Boş = Otomatik):")

        java_row = QHBoxLayout()

        java_row.setSpacing(8)

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

        _add_field(lay_perf, self.lbl_java_field, java_row)



        self.lbl_jvm_field = QLabel("Ek JVM Argümanları:")

        self.line_jvm_args = QLineEdit(self.settings.get("jvm_args", ""))

        self.line_jvm_args.setPlaceholderText("Örn: -XX:+UseG1GC -Dsun.rmi.dgc.server.gcInterval=2147483646")

        self.line_jvm_args.textChanged.connect(self._on_settings_changed)

        _add_field(lay_perf, self.lbl_jvm_field, self.line_jvm_args)



        self.lbl_temurin_field = QLabel("Dahili Java Runtimes (Adoptium Temurin):")

        self.temurin_container = QFrame()

        self.temurin_container.setObjectName("TemurinContainer")

        self.temurin_container.setStyleSheet("""

            QFrame#TemurinContainer {

                background: rgba(15, 23, 42, 0.45);

                border: 1px solid rgba(255, 255, 255, 0.08);

                border-radius: 8px;

                padding: 6px;

            }

        """)

        lay_tem = QVBoxLayout(self.temurin_container)

        lay_tem.setContentsMargins(10, 8, 10, 8)

        lay_tem.setSpacing(6)



        self._temurin_rows = {}

        for major, label_txt, sub_txt in [

            (8, "Java 8 LTS", "MC <= 1.16.5"),

            (17, "Java 17 LTS", "MC 1.17 - 1.20.4"),

            (21, "Java 21 LTS", "MC 1.20.5+"),

        ]:

            r_lay = QHBoxLayout()

            r_lay.setSpacing(10)



            lbl_title = QLabel(f"<b>{label_txt}</b> <span style='color: #64748B;'>({sub_txt})</span>")

            lbl_title.setStyleSheet("font-size: 11px; color: #E2E8F0; background: transparent;")

            lbl_title.setTextFormat(Qt.RichText)



            lbl_status = QLabel("Kontrol ediliyor...")

            lbl_status.setStyleSheet("font-size: 11px; color: #94A3B8; background: transparent;")



            btn_dl = QPushButton("İndir")

            btn_dl.setCursor(Qt.PointingHandCursor)

            btn_dl.setStyleSheet("""

                QPushButton {

                    background: rgba(59, 130, 246, 0.15);

                    color: #60A5FA;

                    border: 1px solid rgba(59, 130, 246, 0.3);

                    border-radius: 4px;

                    padding: 3px 10px;

                    font-size: 11px;

                    font-weight: 600;

                }

                QPushButton:hover {

                    background: rgba(59, 130, 246, 0.3);

                    border-color: #60A5FA;

                }

            """)

            btn_dl.clicked.connect(lambda checked=False, m=major: self._install_temurin_manual(m))



            r_lay.addWidget(lbl_title, 2)

            r_lay.addWidget(lbl_status, 3)

            r_lay.addWidget(btn_dl, 0)

            lay_tem.addLayout(r_lay)



            self._temurin_rows[major] = {

                "title": lbl_title,

                "status": lbl_status,

                "btn": btn_dl,

                "sub_txt": sub_txt,

                "label_txt": label_txt,

            }



        _add_field(lay_perf, self.lbl_temurin_field, self.temurin_container)

        lay_perf.addStretch()



        # --- KART 3: Microsoft Hesabı, Görünüm & Sesler ---

        card_acc, lay_acc, self.lbl_card_acc_hdr = _make_settings_card("HESAP, GÖRÜNÜM & SESLER")



        self.lbl_acc_status = QLabel("")

        self.lbl_acc_status.setStyleSheet("font-size: 14px; font-weight: bold; color: white; background: transparent;")

        lay_acc.addWidget(self.lbl_acc_status)



        acc_btn_row = QHBoxLayout()

        acc_btn_row.setSpacing(8)

        self.btn_acc_login = QPushButton("Giriş Yap / Hesap Değiştir")

        self.btn_acc_login.setObjectName("BtnAccLogin")

        self.btn_acc_login.setCursor(Qt.PointingHandCursor)

        self.btn_acc_login.clicked.connect(lambda checked=False: self._settings_login_microsoft())



        self.btn_acc_logout = QPushButton("Oturumu Kapat")

        self.btn_acc_logout.setObjectName("BtnAccLogout")

        self.btn_acc_logout.setCursor(Qt.PointingHandCursor)

        self.btn_acc_logout.clicked.connect(lambda checked=False: self._settings_logout_microsoft())

        acc_btn_row.addWidget(self.btn_acc_login, 1)

        acc_btn_row.addWidget(self.btn_acc_logout)

        _add_field(lay_acc, None, acc_btn_row)



        # Theme Selector

        self.lbl_theme_field = QLabel("Arayüz Teması / Vurgu:")

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

        _add_field(lay_acc, self.lbl_theme_field, self.combo_theme)



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

        _add_field(lay_acc, None, part_row)



        part_opacity_row = QHBoxLayout()

        part_opacity_row.setSpacing(8)

        self.lbl_particle_opacity = QLabel("Saydamlık Düzeyi:" if curr_lang == "tr" else "Opacity Level:")

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

        _add_field(lay_acc, None, part_opacity_row)



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

        _add_field(lay_acc, None, vol_row)



        self.lbl_bg_field = QLabel("Özel Arka Plan Görseli:")

        bg_row = QHBoxLayout()

        bg_row.setSpacing(8)

        self.btn_choose_bg = QPushButton("Arka Plan Seç...")

        self.btn_choose_bg.setCursor(Qt.PointingHandCursor)

        self.btn_choose_bg.clicked.connect(lambda checked=False: self._choose_custom_bg())

        self.btn_reset_bg = QPushButton("Varsayılan Arka Plan")

        self.btn_reset_bg.setCursor(Qt.PointingHandCursor)

        self.btn_reset_bg.clicked.connect(lambda checked=False: self._reset_custom_bg())

        bg_row.addWidget(self.btn_choose_bg)

        bg_row.addWidget(self.btn_reset_bg)

        _add_field(lay_acc, self.lbl_bg_field, bg_row)

        lay_acc.addStretch()



        # --- KART 4: Depolama & Güncelleme / Hakkında ---

        card_sys, lay_sys, self.lbl_card_sys_hdr = _make_settings_card("DEPOLAMA & GÜNCELLEME")



        folder_grid = QGridLayout()

        folder_grid.setSpacing(8)

        self.btn_f_mc = QPushButton(".minecraft Klasörü")

        self.btn_f_mc.setCursor(Qt.PointingHandCursor)

        self.btn_f_mc.clicked.connect(lambda checked=False: (os.makedirs(self.mc_dir, exist_ok=True), safe_open_path(self.mc_dir)))

        self.btn_f_prof = QPushButton("Profiller Klasörü")

        self.btn_f_prof.setCursor(Qt.PointingHandCursor)

        self.btn_f_prof.clicked.connect(lambda checked=False: (os.makedirs(self.profiles_dir, exist_ok=True), safe_open_path(self.profiles_dir)))

        self.btn_f_srv = QPushButton("Sunucular Klasörü")

        self.btn_f_srv.setCursor(Qt.PointingHandCursor)

        self.btn_f_srv.clicked.connect(lambda checked=False: (os.makedirs(os.path.join(self.data_dir, "servers"), exist_ok=True), safe_open_path(os.path.join(self.data_dir, "servers"))))

        self.btn_clear_cache = QPushButton("Log & Önbellek Temizle")

        self.btn_clear_cache.setCursor(Qt.PointingHandCursor)

        self.btn_clear_cache.clicked.connect(lambda checked=False: self._clear_launcher_cache())

        folder_grid.addWidget(self.btn_f_mc, 0, 0)

        folder_grid.addWidget(self.btn_f_prof, 0, 1)

        folder_grid.addWidget(self.btn_f_srv, 1, 0)

        folder_grid.addWidget(self.btn_clear_cache, 1, 1)

        lay_sys.addLayout(folder_grid)



        ver_row = QHBoxLayout()

        ver_row.setSpacing(8)

        self.lbl_version_info = QLabel(f"Vega Launcher v{__version__} — by {__author__}")

        self.lbl_version_info.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 600; background: transparent;")

        self.btn_check_updates = QPushButton("GÜNCELLEMELERİ KONTROL ET")

        self.btn_check_updates.setObjectName("BtnCheckUpdates")

        self.btn_check_updates.setCursor(Qt.PointingHandCursor)

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

        self._refresh_temurin_ui()

        return page



    def _refresh_temurin_ui(self):

        if not hasattr(self, "_temurin_rows"):

            return

        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")

        en = (lang == "en")

        try:

            from java_provisioner import DEFAULT_JAVA_PROVISIONER

            statuses = DEFAULT_JAVA_PROVISIONER.get_all_statuses(self.mc_dir)

            for major, info in self._temurin_rows.items():

                st = statuses.get(major, {})

                installed = st.get("installed", False)

                is_portable = st.get("is_portable", False)

                ver_str = st.get("version_str") or f"{major}.x"

                lbl_title = info["title"]

                lbl_status = info["status"]

                btn = info["btn"]

                sub = info["sub_txt"]

                lbl_txt = info["label_txt"]



                lbl_title.setText(f"<b>{lbl_txt}</b> <span style='color: #64748B;'>({sub})</span>")

                if installed:

                    if is_portable:

                        lbl_status.setText(

                            f"<span style='color: #4ADE80; font-weight: bold;'>✓ {'Installed' if en else 'Kurulu'}</span> <span style='color: #94A3B8;'>({ver_str})</span>"

                        )

                        btn.setText("Reinstall" if en else "Yeniden Kur")

                    else:

                        lbl_status.setText(

                            f"<span style='color: #38BDF8; font-weight: bold;'>✓ {'System' if en else 'Sistem'}</span> <span style='color: #94A3B8;'>({ver_str})</span>"

                        )

                        btn.setText("Install Local" if en else "Dahili Kur")

                else:

                    lbl_status.setText(

                        f"<span style='color: #F87171; font-weight: bold;'>✗ {'Not Found' if en else 'Yüklü Değil'}</span>"

                    )

                    btn.setText("Download" if en else "İndir")

        except Exception:

            pass



    def _install_temurin_manual(self, major: int):

        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"

        from java_provisioner import JavaDownloadThread

        self.java_manual_thread = JavaDownloadThread(

            target_major=major,

            mc_dir=self.mc_dir,

            lang="en" if en else "tr",

            parent=self,

        )

        self._active_threads = [t for t in self._active_threads if t.isRunning()]

        self._active_threads.append(self.java_manual_thread)



        progress_dlg = QProgressDialog(

            f"Downloading Eclipse Temurin Java {major}..." if en else f"Adoptium Temurin Java {major} indiriliyor...",

            "Cancel" if en else "İptal",

            0,

            100,

            self,

        )

        progress_dlg.setWindowTitle("Adoptium Java Provisioner" if en else "Dahili Java Kurulumu")

        progress_dlg.setWindowModality(Qt.WindowModal)



        self.java_manual_thread.progress_status.connect(progress_dlg.setLabelText)

        self.java_manual_thread.progress_status.connect(

            lambda s: self.statusBar().showMessage(s, 2000)

        )

        self.java_manual_thread.progress_val.connect(

            lambda cur, tot: progress_dlg.setValue(int(cur * 100 / tot) if tot > 0 else 0)

        )

        progress_dlg.canceled.connect(self.java_manual_thread.cancel)



        def _on_manual_done(success: bool, path_or_err: str):

            progress_dlg.close()

            self._refresh_temurin_ui()

            if getattr(self.java_manual_thread, "_is_cancelled", False):

                self.statusBar().showMessage("Download cancelled." if en else "İndirme iptal edildi.", 3000)

                return

            if success:

                if hasattr(self, "sound_mgr") and self.sound_mgr:

                    self.sound_mgr.play_levelup()

                self.statusBar().showMessage(

                    f"Java {major} installed to {path_or_err}" if en else f"Java {major} başarıyla kuruldu: {path_or_err}",

                    4000

                )

                QMessageBox.information(

                    self,

                    "Java Provisioned" if en else "Java Kurulumu Tamamlandı",

                    f"Adoptium Eclipse Temurin Java {major} has been successfully installed and verified!\nPath: {path_or_err}"

                    if en else

                    f"Adoptium Eclipse Temurin Java {major} başarıyla indirildi ve kuruldu!\nDosya: {path_or_err}",

                )

            else:

                if hasattr(self, "sound_mgr") and self.sound_mgr:

                    self.sound_mgr.play_error()

                QMessageBox.critical(

                    self,

                    "Java Download Error" if en else "Java İndirme Hatası",

                    f"Failed to install Java {major}:\n{path_or_err}"

                    if en else

                    f"Java {major} indirilirken hata oluştu:\n{path_or_err}",

                )



        self.java_manual_thread.download_finished.connect(_on_manual_done)

        self.java_manual_thread.start()

        progress_dlg.exec()



    def _refresh_account_status_label(self):

        acc_name = (getattr(self, "ms_login", {}) or {}).get("name")

        if hasattr(self, "nav_bar") and hasattr(self.nav_bar, "update_user"):

            self.nav_bar.update_user(acc_name, bool(acc_name))

        if not hasattr(self, "lbl_acc_status"):

            return

        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")

        if acc_name:

            self.lbl_acc_status.setText(f"{'Active Account' if lang == 'en' else 'Aktif Hesap'}: {acc_name}")

            self.lbl_acc_status.setStyleSheet("font-size: 13px; font-weight: 700; color: #34D399; background: transparent;")

        else:

            self.lbl_acc_status.setText("Not Logged In (Microsoft)" if lang == "en" else "Giriş Yapılmadı (Microsoft Hesabı Yok)")

            self.lbl_acc_status.setStyleSheet("font-size: 13px; font-weight: 600; color: #94A3B8; background: transparent;")



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

            if hasattr(self, "lbl_temurin_field"):

                self.lbl_temurin_field.setText("Adoptium Temurin Java Runtimes:" if en else "Dahili Java Runtimes (Adoptium Temurin):")

                self._refresh_temurin_ui()

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

            self.on_profile_selected(force=True)

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

        self.on_profile_selected(force=True)

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

            safe_open_path(pdata["path"])

        else:

            safe_open_path(self.profiles_dir)



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

        key = "home" if key == "profiles" else key

        if getattr(self, "_current_tab_key", None) == key:

            return

        self._current_tab_key = key

        if hasattr(self, "nav_bar") and hasattr(self.nav_bar, "set_active_tab"):

            self.nav_bar.set_active_tab(key)

        mapping = {"home": 0, "packs": 1, "mods": 2, "shaders": 3, "bedrock_home": 4, "server": 5, "settings": 6}

        idx = mapping.get(key, 0)

        self.stack.setCurrentIndex(idx)

        if hasattr(self, 'particle_overlay') and self.particle_overlay:

            if not self.isMinimized() and not getattr(self, '_is_game_running', False):

                self.particle_overlay.resume()

                self.particle_overlay.raise_()

        

        if key == "home":

            # If a profile is selected, show its mod panel, else hide

            if self.profile_list.currentItem():

                self.right_stack.setCurrentWidget(self.installed_mods_panel)

                self.right_stack.show()

            else:

                self.right_stack.hide()

        elif key == "packs":

            # Modpack tab: drawer is closed unless a card is actively selected for the open detail_panel

            sel_card = getattr(self.pack_browser, 'selected_card', None)

            cur_proj = getattr(self.detail_panel, 'current_project', None)

            sel_data = getattr(sel_card, 'data', None) if sel_card is not None else None

            same_proj = (

                sel_card is not None

                and (

                    not isinstance(cur_proj, dict)

                    or not isinstance(sel_data, dict)

                    or (cur_proj.get("project_id") or cur_proj.get("id") or cur_proj.get("slug"))

                    == (sel_data.get("project_id") or sel_data.get("id") or sel_data.get("slug"))

                )

            )

            if sel_card and same_proj and self.right_stack.isVisible() and self.right_stack.currentWidget() == self.detail_panel:

                self.pack_browser.set_columns(3)

                self.right_stack.show()

            else:

                self.right_stack.hide()

                self.pack_browser.set_columns(4)

                if hasattr(self.pack_browser, 'clear_selection'):

                    self.pack_browser.clear_selection()

            self.pack_browser.refresh_if_needed()

        elif key in ["bedrock_home", "server", "settings"]:

            self.right_stack.hide()

            if key == "settings":

                self._refresh_account_status_label()

        else:

            # Store/search tabs (mods / shaders)

            browser = self.mod_browser if key == "mods" else self.shader_browser

            sel_card = getattr(browser, 'selected_card', None)

            cur_proj = getattr(self.detail_panel, 'current_project', None)

            sel_data = getattr(sel_card, 'data', None) if sel_card is not None else None

            same_proj = (

                sel_card is not None

                and (

                    not isinstance(cur_proj, dict)

                    or not isinstance(sel_data, dict)

                    or (cur_proj.get("project_id") or cur_proj.get("id") or cur_proj.get("slug"))

                    == (sel_data.get("project_id") or sel_data.get("id") or sel_data.get("slug"))

                )

            )

            if sel_card and same_proj and self.right_stack.isVisible() and self.right_stack.currentWidget() == self.detail_panel:

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



    def on_browser_item_selected(self, data):

        prev = getattr(self.detail_panel, "current_project", None)

        if (

            not self.right_stack.isHidden()

            and self.right_stack.currentWidget() == self.detail_panel

            and not self.detail_panel.isHidden()

            and isinstance(prev, dict)

            and isinstance(data, dict)

        ):

            prev_id = prev.get("project_id") or prev.get("id") or prev.get("slug")

            new_id = data.get("project_id") or data.get("id") or data.get("slug")

            if (

                prev_id

                and new_id

                and prev_id == new_id

                and prev.get("filter_version") == data.get("filter_version")

                and prev.get("filter_loader") == data.get("filter_loader")

            ):

                return

        if hasattr(self, "sound_mgr") and self.sound_mgr:

            self.sound_mgr.play_enderchest_open()

        self.right_stack.setCurrentWidget(self.detail_panel)

        self.detail_panel.update_info(data)

        self.detail_panel.show()

        self.right_stack.show()

        total_w = self.splitter.width() or self.width() or 1440

        self.splitter.setSizes([max(total_w - 360, 600), 360])

        current_w = self.stack.currentWidget()

        if hasattr(current_w, 'set_columns'):

            current_w.set_columns(3)



    def on_detail_panel_closed(self):

        self.detail_panel.hide()

        self.detail_panel.current_project = None

        self.detail_panel.current_data = None

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

        self._active_selected_profile_id = None

        self._last_selected_profile_row = -1

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

        clicked_pid = item.data(Qt.UserRole) if item is not None else self.get_selected_profile()[0]

        if clicked_pid is not None and clicked_pid == getattr(self, "_active_selected_profile_id", None):

            return

        if hasattr(self, 'sound_mgr') and self.sound_mgr:

            self.sound_mgr.play_click()

        self.on_profile_selected()



    def on_profile_selected(self, force=False):

        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")

        en = lang == "en"

        pid, pdata = self.get_selected_profile()

        if not force and pid is not None and pid == getattr(self, "_active_selected_profile_id", None) and pdata:

            return

        self._active_selected_profile_id = pid if pdata else None

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

                last_row = getattr(self, "_last_selected_profile_row", -1)

                if last_row != curr_row:

                    if 0 <= last_row < self.profile_list.count():

                        old_w = self.profile_list.itemWidget(self.profile_list.item(last_row))

                        if old_w and hasattr(old_w, "set_selected"):

                            old_w.set_selected(False)

                    if 0 <= curr_row < self.profile_list.count():

                        new_w = self.profile_list.itemWidget(self.profile_list.item(curr_row))

                        if new_w and hasattr(new_w, "set_selected"):

                            new_w.set_selected(True)

                    self._last_selected_profile_row = curr_row

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

        if self.profile_list.currentItem() != item:

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

        if getattr(self, "_is_game_running", False) or getattr(self, "_is_launching", False):

            play_action.setEnabled(False)

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



            if data.get("imported_path"):

                profile_path = data["imported_path"]

                pack_name = data.get("name") or os.path.basename(profile_path)

            else:

                pack_name, profile_path = self._generate_unique_profile_name(data['name'])

                os.makedirs(profile_path, exist_ok=True)

            profile_id = str(uuid.uuid4())

                

            new_pdata = {

                "name": pack_name,

                "version": raw_version,

                "loader": loader_type,

                "ram": data['ram'],

                "path": profile_path,

                "icon": ""

            }

            if hasattr(self, "profile_session"):

                self.profile_session.create_profile(

                    profile_id,

                    new_pdata,

                    getattr(self, "ms_login", {}),

                    getattr(self, "settings", {}),

                )

            else:

                self.profiles[profile_id] = new_pdata

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

        if hasattr(self, "profile_session"):

            self.profile_session.delete_profile(

                pid,

                getattr(self, "ms_login", {}),

                getattr(self, "settings", {}),

            )

        else:

            del self.profiles[pid]

            self.save_config()

        if hasattr(self, 'sound_mgr') and self.sound_mgr:

            self.sound_mgr.play_break()

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

            

            if hasattr(self, "profile_session"):

                self.profile_session.update_profile(

                    pid,

                    {"name": new_name, "ram": new_ram, "icon": new_icon, "banner": new_banner},

                    getattr(self, "ms_login", {}),

                    getattr(self, "settings", {}),

                )

            else:

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

            

            self.install_modal = VegaInstallModal(pack_name, self)

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

            

            self.install_modal = VegaInstallModal(pack_name, self)

            self.install_modal.show()

            

            source = project.get("source", "modrinth")

            cat = DEFAULT_CURSEFORGE_CATALOG if source == "curseforge" else DEFAULT_CATALOG

            self.dl_thread = DownloadModpackThread(

                new_path,

                is_local=False,

                project_id=proj_id,

                policy=policy,

                selected_version_obj=selected_ver,

                catalog=cat,

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

            

        source = project.get("source", "modrinth")

        cat = DEFAULT_CURSEFORGE_CATALOG if source == "curseforge" else DEFAULT_CATALOG

        policy = CompatibilityPolicy.for_profile(pdata, ptype)

        dest_dir = os.path.join(pdata["path"], policy.target_subdir)



        # Smart Conflict Detection & Replacement

        from mod_manager import find_existing_mod_files

        title = project.get("title") or ""

        slug = project.get("slug") or ""

        existing_matches = find_existing_mod_files(dest_dir, title)

        if not existing_matches and slug:

            existing_matches = find_existing_mod_files(dest_dir, slug)



        overwrite = False

        if existing_matches:

            old_file = existing_matches[0]

            src_name = "CurseForge" if source == "curseforge" else "Modrinth"

            reply = QMessageBox.question(

                self,

                "Conflict Detected" if en else "Çakışma Tespit Edildi",

                f"'{old_file}' is already installed.\n\nWould you like to replace it with the {src_name} version?"

                if en else

                f"'{old_file}' zaten kurulu.\n\n{src_name} sürümüyle değiştirilip güncellensin mi?",

                QMessageBox.Yes | QMessageBox.No,

                QMessageBox.Yes

            )

            if reply != QMessageBox.Yes:

                return

            overwrite = True

            try:

                os.remove(os.path.join(dest_dir, old_file))

            except Exception:

                pass



        self.detail_panel.download_btn.setText("Downloading..." if en else "İndiriliyor...")

        self.detail_panel.download_btn.setEnabled(False)

        self.statusBar().showMessage(

            f"Downloading: {project.get('title', '')}..." if en else f"İndiriliyor: {project.get('title', '')}..."

        )

        

        self.dl_thread = DownloadModThread(

            project_id=project.get("project_id"),

            target_root=pdata["path"],

            policy=policy,

            catalog=cat,

            overwrite=overwrite,

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

            self._active_selected_profile_id = None

            pid, pdata = self.get_selected_profile()

            if pid and pdata and isinstance(pdata, dict) and pdata.get("path") and hasattr(self, "installed_mods_panel"):

                mods_dir = os.path.join(pdata["path"], "mods")

                self.installed_mods_panel._last_dir_mtime = -1

                self.installed_mods_panel.load_mods(mods_dir, pdata, pid, self)

            if hasattr(self, 'sound_mgr') and self.sound_mgr:

                self.sound_mgr.play_levelup()

            self.statusBar().showMessage("Download complete!" if en else "İndirme işlemi tamamlandı!")

            QMessageBox.information(

                self,

                "Success" if en else "Başarılı",

                "Download complete!" if en else "İndirme işlemi tamamlandı!"

            )

        else:

            cur_proj = getattr(self.detail_panel, "current_project", {}) or {}

            web_url = cur_proj.get("website_url")

            if web_url and cur_proj.get("source") == "curseforge":

                reply = QMessageBox.question(

                    self,

                    "Manual Download Required" if en else "Manuel İndirme Gerekli",

                    (

                        f"{msg}\n\nThis mod author has disabled third-party downloads.\n"

                        "Would you like to open CurseForge in your browser to download it?"

                        if en else

                        f"{msg}\n\nBu modun yazarı üçüncü parti indirmeleri devre dışı bırakmış.\n"

                        "Modu tarayıcıda açıp manuel indirmek ister misiniz?"

                    ),

                    QMessageBox.Yes | QMessageBox.No,

                    QMessageBox.Yes

                )

                if reply == QMessageBox.Yes:

                    from PySide6.QtGui import QDesktopServices

                    QDesktopServices.openUrl(QUrl(web_url))

                return



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

        

        self.install_modal = VegaInstallModal(

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



    def on_launch_error(self, msg: str = ""):

        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")

        en = lang == "en"

        self._is_launching = False

        self._is_game_running = False

        if hasattr(self, 'particle_overlay') and self.particle_overlay:

            if self.isVisible() and not self.isMinimized():

                self.particle_overlay.resume()

        if hasattr(self, 'sound_mgr') and self.sound_mgr:

            self.sound_mgr.play_error()

        if hasattr(self, 'action_bar'):

            self.action_bar.play_btn.setEnabled(True)

            self.action_bar.play_btn.setText("PLAY" if en else "OYNA")

            self.action_bar.progress.setVisible(False)

        if msg:

            self.statusBar().showMessage(f"Launch error: {msg}" if en else f"Başlatma hatası: {msg}")



    def on_play(self):

        if getattr(self, "_is_launching", False) is True or getattr(self, "_is_game_running", False) is True:

            return

        self._is_launching = True

        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")

        en = lang == "en"

        try:

            if hasattr(self, 'sound_mgr') and self.sound_mgr:

                self.sound_mgr.play_click()

            pid, pdata = self.get_selected_profile()

            if not pid:

                self._is_launching = False

                if hasattr(self, 'sound_mgr') and self.sound_mgr:

                    self.sound_mgr.play_error()

                QMessageBox.warning(

                    self,

                    "Warning" if en else "Uyarı",

                    "Please select a profile." if en else "Lütfen bir profil seçin."

                )

                return



            if hasattr(self, 'action_bar'):

                self.action_bar.play_btn.setEnabled(False)

                

            if not hasattr(self, 'ms_login') or not self.ms_login:

                dialog = MicrosoftLoginDialog(self)

                if dialog.exec() == QDialog.Accepted:

                    self.ms_login = dialog.get_account_data()

                    self.save_config()

                    self._continue_launch(pid, pdata)

                else:

                    self._is_launching = False

                    if hasattr(self, 'action_bar'):

                        self.action_bar.play_btn.setEnabled(True)

                        self.action_bar.play_btn.setText("PLAY" if en else "OYNA")

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

            self._is_launching = False

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

            self._is_launching = False

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

                self._is_launching = False

                if hasattr(self, 'action_bar'):

                    self.action_bar.play_btn.setEnabled(True)

                    self.action_bar.play_btn.setText("PLAY" if lang == "en" else "OYNA")

        else:

            self._is_launching = False

            if hasattr(self, 'action_bar'):

                self.action_bar.play_btn.setEnabled(True)

                self.action_bar.play_btn.setText("PLAY" if lang == "en" else "OYNA")



    def _continue_launch(self, pid, pdata):

        lang = (getattr(self, "settings", {}) or {}).get("language", "tr")

        en = (lang == "en")

        try:

            mc_dir = self.mc_dir

            os.makedirs(mc_dir, exist_ok=True)

            version = pdata["version"]



            from java_provisioner import DEFAULT_JAVA_PROVISIONER

            user_java = (getattr(self, "settings", {}) or {}).get("java_path", "").strip() or None

            req_major, resolved_java = DEFAULT_JAVA_PROVISIONER.resolve_java_runtime(

                mc_version=version,

                mc_dir=mc_dir,

                custom_java=user_java,

            )



            if not resolved_java:

                reply = QMessageBox.question(

                    self,

                    "Java Runtime Required" if en else "Java Çalışma Ortamı Gerekli",

                    (f"Minecraft {version} requires Java {req_major}.\n"

                     f"No compatible Java was found on your system.\n\n"

                     f"Would you like to automatically download and install portable Adoptium Temurin Java {req_major} now?")

                    if en else

                    (f"Minecraft {version} için Java {req_major} gerekiyor.\n"

                     f"Sisteminizde uyumlu bir Java bulunamadı.\n\n"

                     f"Dahili Adoptium Temurin Java {req_major} şimdi otomatik olarak indirilip kurulsun mu?"),

                    QMessageBox.Yes | QMessageBox.No,

                    QMessageBox.Yes,

                )

                if reply != QMessageBox.Yes:

                    self._is_launching = False

                    if hasattr(self, 'action_bar'):

                        self.action_bar.play_btn.setEnabled(True)

                        self.action_bar.play_btn.setText("PLAY" if en else "OYNA")

                    return



                self._download_temurin_and_continue(pid, pdata, req_major)

                return



            def_ram = int((getattr(self, "settings", {}) or {}).get("default_ram", 4096) or 4096)

            ram_mb = int(pdata.get("ram", def_ram) or def_ram)

            options = self.launch_pipeline.build_launch_options(

                auth_session=self.ms_login or {},

                game_directory=pdata["path"],

                ram_mb=ram_mb,

                extra_jvm=(getattr(self, "settings", {}) or {}).get("jvm_args", "").strip(),

                java_path=resolved_java,

            )

            

            if not self.launch_pipeline.is_engine_installed(version):

                if self.launch_pipeline.is_loader_version(version):

                    self._is_launching = False

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

                        self._is_launching = False

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

                        self._is_launching = False

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

            self._is_launching = False

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



    def _download_temurin_and_continue(self, pid, pdata, req_major: int):

        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"

        from java_provisioner import JavaDownloadThread

        self.java_dl_thread = JavaDownloadThread(

            target_major=req_major,

            mc_dir=self.mc_dir,

            lang="en" if en else "tr",

            parent=self,

        )

        self._active_threads = [t for t in self._active_threads if t.isRunning()]

        self._active_threads.append(self.java_dl_thread)



        if hasattr(self, 'action_bar'):

            self.action_bar.play_btn.setEnabled(False)

            self.action_bar.play_btn.setText("Downloading..." if en else "İndiriliyor...")

            self.action_bar.progress.setVisible(True)

            self.action_bar.progress.setRange(0, 100)

            self.action_bar.progress.setValue(0)

            self.java_dl_thread.progress_val.connect(

                lambda cur, tot: self.action_bar.progress.setValue(int(cur * 100 / tot) if tot > 0 else 0)

            )



        self.java_progress_dlg = QProgressDialog(

            f"Downloading Adoptium Temurin Java {req_major}..." if en else f"Adoptium Temurin Java {req_major} indiriliyor...",

            "Cancel" if en else "İptal",

            0,

            100,

            self,

        )

        self.java_progress_dlg.setWindowTitle("Java Provisioner" if en else "Java İndirici")

        self.java_progress_dlg.setWindowModality(Qt.WindowModal)



        self.java_dl_thread.progress_status.connect(self.java_progress_dlg.setLabelText)

        self.java_dl_thread.progress_status.connect(

            lambda s: self.statusBar().showMessage(s, 2000)

        )

        self.java_dl_thread.progress_val.connect(

            lambda cur, tot: self.java_progress_dlg.setValue(int(cur * 100 / tot) if tot > 0 else 0)

        )

        self.java_progress_dlg.canceled.connect(self.java_dl_thread.cancel)



        def _on_java_dl_finished(success: bool, path_or_err: str):

            self.java_progress_dlg.close()

            if hasattr(self, 'action_bar'):

                self.action_bar.progress.setVisible(False)

            if getattr(self.java_dl_thread, '_is_cancelled', False):

                self._is_launching = False

                if hasattr(self, 'action_bar'):

                    self.action_bar.play_btn.setEnabled(True)

                    self.action_bar.play_btn.setText("PLAY" if en else "OYNA")

                self.statusBar().showMessage("Java download cancelled." if en else "Java indirmesi iptal edildi.", 3000)

                return

            if success:

                self.statusBar().showMessage(

                    f"Java {req_major} installed successfully!" if en else f"Java {req_major} başarıyla kuruldu!",

                    4000

                )

                if hasattr(self, "_refresh_temurin_ui"):

                    self._refresh_temurin_ui()

                self._continue_launch(pid, pdata)

            else:

                self._is_launching = False

                if hasattr(self, 'sound_mgr') and self.sound_mgr:

                    self.sound_mgr.play_error()

                if hasattr(self, 'action_bar'):

                    self.action_bar.play_btn.setEnabled(True)

                    self.action_bar.play_btn.setText("PLAY" if en else "OYNA")

                QMessageBox.critical(

                    self,

                    "Java Download Error" if en else "Java İndirme Hatası",

                    f"Failed to install Java {req_major}:\n{path_or_err}"

                    if en else

                    f"Java {req_major} kurulumu başarısız:\n{path_or_err}"

                )



        self.java_dl_thread.download_finished.connect(_on_java_dl_finished)

        self.java_dl_thread.start()

        self.java_progress_dlg.exec()



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

            self._is_launching = False

            process = session.process

            

            self.tracker_thread = PlaytimeTrackerThread(process, pid)

            self._active_threads = [t for t in self._active_threads if t.isRunning()]

            self._active_threads.append(self.tracker_thread)

            self.tracker_thread.tracking_finished.connect(self.on_game_closed)

            self.tracker_thread.start()

            

            QTimer.singleShot(1500, self.on_game_started)

        except Exception as e:

            self._is_launching = False

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

        if getattr(self, "_is_game_running", True) is False:

            return

        en = (getattr(self, "settings", {}) or {}).get("language", "tr") == "en"

        self._is_launching = False

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

        self._is_launching = False

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

            if hasattr(self, "profile_session"):

                self.profile_session.add_playtime(pid, elapsed_seconds, getattr(self, "ms_login", {}), getattr(self, "settings", {}))

            elif pid in self.profiles:

                current = self.profiles[pid].get("playtime", 0)

                self.profiles[pid]["playtime"] = current + elapsed_seconds

                self.save_config()

            return



        self.showNormal()

        self.show()

        if hasattr(self, "profile_session"):

            self.profile_session.add_playtime(pid, elapsed_seconds, getattr(self, "ms_login", {}), getattr(self, "settings", {}))

            self.on_profile_selected(force=True)

        elif pid in self.profiles:

            current = self.profiles[pid].get("playtime", 0)

            self.profiles[pid]["playtime"] = current + elapsed_seconds

            self.save_config()

            self.on_profile_selected(force=True)



        exit_code = getattr(getattr(self, "tracker_thread", None), "exit_code", 0) or 0

        if exit_code != 0:

            pdata = self.profiles.get(pid, {})

            profile_path = pdata.get("path")

            if profile_path and os.path.exists(profile_path):

                try:

                    from crash_analyzer import CrashAnalyzer, VegaCrashDetectiveModal

                    report = CrashAnalyzer.analyze_profile(profile_path, exit_code=exit_code, lang=lang)

                    self.crash_modal = VegaCrashDetectiveModal(report, parent=self, lang=lang)

                    self.crash_modal.show()

                except Exception as diag_err:

                    print(f"[CrashDetective] Error launching modal: {diag_err}")

            if hasattr(self, "installed_mods_panel"):

                self.installed_mods_panel.show_crash_analysis(exit_code=exit_code)

            self.statusBar().showMessage(

                f"Game crashed (Code: {exit_code}) — Crash Detective opened."

                if en else

                f"Oyun hata ile kapandı (Kod: {exit_code}) — Kaza Dedektifi açıldı."

            )





    def handle_dungeons_download(self, download):

        try:

            from PySide6.QtWebEngineCore import QWebEngineDownloadRequest

        except ImportError:

            class QWebEngineDownloadRequest:  # type: ignore

                DownloadCompleted = 2

                DownloadCancelled = 3

                DownloadInterrupted = 4



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

                        extracted_paks = ContentCatalog.extract_zip_safely(

                            dest_path,

                            target_dir,

                            pattern=lambda fn: fn.lower().endswith('.pak'),

                            flatten=True,

                        )

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



        server_w = getattr(self, 'server_widget', None) or getattr(self, 'server_page', None)

        server_running = bool(server_w and hasattr(server_w, 'is_running') and server_w.is_running())

        if server_running:

            lang = (getattr(self, "settings", {}) or {}).get("language", "tr")

            en = (lang == "en")

            ans = QMessageBox.question(

                self,

                "Server Running" if en else "Sunucu Çalışıyor",

                (

                    "A Minecraft server is currently running. Closing the launcher will stop the server.\n\n"

                    "Are you sure you want to save and exit?"

                ) if en else (

                    "Şu anda bir Minecraft sunucusu çalışıyor. Başlatıcıyı kapatmak sunucuyu durduracaktır.\n\n"

                    "Kaydedip çıkmak istediğinize emin misiniz?"

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

        close_effect = None

        if hasattr(self, "sound_mgr") and self.sound_mgr and self.sound_mgr.is_enabled():

            try:

                self.sound_mgr.play_door_close()

                close_effect = getattr(self.sound_mgr, "_effects", {}).get("door_close")

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

                    if hasattr(th, 'cancel'):

                        try:

                            th.cancel()

                        except Exception:

                            pass

                    elif hasattr(th, 'stop'):

                        try:

                            th.stop()

                        except Exception:

                            pass

                    elif hasattr(th, 'terminate_process'):

                        try:

                            th.terminate_process(timeout=4)

                        except Exception:

                            pass

                    elif hasattr(th, 'stop_server'):

                        try:

                            th.stop_server()

                        except Exception:

                            pass

                    th.quit()

                    th.wait(1000)

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



        if close_effect is not None:

            # Drain audio buffer cleanly so the door closing slam is never cut off

            from PySide6.QtCore import QElapsedTimer

            wait_timer = QElapsedTimer()

            wait_timer.start()

            while wait_timer.elapsed() < 500:

                QApplication.processEvents()

                if not close_effect.isPlaying() and wait_timer.elapsed() > 100:

                    break

                time.sleep(0.01)

        elif close_timer is not None:

            while close_timer.elapsed() < 420:

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

            if (

                getattr(window, "_is_launching", False) is True

                or getattr(window, "_is_game_running", False) is True

                or getattr(window, "_cli_launch_pending", False) is True

            ):

                return

            target_pid = args[i + 1]

            item = window._get_profile_item(target_pid)

            if item:

                window._cli_launch_pending = True

                window.profile_list.setCurrentItem(item)

                window.on_profile_selected()



                def _trigger_cli_play():

                    window._cli_launch_pending = False

                    window.on_play()



                QTimer.singleShot(600, _trigger_cli_play)

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

        try:

            import ctypes

            user32 = ctypes.windll.user32

            hwnd = int(window.winId())

            user32.ShowWindow(hwnd, 9)  # SW_RESTORE

            user32.SetForegroundWindow(hwnd)

        except Exception:

            pass

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



    SINGLE_INSTANCE_MUTEX = "Global\\VegaLauncher_SingleInstance_Mutex"

    SINGLE_INSTANCE_SERVER = "vega_launcher_single_instance_ipc"

    mutex_handle = None



    if os.environ.get("VEGA_ALLOW_MULTIPLE") != "1":

        already_running = False

        try:

            import ctypes

            kernel32 = ctypes.windll.kernel32

            mutex_handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)

            if kernel32.GetLastError() in (183, 5):  # ERROR_ALREADY_EXISTS or ERROR_ACCESS_DENIED

                already_running = True

        except Exception:

            already_running = False



        if already_running:

            from PySide6.QtNetwork import QLocalSocket

            import time

            sock = QLocalSocket()

            connected = False

            for _ in range(30):  # Retry for up to 3.0s if primary instance is still initializing

                sock.connectToServer(SINGLE_INSTANCE_SERVER)

                if sock.waitForConnected(100):

                    connected = True

                    break

                time.sleep(0.1)



            if connected:

                payload = json.dumps(sys.argv[1:]).encode("utf-8")

                sock.write(payload)

                sock.waitForBytesWritten(1000)

                sock.disconnectFromServer()

            else:

                try:

                    import ctypes

                    user32 = ctypes.windll.user32

                    hwnd = user32.FindWindowW(None, "Vega Launcher")

                    if hwnd:

                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE

                        user32.SetForegroundWindow(hwnd)

                except Exception:

                    pass



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

        window._single_instance_mutex = mutex_handle

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


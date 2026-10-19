from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QProgressBar, QSpacerItem, QSizePolicy, QFrame, QComboBox,
                               QListWidget, QListWidgetItem, QMessageBox, QMenu, QLineEdit)
from PySide6.QtCore import Qt, Signal, QThread, QPoint
from PySide6.QtGui import QFont, QFontDatabase
import os
import re

_FONTS_LOADED = False

def _ensure_minecraft_fonts():
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    try:
        from PySide6.QtWidgets import QApplication
        if not QApplication.instance():
            return
        base_dir = os.path.dirname(os.path.abspath(__file__))
        fonts_dir = os.path.join(base_dir, "assets", "fonts")
        if os.path.exists(fonts_dir):
            for fname in os.listdir(fonts_dir):
                if fname.lower().endswith((".ttf", ".otf")):
                    QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))
        _FONTS_LOADED = True
    except Exception:
        pass


_RE_LOADER = re.compile(r'(?:[-_+](fabric|forge|neoforge|quilt)(?:[-_+]|$))', re.IGNORECASE)
_RE_FABRIC_API = re.compile(r'^fabric[-_]api', re.IGNORECASE)
_RE_MC_VER = re.compile(r'(?:mc[-_+]?)?(1\.(?:1[2-9]|2[0-9]|3[0-9])(?:\.\d+)?)', re.IGNORECASE)
_RE_MOD_VER = re.compile(r'(?:[-_+]v?|v)(\d+\.\d+(?:\.\d+)*(?:-[a-zA-Z0-9.]+)?)(?:[-_+.]|$)')
_RE_NAME_MATCH = re.compile(r'[-_+](?:fabric|forge|neoforge|quilt|mc\d|v?\d+\.\d+)', re.IGNORECASE)
_RE_TOKENS = re.compile(r'[-_+]')
_RE_CAMEL = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')
_RE_API = re.compile(r'\bApi\b', re.IGNORECASE)

_FORMAT_NAME_CACHE = {}

def _format_mod_display_name(filename: str):
    cached = _FORMAT_NAME_CACHE.get(filename)
    if cached is not None:
        return cached

    stem = filename
    for ext in ('.disabled', '.jar', '.pak', '.zip'):
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            
    # Detect loader
    loader = ''
    l_m = _RE_LOADER.search(stem)
    if l_m and not _RE_FABRIC_API.match(stem):
        loader = l_m.group(1).capitalize()

    # Detect MC version
    mc_ver = ''
    m_m = _RE_MC_VER.search(stem)
    if m_m:
        mc_ver = m_m.group(1)

    # Detect Mod Version
    mod_ver = ''
    v_m = _RE_MOD_VER.search(stem)
    if v_m:
        cand = v_m.group(1)
        if cand != mc_ver:
            mod_ver = f"v{cand}"

    name_match = _RE_NAME_MATCH.split(stem, maxsplit=1)
    raw_name = name_match[0] if name_match else stem
    
    if not raw_name or len(raw_name) <= 1:
        tokens = _RE_TOKENS.split(stem)
        raw_name = tokens[0] if tokens else stem

    raw_name = raw_name.replace('-', ' ').replace('_', ' ').strip()
    title = _RE_CAMEL.sub(' ', raw_name).strip()
    if title.islower():
        title = title.title()
    title = _RE_API.sub('API', title)
    if not title:
        title = filename

    sub_parts = []
    if mod_ver:
        sub_parts.append(mod_ver)
    if loader:
        sub_parts.append(loader)
    if mc_ver:
        sub_parts.append(f"MC {mc_ver}")
    if not sub_parts:
        ext_clean = "Pak" if filename.endswith(".pak") or ".pak." in filename else "Mod"
        sub_parts.append(ext_clean)
    res = (title, " · ".join(sub_parts))
    _FORMAT_NAME_CACHE[filename] = res
    return res

class WorldBackupThread(QThread):
    backup_finished = Signal(bool, str)

    def __init__(self, base_zip, w_path, parent=None):
        super().__init__(parent)
        self.base_zip = base_zip
        self.w_path = w_path

    def run(self):
        try:
            from backup_manager import BackupManager
            archive_path = BackupManager.create_world_archive(self.base_zip, self.w_path)
            self.backup_finished.emit(True, archive_path)
        except Exception as e:
            self.backup_finished.emit(False, str(e))

class WorldScannerThread(QThread):
    worlds_scanned = Signal(list)

    def __init__(self, saves_dir: str, parent=None):
        super().__init__(parent)
        self.saves_dir = saves_dir

    def run(self):
        import datetime
        results = []
        try:
            if not os.path.exists(self.saves_dir):
                self.worlds_scanned.emit([])
                return
            worlds = [d for d in os.listdir(self.saves_dir) if os.path.isdir(os.path.join(self.saves_dir, d))]
            for w in sorted(worlds):
                w_path = os.path.join(self.saves_dir, w)
                total_bytes = 0
                level_dat = os.path.join(w_path, "level.dat")
                latest_mtime = os.path.getmtime(level_dat) if os.path.exists(level_dat) else os.path.getmtime(w_path)
                file_count = 0
                for r, _, files in os.walk(w_path):
                    for f in files:
                        fp = os.path.join(r, f)
                        try:
                            total_bytes += os.path.getsize(fp)
                        except OSError:
                            pass
                        file_count += 1
                        if file_count > 2500:
                            break
                    if file_count > 2500:
                        break
                size_mb = total_bytes / (1024 * 1024)
                dt_str = datetime.datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M")
                results.append((w, w_path, size_mb, dt_str))
        except Exception:
            pass
        self.worlds_scanned.emit(results)


class ModItemWidget(QWidget):
    def __init__(self, filepath, parent_list, lang="tr"):
        super().__init__()
        _ensure_minecraft_fonts()
        self.filepath = filepath
        self.parent_list = parent_list
        self.lang = lang
        self.is_disabled = self.filepath.endswith(".disabled")
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignVCenter)
        self.setFixedHeight(54)
        
        filename = os.path.basename(self.filepath)
        display_fn = filename[:-9] if self.is_disabled else filename
        self.title_text, self.subtitle_text = _format_mod_display_name(display_fn)
        
        # Subtle file type icon box
        self.icon_box = QFrame()
        self.icon_box.setObjectName("ModTypeBox")
        self.icon_box.setFixedSize(32, 32)
        icon_lay = QVBoxLayout(self.icon_box)
        icon_lay.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel("PAK" if display_fn.endswith(".pak") else "JAR")
        icon_lbl.setObjectName("ModTypeLbl")
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lay.addWidget(icon_lbl)
        layout.addWidget(self.icon_box)

        # Title & Subtitle vertical layout
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setAlignment(Qt.AlignVCenter)
        
        self.name_lbl = QLabel(self.title_text)
        self.name_lbl.setObjectName("ModNameLbl")
        self.name_lbl.setToolTip(f"{self.title_text}\n{filename}")
        self.name_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_layout.addWidget(self.name_lbl)
        
        self.sub_lbl = QLabel(self.subtitle_text)
        self.sub_lbl.setObjectName("ModSubLbl")
        text_layout.addWidget(self.sub_lbl)
        
        layout.addLayout(text_layout, 1)
        
        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedSize(84, 30)
        self.toggle_btn.setFont(QFont("Monocraft", 10, QFont.Bold))
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(lambda x=None: self.toggle_mod())
        layout.addWidget(self.toggle_btn)
        
        self.del_btn = QPushButton("🗑️")
        self.del_btn.setObjectName("ModDelBtn")
        self.del_btn.setFixedSize(30, 30)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setToolTip("Delete Mod" if self.lang == "en" else "Modu Sil")
        self.del_btn.clicked.connect(lambda x=None: self.delete_mod())
        layout.addWidget(self.del_btn)

        self.setStyleSheet("""
            #ModTypeBox {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            #ModTypeLbl {
                font-size: 10px;
                font-weight: 700;
                color: #94A3B8;
                background: transparent;
            }
            #ModNameLbl {
                font-size: 13px;
                font-weight: bold;
                color: #F8FAFC;
                background: transparent;
            }
            #ModSubLbl {
                font-size: 11px;
                color: #94A3B8;
                background: transparent;
            }
            #ModDelBtn {
                background-color: #222228;
                color: #EF4444;
                border: 1px solid #18181C;
                border-top: 1px solid #33333E;
                border-bottom: 2px solid #141418;
                border-radius: 4px;
                font-size: 13px;
                padding: 0px;
            }
            QPushButton#ModDelBtn:hover {
                background-color: #7F1D1D;
                color: #FCA5A5;
                border-color: #DC2626;
            }
        """)
        self.update_toggle_style()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(100, 54)
        
    def update_toggle_style(self):
        if hasattr(self.parent_list, "_get_toggle_styles"):
            on_style, off_style = self.parent_list._get_toggle_styles()
        else:
            on_style, off_style = "", ""

        if self.is_disabled:
            self.toggle_btn.setText("OFF" if self.lang == "en" else "KAPALI")
            self.toggle_btn.setToolTip("Enable Mod" if self.lang == "en" else "Modu Etkinleştir")
            if off_style:
                self.toggle_btn.setStyleSheet(off_style)
            self.name_lbl.setStyleSheet("color: #64748B;")
        else:
            self.toggle_btn.setText("ON" if self.lang == "en" else "AÇIK")
            self.toggle_btn.setToolTip("Disable Mod" if self.lang == "en" else "Modu Devre Dışı Bırak")
            if on_style:
                self.toggle_btn.setStyleSheet(on_style)
            self.name_lbl.setStyleSheet("color: #F8FAFC;")

    def set_language(self, lang="tr"):
        self.lang = lang
        self.update_toggle_style()
        if hasattr(self, "del_btn"):
            self.del_btn.setToolTip("Delete Mod" if self.lang == "en" else "Modu Sil")
            
    def toggle_mod(self):
        try:
            if self.is_disabled:
                if self.filepath.lower().endswith(".disabled"):
                    new_path = self.filepath[:-len(".disabled")]
                else:
                    new_path, _ = os.path.splitext(self.filepath)
                os.rename(self.filepath, new_path)
                self.filepath = new_path
                self.is_disabled = False
            else:
                new_path = self.filepath + ".disabled"
                os.rename(self.filepath, new_path)
                self.filepath = new_path
                self.is_disabled = True
            self.update_toggle_style()
            try:
                from sound_manager import SoundManager
                if self.is_disabled:
                    SoundManager.get_instance().play_lever_off()
                else:
                    SoundManager.get_instance().play_lever_on()
            except Exception:
                pass
        except Exception as e:
            err_msg = f"Could not change mod state:\n{e}" if self.lang == "en" else f"Mod durumu değiştirilemedi:\n{e}"
            QMessageBox.warning(self, "Error" if self.lang == "en" else "Hata", err_msg)
            
    def delete_mod(self):
        title = "Confirm" if self.lang == "en" else "Onay"
        msg = "Are you sure you want to delete this mod?" if self.lang == "en" else "Bu modu silmek istediğinize emin misiniz?"
        reply = QMessageBox.question(self, title, msg, QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_break()
            except Exception:
                pass
            try:
                os.remove(self.filepath)
                self.parent_list.refresh_list()
            except Exception as e:
                try:
                    from sound_manager import SoundManager
                    SoundManager.get_instance().play_error()
                except Exception:
                    pass
                err_msg = f"Could not delete mod:\n{e}" if self.lang == "en" else f"Mod silinemedi:\n{e}"
                QMessageBox.warning(self, "Error" if self.lang == "en" else "Hata", err_msg)

_SCREENSHOT_ICON_CACHE = {}

class InstalledModsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InstalledModsPanel")
        self.current_dir = None
        self.pdata = None
        self.pid = None
        self.main_window = None
        self.lang = "tr"
        self._mod_load_gen = 0
        self._pending_mods = []
        self._pending_idx = 0
        self._last_dir_mtime = -1
        self._last_loaded_count = 0
        self._cached_toggle_styles_theme = None
        self._cached_on_style = ""
        self._cached_off_style = ""
        self._world_scanner_thread = None
        
        from PySide6.QtWidgets import QStackedWidget, QPlainTextEdit
        from PySide6.QtCore import QSize
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 4)
        self.title = QLabel("KURULU MODLAR")
        self.title.setStyleSheet("font-family: 'Minecraft Five', 'Segoe UI', sans-serif; font-size: 15px; font-weight: bold; color: #F8FAFC; letter-spacing: 0.5px; background: transparent;")
        header_layout.addWidget(self.title)
        header_layout.addStretch()

        self.install_engine_btn = QPushButton("Motor Kur (Forge/Fabric)")
        self.install_engine_btn.setObjectName("PrimaryAccentButton")
        self.install_engine_btn.setCursor(Qt.PointingHandCursor)
        self.install_engine_btn.setStyleSheet("""
            QPushButton {
                background-color: #222228;
                color: #E4E4E7;
                border: 1px solid #18181C;
                border-top: 1.5px solid #3E3E48;
                border-bottom: 2.5px solid #141416;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2A2A32;
                border-top: 1.5px solid #525260;
                color: #FFFFFF;
            }
        """)
        self.install_engine_btn.clicked.connect(lambda checked=False: self.open_engine_installer())
        header_layout.addWidget(self.install_engine_btn)

        layout.addLayout(header_layout)

        # Sub-tab bar: [MODLAR] [DÜNYALAR] [EKRAN GÖRÜNTÜLERİ] [LOG / ÇÖKME]
        sub_tab_row = QHBoxLayout()
        sub_tab_row.setSpacing(6)
        self.sub_tab_btns = []
        tab_labels = ["MODLAR", "DÜNYALAR", "EKRAN GÖRÜNTÜLERİ", "LOG / ÇÖKME"]
        for idx, t_lbl in enumerate(tab_labels):
            btn = QPushButton(t_lbl)
            btn.setObjectName("SubTabButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda checked=False, i=idx: self.switch_sub_tab(i, play_sound=True))
            sub_tab_row.addWidget(btn)
            self.sub_tab_btns.append(btn)
        layout.addLayout(sub_tab_row)

        self.sub_stack = QStackedWidget()
        layout.addWidget(self.sub_stack, 1)

        list_style = "QListWidget { background-color: #1A1A1E; border: 1px solid #282830; border-radius: 6px; outline: none; } QListWidget::item { border-bottom: 1px solid #242428; padding: 8px; color: #F8FAFC; } QListWidget::item:selected { background-color: #2B1D42; color: #FFFFFF; border: 1px solid #8B5CF6; }"
        btn_style = "QPushButton { background-color: #222228; color: #E4E4E7; border: 1px solid #18181C; border-top: 1.5px solid #3E3E48; border-bottom: 3px solid #18181C; border-radius: 4px; padding: 6px 12px; font-size: 11px; font-weight: 600; } QPushButton:hover { border-top: 1.5px solid #4C4C58; background-color: #2A2A32; color: #FFFFFF; }"

        # Page 0: Mods
        mods_page = QWidget()
        m_lay = QVBoxLayout(mods_page)
        m_lay.setContentsMargins(0, 0, 0, 0)
        m_lay.setSpacing(6)

        search_bar_layout = QHBoxLayout()
        search_bar_layout.setContentsMargins(0, 2, 0, 0)
        search_bar_layout.setSpacing(8)

        self.mod_search_input = QLineEdit()
        self.mod_search_input.setPlaceholderText("Modlarda ara..." if self.lang == "tr" else "Search installed mods...")
        self.mod_search_input.setClearButtonEnabled(True)
        self.mod_search_input.setStyleSheet("""
            QLineEdit {
                background-color: #141416;
                color: #F8FAFC;
                border: 1px solid #282830;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-family: 'Segoe UI', sans-serif;
            }
            QLineEdit:hover {
                border-color: #3E3E48;
            }
            QLineEdit:focus {
                border: 1px solid #8B5CF6;
                background-color: #18181D;
            }
        """)
        self.mod_search_input.textChanged.connect(self._filter_mods)
        search_bar_layout.addWidget(self.mod_search_input, 1)

        self.mod_count_lbl = QLabel("")
        self.mod_count_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 600; background: transparent; border: none; padding-right: 4px;")
        search_bar_layout.addWidget(self.mod_count_lbl, 0)

        m_lay.addLayout(search_bar_layout)

        self.mod_list = QListWidget()
        self.mod_list.setStyleSheet("QListWidget { background-color: #1A1A1E; border: 1px solid #282830; border-radius: 6px; outline: none; } QListWidget::item { border-bottom: 1px solid #242428; padding: 0px; }")
        m_lay.addWidget(self.mod_list, 1)
        self.sub_stack.addWidget(mods_page)

        # Page 1: Worlds (Saves)
        worlds_page = QWidget()
        w_lay = QVBoxLayout(worlds_page)
        w_lay.setContentsMargins(0, 0, 0, 0)
        w_lay.setSpacing(8)
        self.world_list = QListWidget()
        self.world_list.setStyleSheet(list_style)
        w_lay.addWidget(self.world_list, 1)
        w_btn_row = QHBoxLayout()
        self.btn_world_backup = QPushButton(".zip Yedekle")
        self.btn_world_backup.setCursor(Qt.PointingHandCursor)
        self.btn_world_backup.setStyleSheet(btn_style)
        self.btn_world_backup.clicked.connect(lambda checked=False: self.backup_selected_world())
        self.btn_world_folder = QPushButton("Klasörü Aç")
        self.btn_world_folder.setCursor(Qt.PointingHandCursor)
        self.btn_world_folder.setStyleSheet(btn_style)
        self.btn_world_folder.clicked.connect(lambda checked=False: self.open_worlds_folder())
        self.btn_world_del = QPushButton("Sil")
        self.btn_world_del.setCursor(Qt.PointingHandCursor)
        self.btn_world_del.setStyleSheet("QPushButton { background-color: #991B1B; color: #FFFFFF; border: 1px solid #7F1D1D; border-top: 1.5px solid #DC2626; border-bottom: 3px solid #7F1D1D; border-radius: 4px; padding: 6px 12px; font-size: 11px; font-weight: bold; } QPushButton:hover { background-color: #7F1D1D; }")
        self.btn_world_del.clicked.connect(lambda checked=False: self.delete_selected_world())
        w_btn_row.addWidget(self.btn_world_backup)
        w_btn_row.addWidget(self.btn_world_folder)
        w_btn_row.addWidget(self.btn_world_del)
        w_lay.addLayout(w_btn_row)
        self.sub_stack.addWidget(worlds_page)

        # Page 2: Screenshots
        shots_page = QWidget()
        s_lay = QVBoxLayout(shots_page)
        s_lay.setContentsMargins(0, 0, 0, 0)
        s_lay.setSpacing(8)
        self.shot_list = QListWidget()
        self.shot_list.setIconSize(QSize(72, 42))
        self.shot_list.setStyleSheet(list_style)
        self.shot_list.itemDoubleClicked.connect(lambda item=None: self.open_selected_screenshot())
        s_lay.addWidget(self.shot_list, 1)
        s_btn_row = QHBoxLayout()
        self.btn_shot_copy = QPushButton("Panoya Kopyala")
        self.btn_shot_copy.setCursor(Qt.PointingHandCursor)
        self.btn_shot_copy.setStyleSheet(btn_style)
        self.btn_shot_copy.clicked.connect(lambda checked=False: self.copy_selected_screenshot())
        self.btn_shot_folder = QPushButton("Klasörü Aç")
        self.btn_shot_folder.setCursor(Qt.PointingHandCursor)
        self.btn_shot_folder.setStyleSheet(btn_style)
        self.btn_shot_folder.clicked.connect(lambda checked=False: self.open_screenshots_folder())
        self.btn_shot_del = QPushButton("Sil")
        self.btn_shot_del.setCursor(Qt.PointingHandCursor)
        self.btn_shot_del.setStyleSheet("QPushButton { background-color: #991B1B; color: #FFFFFF; border: 1px solid #7F1D1D; border-top: 1.5px solid #DC2626; border-bottom: 3px solid #7F1D1D; border-radius: 4px; padding: 6px 12px; font-size: 11px; font-weight: bold; } QPushButton:hover { background-color: #7F1D1D; }")
        self.btn_shot_del.clicked.connect(lambda checked=False: self.delete_selected_screenshot())
        s_btn_row.addWidget(self.btn_shot_copy)
        s_btn_row.addWidget(self.btn_shot_folder)
        s_btn_row.addWidget(self.btn_shot_del)
        s_lay.addLayout(s_btn_row)
        self.sub_stack.addWidget(shots_page)

        # Page 3: Logs / Crash Analyzer
        logs_page = QWidget()
        l_lay = QVBoxLayout(logs_page)
        l_lay.setContentsMargins(0, 0, 0, 0)
        l_lay.setSpacing(8)
        self.lbl_crash_diagnosis = QLabel("")
        self.lbl_crash_diagnosis.setWordWrap(True)
        self.lbl_crash_diagnosis.setStyleSheet("background-color: #1A1A1E; border: 1px solid #282830; border-radius: 6px; padding: 12px; font-size: 12px; color: #F8FAFC;")
        l_lay.addWidget(self.lbl_crash_diagnosis)
        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMaximumBlockCount(3000)
        self.log_viewer.setStyleSheet("background-color: #0C0C0E; color: #E2E8F0; font-family: Consolas, monospace; font-size: 11px; border: 1px solid #242428; border-radius: 4px; padding: 6px;")
        l_lay.addWidget(self.log_viewer, 1)
        l_btn_row = QHBoxLayout()
        self.btn_log_refresh = QPushButton("Yenile")
        self.btn_log_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_log_refresh.setStyleSheet(btn_style)
        self.btn_log_refresh.clicked.connect(lambda checked=False: self.refresh_logs())
        self.btn_log_copy = QPushButton("Raporu Kopyala")
        self.btn_log_copy.setCursor(Qt.PointingHandCursor)
        self.btn_log_copy.setStyleSheet(btn_style)
        self.btn_log_copy.clicked.connect(lambda checked=False: self.copy_log_report())
        self.btn_log_folder = QPushButton("Log Klasörü")
        self.btn_log_folder.setCursor(Qt.PointingHandCursor)
        self.btn_log_folder.setStyleSheet(btn_style)
        self.btn_log_folder.clicked.connect(lambda checked=False: self.open_logs_folder())
        l_btn_row.addWidget(self.btn_log_refresh)
        l_btn_row.addWidget(self.btn_log_copy)
        l_btn_row.addWidget(self.btn_log_folder)
        l_lay.addLayout(l_btn_row)
        self.sub_stack.addWidget(logs_page)

        self.switch_sub_tab(0)

    def _get_profile_root(self):
        if self.pdata and self.pdata.get("path"):
            return self.pdata["path"]
        if self.current_dir:
            return os.path.dirname(self.current_dir.rstrip("\\/"))
        return None

    def switch_sub_tab(self, index, play_sound=False):
        if play_sound:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_book_flip()
            except Exception:
                pass
        self.sub_stack.setCurrentIndex(index)
        en = self.lang == "en"
        titles = (
            ["Installed Mods", "Saved Worlds", "Screenshots", "Logs & Crash Analyzer"]
            if en else
            ["Kurulu Modlar", "Kayıtlı Dünyalar", "Ekran Görüntüleri", "Log & Çökme Analizi"]
        )
        if 0 <= index < len(titles):
            self.title.setText(titles[index])
        if hasattr(self, "install_engine_btn"):
            self.install_engine_btn.setVisible(index == 0)
        theme_key = getattr(self, "_active_theme", None)
        if not theme_key:
            try:
                win = self.window()
                if win and hasattr(win, "settings") and isinstance(win.settings, dict):
                    theme_key = win.settings.get("theme", "electric_amethyst")
            except Exception:
                theme_key = "electric_amethyst"
        if not theme_key:
            theme_key = "electric_amethyst"

        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            r, g, b = t["rgb"]
            prim_light = t["primary_light"]
        except Exception:
            r, g, b = (139, 92, 246)
            prim_light = "#A855F7"

        for i, btn in enumerate(self.sub_tab_btns):
            is_active = (i == index)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            if is_active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: #261E38;
                        color: #FFFFFF;
                        border: 1px solid {prim_light};
                        border-top: 1.5px solid {prim_light};
                        border-bottom: 2.5px solid #4C1D95;
                        border-radius: 4px;
                        font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 6px 12px;
                    }}
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1A1A1E;
                        color: #94A3B8;
                        border: 1px solid #242428;
                        border-top: 1px solid #2E2E34;
                        border-bottom: 2px solid #16161A;
                        border-radius: 4px;
                        font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 6px 12px;
                    }
                    QPushButton:hover {
                        background-color: #222228;
                        color: #FFFFFF;
                        border-top: 1px solid #3E3E48;
                    }
                """)
        if index == 0:
            self.refresh_list()
        elif index == 1:
            self.refresh_worlds()
        elif index == 2:
            self.refresh_screenshots()
        elif index == 3:
            self.refresh_logs()

    def _get_toggle_styles(self):
        theme_key = getattr(self, "_active_theme", None) or "electric_amethyst"
        if getattr(self, "_cached_toggle_styles_theme", None) == theme_key and self._cached_on_style:
            return self._cached_on_style, self._cached_off_style

        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            grad_start = t.get("gradient_start", "#7C3AED")
            primary = t.get("primary", "#8B5CF6")
            bevel_top = t.get("bevel_top", "#A78BFA")
            bevel_bottom = t.get("bevel_bottom", "#4C1D95")
            pressed = t.get("pressed", "#6D28D9")
            glow = t.get("glow", "#C084FC")
        except Exception:
            grad_start = "#7C3AED"
            primary = "#8B5CF6"
            bevel_top = "#A78BFA"
            bevel_bottom = "#4C1D95"
            pressed = "#6D28D9"
            glow = "#C084FC"

        self._cached_on_style = f"""
            QPushButton {{
                background-color: {grad_start};
                color: #FFFFFF;
                border: 1px solid {pressed};
                border-top: 1.5px solid {bevel_top};
                border-left: 1px solid {primary};
                border-right: 1px solid {pressed};
                border-bottom: 2.5px solid {bevel_bottom};
                border-radius: 4px;
                font-family: 'Monocraft', 'Minecraft Five', 'Minecraft', sans-serif;
                font-weight: 700;
                font-size: 10pt;
                letter-spacing: 0.5px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {primary};
                border-top: 1.5px solid {glow};
            }}
            QPushButton:pressed {{
                background-color: {pressed};
                border-top: 2.5px solid {bevel_bottom};
                border-bottom: 1px solid {bevel_top};
            }}
        """
        self._cached_off_style = """
            QPushButton {
                background-color: #26262B;
                color: #94A3B8;
                border: 1px solid #1C1C20;
                border-top: 1px solid #383842;
                border-bottom: 2px solid #18181C;
                border-radius: 4px;
                font-family: 'Monocraft', 'Minecraft Five', 'Minecraft', sans-serif;
                font-weight: 700;
                font-size: 10pt;
                letter-spacing: 0.5px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #2F2F36;
                color: #CBD5E1;
            }
            QPushButton:pressed {
                background-color: #1C1C20;
            }
        """
        self._cached_toggle_styles_theme = theme_key
        return self._cached_on_style, self._cached_off_style

    def set_theme(self, theme_key: str):
        self._active_theme = theme_key
        self._cached_toggle_styles_theme = None
        self._cached_on_style = ""
        self._cached_off_style = ""
        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            r, g, b = t["rgb"]
            prim_light = t["primary_light"]
            tint = t.get("text_tint", "#FFFFFF")

            list_style = f"QListWidget {{ background-color: #1A1A1E; border: 1px solid #282830; border-radius: 6px; outline: none; }} QListWidget::item {{ border-bottom: 1px solid #242428; padding: 8px; color: #F8FAFC; }} QListWidget::item:selected {{ background-color: #261E38; color: {tint}; border: 1px solid {prim_light}; }}"
            btn_style = f"QPushButton {{ background-color: #222228; color: #E4E4E7; border: 1px solid #18181C; border-top: 1.5px solid #3E3E48; border-bottom: 2.5px solid #141416; border-radius: 4px; padding: 6px 12px; font-size: 11px; font-weight: 600; }} QPushButton:hover {{ border-top: 1.5px solid {prim_light}; background-color: #2A2A32; color: #FFFFFF; }}"

            if hasattr(self, "world_list"): self.world_list.setStyleSheet(list_style)
            if hasattr(self, "shot_list"): self.shot_list.setStyleSheet(list_style)
            if hasattr(self, "mod_list"): self.mod_list.setStyleSheet(f"QListWidget {{ background-color: #1A1A1E; border: 1px solid #282830; border-radius: 6px; outline: none; }} QListWidget::item {{ border-bottom: 1px solid #242428; padding: 0px; }} QListWidget::item:selected {{ background-color: #261E38; border: 1px solid {prim_light}; }}")
            for b in [
                getattr(self, "btn_world_backup", None),
                getattr(self, "btn_world_folder", None),
                getattr(self, "btn_shot_copy", None),
                getattr(self, "btn_shot_folder", None),
                getattr(self, "btn_log_refresh", None),
                getattr(self, "btn_log_copy", None),
                getattr(self, "btn_log_folder", None),
            ]:
                if b: b.setStyleSheet(btn_style)

            if hasattr(self, "mod_search_input"):
                self.mod_search_input.setStyleSheet(f"""
                    QLineEdit {{
                        background-color: #141416;
                        color: #F8FAFC;
                        border: 1px solid #282830;
                        border-radius: 6px;
                        padding: 6px 12px;
                        font-size: 12px;
                        font-family: 'Segoe UI', sans-serif;
                    }}
                    QLineEdit:hover {{
                        border-color: #3E3E48;
                    }}
                    QLineEdit:focus {{
                        border: 1px solid {prim_light};
                        background-color: #18181D;
                    }}
                """)

            if hasattr(self, "lbl_crash_diagnosis") and not ("Diagnosis:" in self.lbl_crash_diagnosis.text() or "Teşhis:" in self.lbl_crash_diagnosis.text() or "Crash" in self.lbl_crash_diagnosis.text() or "hata ile kapandı" in self.lbl_crash_diagnosis.text()):
                self.lbl_crash_diagnosis.setStyleSheet(f"background-color: #1A1A1E; border: 1px solid rgba({r}, {g}, {b}, 0.35); border-radius: 6px; padding: 12px; font-size: 12px; color: #F8FAFC;")
            if hasattr(self, "mod_list"):
                for i in range(self.mod_list.count()):
                    w = self.mod_list.itemWidget(self.mod_list.item(i))
                    if w and hasattr(w, "update_toggle_style"):
                        w.update_toggle_style()
            cur_idx = self.sub_stack.currentIndex()
            for i, btn in enumerate(self.sub_tab_btns):
                is_active = (i == cur_idx)
                btn.setProperty("active", "true" if is_active else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                if is_active:
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: #261E38;
                            color: #FFFFFF;
                            border: 1px solid {prim_light};
                            border-top: 1.5px solid {prim_light};
                            border-bottom: 2.5px solid #4C1D95;
                            border-radius: 4px;
                            font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                            font-size: 11px;
                            font-weight: bold;
                            padding: 6px 12px;
                        }}
                    """)
        except Exception:
            pass


    def set_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        tab_labels = (
            ["MODS", "WORLDS", "SCREENSHOTS", "LOGS / CRASH"]
            if en else
            ["MODLAR", "DÜNYALAR", "EKRAN GÖRÜNTÜLERİ", "LOG / ÇÖKME"]
        )
        for i, lbl in enumerate(tab_labels):
            self.sub_tab_btns[i].setText(lbl)
        if hasattr(self, "install_engine_btn"):
            self.install_engine_btn.setText("Install Loader" if en else "Motor Kur (Forge/Fabric)")
        if hasattr(self, "mod_search_input"):
            self.mod_search_input.setPlaceholderText("Search installed mods..." if en else "Modlarda ara...")
        if hasattr(self, "mod_search_input") and hasattr(self, "_filter_mods"):
            self._filter_mods(self.mod_search_input.text())
        if hasattr(self, "mod_list"):
            for i in range(self.mod_list.count()):
                w = self.mod_list.itemWidget(self.mod_list.item(i))
                if w and hasattr(w, "set_language"):
                    w.set_language(lang)
        self.btn_world_backup.setText("Backup .zip" if en else ".zip Yedekle")
        self.btn_world_folder.setText("Open Folder" if en else "Klasörü Aç")
        self.btn_world_del.setText("Delete" if en else "Sil")
        self.btn_shot_copy.setText("Copy Image" if en else "Panoya Kopyala")
        self.btn_shot_folder.setText("Open Folder" if en else "Klasörü Aç")
        self.btn_shot_del.setText("Delete" if en else "Sil")
        self.btn_log_refresh.setText("Refresh" if en else "Yenile")
        self.btn_log_copy.setText("Copy Report" if en else "Raporu Kopyala")
        self.btn_log_folder.setText("Logs Folder" if en else "Log Klasörü")

    def open_engine_installer(self):
        if not self.pdata or not self.pid or not self.main_window:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Info" if self.lang == "en" else "Bilgi",
                "Please select a profile first." if self.lang == "en" else "Lütfen önce bir profil seçin."
            )
            return
        from engine_installer import EngineInstallDialog
        dlg = EngineInstallDialog(self.pdata, self.pid, self.main_window, parent=self)
        dlg.exec()
        
    def load_mods(self, mods_dir, pdata=None, pid=None, main_window=None):
        dir_mtime = os.path.getmtime(mods_dir) if mods_dir and os.path.exists(mods_dir) else 0
        if (
            getattr(self, "current_dir", None) == mods_dir
            and getattr(self, "pid", None) == pid
            and getattr(self, "_last_dir_mtime", -1) == dir_mtime
            and getattr(self, "_last_loaded_count", 0) == self.mod_list.count()
            and self.mod_list.count() > 0
        ):
            return

        self.current_dir = mods_dir
        self.pdata = pdata
        self.pid = pid
        self._last_dir_mtime = dir_mtime
        self.main_window = main_window
        if hasattr(self, "mod_search_input"):
            self.mod_search_input.blockSignals(True)
            self.mod_search_input.clear()
            self.mod_search_input.blockSignals(False)
        if main_window and hasattr(main_window, "settings"):
            new_lang = (main_window.settings or {}).get("language", "tr")
            if getattr(self, "lang", None) != new_lang:
                self.set_language(new_lang)
            
        self.switch_sub_tab(self.sub_stack.currentIndex())

    def _filter_mods(self, query: str = None):
        if query is None:
            query = self.mod_search_input.text() if hasattr(self, "mod_search_input") else ""
        query = query.strip().lower()
        visible_count = 0
        total_count = 0
        for i in range(self.mod_list.count()):
            item = self.mod_list.item(i)
            if item.flags() == Qt.NoItemFlags:
                continue
            total_count += 1
            search_str = item.data(Qt.UserRole)
            if not search_str:
                w = self.mod_list.itemWidget(item)
                if w and hasattr(w, "title_text"):
                    search_str = f"{w.title_text} {getattr(w, 'subtitle_text', '')} {os.path.basename(getattr(w, 'filepath', ''))}".lower()
            matches = (not query) or (query in (search_str or ""))
            item.setHidden(not matches)
            if matches:
                visible_count += 1
        total_expected = len(getattr(self, "_pending_mods", [])) if getattr(self, "_pending_mods", None) else total_count
        self._update_mod_count_label(visible_count, total_expected)

    def _update_mod_count_label(self, visible_count: int, total_count: int):
        if not hasattr(self, "mod_count_lbl"):
            return
        en = self.lang == "en"
        suffix = "mods" if en else "mod"
        query = self.mod_search_input.text().strip() if hasattr(self, "mod_search_input") else ""
        if query:
            self.mod_count_lbl.setText(f"{visible_count} / {total_count} {suffix}")
        else:
            self.mod_count_lbl.setText(f"{total_count} {suffix}")
        
    def refresh_list(self):
        self._mod_load_gen = getattr(self, "_mod_load_gen", 0) + 1
        gen = self._mod_load_gen
        self.mod_list.clear()
        empty_txt = "No mods installed in this profile." if self.lang == "en" else "Bu profilde henüz mod yok."
        if not self.current_dir or not os.path.exists(self.current_dir):
            item = QListWidgetItem(empty_txt)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.mod_list.addItem(item)
            self._update_mod_count_label(0, 0)
            return
            
        mods = [f for f in os.listdir(self.current_dir) if f.endswith(".jar") or f.endswith(".jar.disabled") or f.endswith(".pak") or f.endswith(".pak.disabled")]
        
        if not mods:
            item = QListWidgetItem(empty_txt)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.mod_list.addItem(item)
            self._update_mod_count_label(0, 0)
            return
            
        mods.sort()
        self._pending_mods = mods
        self._pending_idx = 0
        self._load_mod_batch(gen, initial=True)

    def _load_mod_batch(self, gen, initial=False):
        if getattr(self, "_mod_load_gen", 0) != gen:
            return
        batch_size = 15
        end_idx = min(self._pending_idx + batch_size, len(self._pending_mods))
        query = self.mod_search_input.text().strip().lower() if hasattr(self, "mod_search_input") else ""
        
        from PySide6.QtCore import QSize, QTimer
        self.mod_list.setUpdatesEnabled(False)
        self.mod_list.blockSignals(True)
        try:
            for i in range(self._pending_idx, end_idx):
                mod = self._pending_mods[i]
                path = os.path.join(self.current_dir, mod)
                item = QListWidgetItem(self.mod_list)
                widget = ModItemWidget(path, self, lang=self.lang)
                item.setSizeHint(QSize(100, 54))
                search_str = f"{widget.title_text} {widget.subtitle_text} {mod}".lower()
                item.setData(Qt.UserRole, search_str)
                if query and query not in search_str:
                    item.setHidden(True)
                self.mod_list.setItemWidget(item, widget)
        finally:
            self.mod_list.blockSignals(False)
            self.mod_list.setUpdatesEnabled(True)
            
        self._pending_idx = end_idx
        total = len(self._pending_mods)
        self._last_loaded_count = total
        current_count = self.mod_list.count()
        self._update_mod_count_label(current_count, total)
        
        if self._pending_idx < total:
            QTimer.singleShot(16, lambda: self._load_mod_batch(gen))

    def refresh_worlds(self):
        import datetime
        self.world_list.clear()
        en = self.lang == "en"
        root = self._get_profile_root()
        saves_dir = os.path.join(root, "saves") if root else None
        if not saves_dir or not os.path.exists(saves_dir):
            item = QListWidgetItem("No saved worlds found." if en else "Bu profilde henüz kayıtlı dünya yok.")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.world_list.addItem(item)
            return
        worlds = [d for d in os.listdir(saves_dir) if os.path.isdir(os.path.join(saves_dir, d))]
        if not worlds:
            item = QListWidgetItem("No saved worlds found." if en else "Bu profilde henüz kayıtlı dünya yok.")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.world_list.addItem(item)
            return

        # Instant display with fast level.dat mtime (0ms UI freeze)
        for w in sorted(worlds):
            w_path = os.path.join(saves_dir, w)
            level_dat = os.path.join(w_path, "level.dat")
            latest_mtime = os.path.getmtime(level_dat) if os.path.exists(level_dat) else os.path.getmtime(w_path)
            dt_str = datetime.datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M")
            calc_txt = "calculating..." if en else "hesaplanıyor..."
            item = QListWidgetItem(f"{w}   •   {calc_txt}   •   {dt_str}")
            item.setData(Qt.UserRole, w_path)
            self.world_list.addItem(item)

        # Background thread for deep disk size scanning without blocking GUI
        if getattr(self, "_world_scanner_thread", None) and self._world_scanner_thread.isRunning():
            if getattr(self._world_scanner_thread, "saves_dir", None) == saves_dir:
                return
            try:
                self._world_scanner_thread.worlds_scanned.disconnect()
            except Exception:
                pass
        self._world_scanner_thread = WorldScannerThread(saves_dir, parent=self)
        self._world_scanner_thread.worlds_scanned.connect(self._on_worlds_scanned)
        self._world_scanner_thread.start()

    def _on_worlds_scanned(self, results):
        if not results:
            return
        res_map = {path: (size_mb, dt_str, name) for name, path, size_mb, dt_str in results}
        for i in range(self.world_list.count()):
            item = self.world_list.item(i)
            w_path = item.data(Qt.UserRole)
            if w_path in res_map:
                size_mb, dt_str, name = res_map[w_path]
                item.setText(f"{name}   •   {size_mb:.1f} MB   •   {dt_str}")


    def backup_selected_world(self):
        import datetime
        en = self.lang == "en"
        item = self.world_list.currentItem()
        w_path = item.data(Qt.UserRole) if item else None
        if not w_path or not os.path.exists(w_path):
            QMessageBox.information(self, "Info" if en else "Bilgi", "Please select a world first." if en else "Lütfen önce listeden bir dünya seçin.")
            return

        if getattr(self, '_world_backup_thread', None) and self._world_backup_thread.isRunning():
            QMessageBox.warning(self, "Warning" if en else "Uyarı", "A backup is already in progress, please wait." if en else "Zaten devam eden bir yedekleme var, lütfen bekleyin.")
            return

        root = self._get_profile_root()
        backups_dir = os.path.join(root, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        w_name = os.path.basename(w_path)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_zip = os.path.join(backups_dir, f"{w_name}_{stamp}")

        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass

        self.btn_world_backup.setEnabled(False)
        self.btn_world_backup.setText("Archiving..." if en else "Zipleniyor...")

        self._world_backup_thread = WorldBackupThread(base_zip, w_path, parent=self)
        self._world_backup_thread.backup_finished.connect(self._on_world_backup_finished)
        self._world_backup_thread.start()

    def _on_world_backup_finished(self, success, result):
        en = self.lang == "en"
        self.btn_world_backup.setEnabled(True)
        self.btn_world_backup.setText("Backup .zip" if en else ".zip Yedekle")
        if success:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_levelup()
            except Exception:
                pass
            QMessageBox.information(
                self,
                "Backup Created" if en else "Yedek Alındı",
                f"{'World backed up to:' if en else 'Dünya başarıyla yedeklendi:'}\n{result}"
            )
        else:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            QMessageBox.warning(self, "Error" if en else "Hata", result)

    def open_worlds_folder(self):
        root = self._get_profile_root()
        if not root:
            return
        saves_dir = os.path.join(root, "saves")
        os.makedirs(saves_dir, exist_ok=True)
        os.startfile(saves_dir)

    def delete_selected_world(self):
        import shutil
        en = self.lang == "en"
        item = self.world_list.currentItem()
        w_path = item.data(Qt.UserRole) if item else None
        if not w_path or not os.path.exists(w_path):
            return
        root = self._get_profile_root()
        if not root:
            return
        saves_real = os.path.realpath(os.path.join(root, "saves"))
        w_real = os.path.realpath(w_path)
        if not (w_real.startswith(saves_real + os.sep) and os.path.isdir(w_real)):
            return
        w_name = os.path.basename(w_real)
        msg = f"Delete world '{w_name}' permanently?" if en else f"'{w_name}' dünyasını kalıcı olarak silmek istediğinize emin misiniz?"
        if QMessageBox.question(self, "Confirm" if en else "Onay", msg, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_break()
            except Exception:
                pass
            try:
                shutil.rmtree(w_real)
                self.refresh_worlds()
            except Exception as e:
                QMessageBox.warning(self, "Error" if en else "Hata", str(e))

    def refresh_screenshots(self):
        import datetime
        from PySide6.QtGui import QIcon, QPixmap
        self.shot_list.clear()
        en = self.lang == "en"
        root = self._get_profile_root()
        shots_dir = os.path.join(root, "screenshots") if root else None
        empty_txt = "No screenshots yet." if en else "Bu profilde henüz ekran görüntüsü yok."
        if not shots_dir or not os.path.exists(shots_dir):
            item = QListWidgetItem(empty_txt)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.shot_list.addItem(item)
            return

        try:
            with os.scandir(shots_dir) as entries:
                valid_entries = [
                    (e.name, e.path, e.stat().st_mtime)
                    for e in entries
                    if e.is_file() and e.name.lower().endswith((".png", ".jpg", ".jpeg"))
                ]
        except Exception:
            valid_entries = []

        if not valid_entries:
            item = QListWidgetItem(empty_txt)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.shot_list.addItem(item)
            return

        valid_entries.sort(key=lambda item: item[2], reverse=True)
        for fname, fpath, mtime in valid_entries[:60]:
            dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            item = QListWidgetItem(f"{fname}   •   {dt_str}")
            cache_key = (fpath, mtime)
            cached_icon = _SCREENSHOT_ICON_CACHE.get(cache_key)
            if cached_icon is not None:
                item.setIcon(cached_icon)
            else:
                pix = QPixmap(fpath)
                if not pix.isNull():
                    scaled_icon = QIcon(pix.scaled(72, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    if len(_SCREENSHOT_ICON_CACHE) >= 200:
                        _SCREENSHOT_ICON_CACHE.pop(next(iter(_SCREENSHOT_ICON_CACHE)), None)
                    _SCREENSHOT_ICON_CACHE[cache_key] = scaled_icon
                    item.setIcon(scaled_icon)
            item.setData(Qt.UserRole, fpath)
            self.shot_list.addItem(item)

    def open_selected_screenshot(self):
        item = self.shot_list.currentItem()
        fpath = item.data(Qt.UserRole) if item else None
        if fpath and os.path.exists(fpath):
            os.startfile(fpath)

    def copy_selected_screenshot(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage
        en = self.lang == "en"
        item = self.shot_list.currentItem()
        fpath = item.data(Qt.UserRole) if item else None
        if not fpath or not os.path.exists(fpath):
            return
        img = QImage(fpath)
        if not img.isNull():
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_pop()
            except Exception:
                pass
            QApplication.clipboard().setImage(img)
            QMessageBox.information(self, "Copied" if en else "Kopyalandı", "Screenshot copied to clipboard!" if en else "Ekran görüntüsü panoya kopyalandı!")

    def open_screenshots_folder(self):
        root = self._get_profile_root()
        if not root:
            return
        shots_dir = os.path.join(root, "screenshots")
        os.makedirs(shots_dir, exist_ok=True)
        os.startfile(shots_dir)

    def delete_selected_screenshot(self):
        en = self.lang == "en"
        item = self.shot_list.currentItem()
        fpath = item.data(Qt.UserRole) if item else None
        if not fpath or not os.path.exists(fpath):
            return
        root = self._get_profile_root()
        if not root:
            return
        shots_real = os.path.realpath(os.path.join(root, "screenshots"))
        f_real = os.path.realpath(fpath)
        if not (f_real.startswith(shots_real + os.sep) and os.path.isfile(f_real)):
            return
        if QMessageBox.question(self, "Confirm" if en else "Onay", "Delete this screenshot?" if en else "Bu ekran görüntüsü silinsin mi?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_break()
            except Exception:
                pass
            try:
                os.remove(f_real)
                self.refresh_screenshots()
            except Exception as e:
                QMessageBox.warning(self, "Error" if en else "Hata", str(e))

    def _diagnose_log_text(self, content, is_crash_report=False, exit_code=0):
        import re
        en = self.lang == "en"
        if not content.strip():
            return "No log data generated yet." if en else "Henüz log veya çökme kaydı oluşmadı."
        if "OutOfMemoryError" in content or "Java heap space" in content:
            return (
                "Diagnosis: Out of Memory (RAM). Increase profile RAM in Settings or Profile Edit."
                if en else
                "Teşhis: Bellek (RAM) Yetersizliği (`OutOfMemoryError`). Profilin RAM miktarını artırın."
            )
        if "UnsupportedClassVersionError" in content or "class file version" in content:
            return (
                "Diagnosis: Incompatible Java Version (`UnsupportedClassVersionError`). Reset custom Java path in Settings or install Java 17/21."
                if en else
                "Teşhis: Uyumsuz Java Sürümü (`UnsupportedClassVersionError`). Ayarlar'dan Özel Java Yolunu sıfırlayın veya uygun Java (17/21) sürümünü seçin."
            )
        mod_match = re.search(r"(?:Mod ID|modid|Mod|missing mandatory dependencies|ModResolutionException|FormattedException)[^\n]{0,120}", content, re.IGNORECASE)
        if mod_match or "Missing or unsupported mandatory dependencies" in content or "net.fabricmc.loader.impl.FormattedException" in content or "ModLoadingException" in content:
            snippet = mod_match.group(0).strip() if mod_match else ""
            return (
                f"Diagnosis: Missing or incompatible Mod dependency! {snippet}"
                if en else
                f"Teşhis: Eksik kütüphane modu veya uyumsuz mod çakışması! ({snippet})"
            )
        if "MixinApplyError" in content or "MixinTransformerError" in content or "MixinPrepareError" in content:
            return (
                "Diagnosis: Mixin Mod Conflict (`MixinApplyError`). Disable recently added mods in the Mods tab."
                if en else
                "Teşhis: Mixin Mod Çakışması (`MixinApplyError`). Son eklediğiniz modları Modlar sekmesinden devre dışı bırakıp deneyin."
            )
        if is_crash_report or (exit_code and exit_code != 0):
            return (
                f"Crash / Non-zero exit detected (Code: {exit_code}). Check stack trace below."
                if en else
                f"Oyun hata ile kapandı (Çıkış kodu: {exit_code}). Aşağıdaki hata dökümünü inceleyin."
            )
        return "Latest session log looks healthy (no crash signature detected)." if en else "Son oturum logu normal görünüyor (çökme imzası tespit edilmedi)."

    def refresh_logs(self, exit_code=0):
        root = self._get_profile_root()
        en = self.lang == "en"
        if not root or not os.path.exists(root):
            self.lbl_crash_diagnosis.setText("Select a profile first." if en else "Lütfen önce bir profil seçin.")
            self.log_viewer.setPlainText("")
            return
        crash_dir = os.path.join(root, "crash-reports")
        latest_log = os.path.join(root, "logs", "latest.log")
        chosen_file = None
        is_crash = False
        if os.path.exists(crash_dir):
            c_files = [os.path.join(crash_dir, f) for f in os.listdir(crash_dir) if f.endswith(".txt") or f.endswith(".log")]
            if c_files:
                c_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                # Prefer crash report if newer than latest.log or if exit_code != 0
                if exit_code != 0 or not os.path.exists(latest_log) or os.path.getmtime(c_files[0]) >= os.path.getmtime(latest_log) - 10:
                    chosen_file = c_files[0]
                    is_crash = True
        if not chosen_file and os.path.exists(latest_log):
            chosen_file = latest_log
        if not chosen_file:
            self.lbl_crash_diagnosis.setText("No logs or crash reports found in this profile yet." if en else "Bu profilde henüz log veya çökme raporu bulunmuyor.")
            self.log_viewer.setPlainText("")
            return
        try:
            file_size = os.path.getsize(chosen_file)
            buffer_size = min(file_size, 262144)
            with open(chosen_file, "rb") as f:
                if file_size > buffer_size:
                    f.seek(file_size - buffer_size)
                raw_bytes = f.read()
            text = raw_bytes.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            content = "".join(lines[-400:])
        except Exception as e:
            content = str(e)
        diag = self._diagnose_log_text(content, is_crash_report=is_crash, exit_code=exit_code)
        self.lbl_crash_diagnosis.setText(f"{diag}\n{os.path.basename(chosen_file)}")
        if "Diagnosis:" in diag or "Teşhis:" in diag or "Crash" in diag or "hata ile kapandı" in diag:
            self.lbl_crash_diagnosis.setStyleSheet("background-color: rgba(60, 20, 25, 0.95); border: 1px solid #FF5555; border-radius: 8px; padding: 10px; font-size: 12px; font-weight: bold; color: #FFD2D2;")
        else:
            self.lbl_crash_diagnosis.setStyleSheet("background-color: rgba(20, 42, 35, 0.95); border: 1px solid #10B981; border-radius: 8px; padding: 10px; font-size: 12px; font-weight: bold; color: #D1FAE5;")
        self.log_viewer.setPlainText(content)
        sb = self.log_viewer.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def show_crash_analysis(self, exit_code=1):
        self.switch_sub_tab(3)
        self.refresh_logs(exit_code=exit_code)

    def copy_log_report(self):
        from PySide6.QtWidgets import QApplication
        en = self.lang == "en"
        txt = self.lbl_crash_diagnosis.text() + "\n\n" + self.log_viewer.toPlainText()
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_pop()
        except Exception:
            pass
        QApplication.clipboard().setText(txt)
        QMessageBox.information(self, "Copied" if en else "Kopyalandı", "Crash/Log report copied to clipboard!" if en else "Log ve teşhis raporu panoya kopyalandı!")

    def open_logs_folder(self):
        root = self._get_profile_root()
        if not root:
            return
        crash_dir = os.path.join(root, "crash-reports")
        logs_dir = os.path.join(root, "logs")
        target = crash_dir if os.path.exists(crash_dir) and os.listdir(crash_dir) else logs_dir
        os.makedirs(target, exist_ok=True)
        os.startfile(target)

class UserCard(QFrame):
    login_requested = Signal()
    logout_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UserCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QFrame#UserCard {
                background-color: #222227;
                border: 1px solid #2E2E36;
                border-top: 1px solid #3A3A42;
                border-bottom: 2px solid #18181C;
                border-radius: 4px;
            }
            QFrame#UserCard:hover {
                background-color: #28282E;
                border-color: #3C3C48;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        
        self.avatar_lbl = QLabel("")
        self.avatar_lbl.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        layout.addWidget(self.avatar_lbl)
        
        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)
        info_layout.setContentsMargins(0, 0, 0, 0)
        
        self.name_lbl = QLabel("Misafir")
        self.name_lbl.setStyleSheet("font-family: 'Segoe UI', -apple-system, sans-serif; font-size: 11.5px; font-weight: 700; color: #F8FAFC; background: transparent; border: none;")
        info_layout.addWidget(self.name_lbl)
        
        self.status_lbl = QLabel("Giriş Yapılmadı ▾")
        self.status_lbl.setStyleSheet("font-size: 10px; color: #94A3B8; background: transparent; border: none;")
        info_layout.addWidget(self.status_lbl)
        
        layout.addLayout(info_layout, 1)
        
        self.is_logged_in = False
        self.user_name = ""
        self.lang = "tr"

    def set_language(self, lang="tr"):
        self.lang = lang
        self._update_display()

    def update_user(self, name: str, is_logged_in: bool):
        self.is_logged_in = is_logged_in
        self.user_name = name or ""
        self._update_display()

    def _update_display(self):
        en = self.lang == "en"
        self.avatar_lbl.setFixedSize(30, 30)
        self.avatar_lbl.setAlignment(Qt.AlignCenter)
        if self.is_logged_in and self.user_name:
            self.name_lbl.setText(self.user_name)
            self.status_lbl.setText("Microsoft ▾")
            self.status_lbl.setStyleSheet("font-size: 10px; color: #34D399; background: transparent; border: none;")
            initial = self.user_name[0].upper() if self.user_name else "M"
            self.avatar_lbl.setText(initial)
            self.avatar_lbl.setStyleSheet("background-color: #7C3AED; color: #FFFFFF; font-weight: 900; font-size: 13px; border-radius: 15px; border: 1px solid #A78BFA;")
        else:
            self.name_lbl.setText("Guest" if en else "Misafir")
            self.status_lbl.setText("Sign In ▾" if en else "Giriş Yapılmadı ▾")
            self.status_lbl.setStyleSheet("font-size: 10px; color: #94A3B8; background: transparent; border: none;")
            self.avatar_lbl.setText("")
            self.avatar_lbl.setStyleSheet("font-size: 14px; background: rgba(255, 255, 255, 0.05); border-radius: 15px; border: 1px solid #282830;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._show_menu()
        super().mousePressEvent(event)

    def _show_menu(self):
        en = self.lang == "en"
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1A1A1E;
                color: #F8FAFC;
                border: 1px solid #282830;
                border-radius: 6px;
                padding: 4px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2E2E38;
                color: #FFFFFF;
            }
        """)
        
        act_login = menu.addAction("Sign In / Switch Account" if en else "Giriş Yap / Hesap Değiştir")
        act_login.triggered.connect(lambda checked=False: self.login_requested.emit())
        
        if self.is_logged_in:
            act_logout = menu.addAction("Sign Out" if en else "Hesaptan Çık")
            act_logout.triggered.connect(lambda checked=False: self.logout_requested.emit())
            
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))


class NavButton(QPushButton):
    def __init__(self, icon_text, parent=None):
        super().__init__(icon_text, parent)
        self.setObjectName("NavButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(38)

class NavBar(QFrame):
    nav_clicked = Signal(str)
    game_changed = Signal(str)
    login_clicked = Signal()
    logout_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavBar")
        self.setFixedWidth(210)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(8)
        
        self.user_card = UserCard()
        self.user_card.login_requested.connect(self.login_clicked)
        self.user_card.logout_requested.connect(self.logout_clicked)
        layout.addWidget(self.user_card)
        
        self.game_selector = QComboBox()
        self.game_selector.addItems(["Minecraft: Java Edition", "Minecraft for Windows"])
        self.game_selector.setStyleSheet("""
            QComboBox {
                background-color: #141416;
                color: #F8FAFC;
                padding: 8px 12px;
                border: 1px solid #282830;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 700;
            }
            QComboBox:hover {
                border-color: #8B5CF6;
            }
        """)
        self.game_selector.currentTextChanged.connect(self.on_game_change)
        layout.addWidget(self.game_selector)
        
        self.btns = {}
        tabs = {
            "home": "Profiller",
            "packs": "Modpaketleri",
            "mods": "Modlar",
            "shaders": "Shaderlar",
            "bedrock_home": "Oyna (Bedrock)",
            "server": "Sunucum"
        }
        
        for key, text in tabs.items():
            btn = NavButton(text)
            btn.clicked.connect(lambda checked=False, k=key: self.on_nav_click(k))
            self.btns[key] = btn
            layout.addWidget(btn)
            
        layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.settings_btn = NavButton("⚙️ Ayarlar")
        self.settings_btn.clicked.connect(lambda checked=False: self.on_nav_click("settings"))
        self.btns["settings"] = self.settings_btn
        layout.addWidget(self.settings_btn)
        
        self.on_game_change("Minecraft: Java Edition")

    def update_user(self, name: str, is_logged_in: bool):
        self.user_card.update_user(name, is_logged_in)

    def set_language(self, lang="tr"):
        self.user_card.set_language(lang)
        if lang == "en":
            labels = {
                "home": "Profiles",
                "packs": "Modpacks",
                "mods": "Mods",
                "shaders": "Shaders",
                "bedrock_home": "Play (Bedrock)",
                "server": "My Server",
                "settings": "⚙️ Settings",
            }
        else:
            labels = {
                "home": "Profiller",
                "packs": "Modpaketleri",
                "mods": "Modlar",
                "shaders": "Shaderlar",
                "bedrock_home": "Oyna (Bedrock)",
                "server": "Sunucum",
                "settings": "⚙️ Ayarlar",
            }
        for k, text in labels.items():
            if k in self.btns:
                self.btns[k].setText(text)

    def on_game_change(self, game_name):
        for k, btn in self.btns.items():
            if k != "settings":
                btn.hide()
        self.btns["settings"].show()
            
        if game_name == "Minecraft: Java Edition":
            self.btns["home"].show()
            self.btns["packs"].show()
            self.btns["mods"].show()
            self.btns["shaders"].show()
            self.btns["server"].show()
            self.on_nav_click("home", play_sound=False)
        elif game_name == "Minecraft for Windows":
            self.btns["bedrock_home"].show()
            self.on_nav_click("bedrock_home", play_sound=False)
            
        self.game_changed.emit(game_name)

    def on_nav_click(self, key, play_sound=True):
        if play_sound:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_book_flip()
            except Exception:
                pass
        for k, b in self.btns.items():
            b.setProperty("active", str(k == key).lower())
            b.style().unpolish(b)
            b.style().polish(b)
        self.nav_clicked.emit(key)

    def set_theme(self, theme_key: str):
        self._active_theme = theme_key
        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            r, g, b = t["rgb"]
            prim_light = t["primary_light"]
            self.game_selector.setStyleSheet(f"""
                QComboBox {{
                    background-color: #141416;
                    color: #F8FAFC;
                    padding: 8px 12px;
                    border: 1px solid #282830;
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                QComboBox:hover {{
                    border-color: {prim_light};
                }}
            """)
            for b in self.btns.values():
                b.style().unpolish(b)
                b.style().polish(b)
                b.update()
        except Exception:
            pass

class PlayButton(QPushButton):
    """
    3D beveled physical Mojang gaming button with pressed-state translation.
    """
    def __init__(self, text="OYNA", parent=None):
        super().__init__(text, parent)
        self.setObjectName("PlayButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(180, 44)


class ActionBar(QFrame):
    play_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ActionBar")
        self.setFixedHeight(64)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 4, 20, 4)
        layout.setSpacing(12)
        
        # Left Capsule (Profile info & badges)
        self.info_layout = QVBoxLayout()
        self.info_layout.setSpacing(2)
        self.info_layout.setAlignment(Qt.AlignVCenter)
        
        self.pack_name = QLabel("Seçili Profil Yok")
        self.pack_name.setStyleSheet("font-size: 15px; font-weight: 800; color: #F8FAFC; background: transparent;")
        
        self.badge_row = QHBoxLayout()
        self.badge_row.setSpacing(6)
        self.badge_row.setAlignment(Qt.AlignVCenter)
        
        self.badge_ver = QLabel("v --")
        self.badge_ver.setStyleSheet("background: rgba(139, 92, 246, 0.16); color: #C084FC; border: 1px solid rgba(139, 92, 246, 0.28); border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 700;")
        
        self.badge_sep1 = QLabel("·")
        self.badge_sep1.setStyleSheet("color: #475569; font-weight: bold; font-size: 12px; background: transparent;")

        self.badge_loader = QLabel("Vanilla")
        self.badge_loader.setStyleSheet("color: #CBD5E1; font-size: 11px; font-weight: 600; background: transparent;")
        
        self.badge_sep2 = QLabel("·")
        self.badge_sep2.setStyleSheet("color: #475569; font-weight: bold; font-size: 12px; background: transparent;")

        self.badge_ram = QLabel("4096 MB")
        self.badge_ram.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 500; background: transparent;")
        
        self.badge_row.addWidget(self.badge_ver)
        self.badge_row.addWidget(self.badge_sep1)
        self.badge_row.addWidget(self.badge_loader)
        self.badge_row.addWidget(self.badge_sep2)
        self.badge_row.addWidget(self.badge_ram)
        self.badge_row.addStretch()
        
        self.pack_size = QLabel("")
        self.pack_size.setVisible(False)
        
        self.info_layout.addWidget(self.pack_name)
        self.info_layout.addLayout(self.badge_row)
        layout.addLayout(self.info_layout)
        
        layout.addStretch()
        
        # Center: Command Deck (OYNA Button + Progress bar)
        self.center_layout = QVBoxLayout()
        self.center_layout.setAlignment(Qt.AlignCenter)
        self.center_layout.setSpacing(2)
        
        self.play_btn = PlayButton("OYNA")
        self.play_btn.clicked.connect(self.play_clicked.emit)
        self.center_layout.addWidget(self.play_btn)
        
        self.progress = QProgressBar()
        self.progress.setFixedSize(180, 4)
        self.progress.setVisible(False)
        self.center_layout.addWidget(self.progress)
        layout.addLayout(self.center_layout)
        
        layout.addStretch()
        
        # Right: Quick utilities
        right_layout = QHBoxLayout()
        self.folder_btn = QPushButton(".MİNECRAFT")
        self.folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #222228;
                color: #E4E4E7;
                border: 1px solid #18181C;
                border-top: 1.5px solid #3E3E48;
                border-left: 1px solid #2E2E36;
                border-right: 1px solid #1A1A1E;
                border-bottom: 3px solid #141418;
                border-radius: 4px;
                padding: 6px 14px;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2A2A32;
                border-top: 1.5px solid #525260;
                color: #FFFFFF;
            }
            QPushButton:pressed {
                border-top: 2px solid #141418;
                border-bottom: 1px solid #3E3E48;
                padding-top: 8px;
            }
        """)
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        right_layout.addWidget(self.folder_btn)
        layout.addLayout(right_layout)

    def set_profile_badges(self, version_str, loader_str, ram_mb):
        disp_v = str(version_str).replace("fabric-loader-", "fabric-") if version_str else "--"
        self.badge_ver.setText(f"v {disp_v}")
        self.badge_loader.setText(str(loader_str).capitalize() if loader_str else "Vanilla")
        self.badge_ram.setText(f"{ram_mb} MB" if ram_mb else "-- MB")
        has_v = bool(version_str)
        has_l = bool(loader_str or version_str)
        has_r = bool(ram_mb)
        self.badge_ver.setVisible(has_v)
        if hasattr(self, "badge_sep1"):
            self.badge_sep1.setVisible(has_v and has_l)
        self.badge_loader.setVisible(has_l)
        if hasattr(self, "badge_sep2"):
            self.badge_sep2.setVisible(has_l and has_r)
        self.badge_ram.setVisible(has_r)

    def set_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        cur_txt = self.play_btn.text()
        if cur_txt in ("OYNA", "PLAY"):
            self.play_btn.setText("PLAY" if en else "OYNA")
        elif cur_txt in ("İndiriliyor...", "Downloading..."):
            self.play_btn.setText("Downloading..." if en else "İndiriliyor...")
        elif cur_txt in ("Başlatılıyor...", "Starting..."):
            self.play_btn.setText("Starting..." if en else "Başlatılıyor...")
        elif cur_txt in ("OYUNDA", "IN GAME"):
            self.play_btn.setText("IN GAME" if en else "OYUNDA")
        elif cur_txt in ("Giriş doğrulanıyor...", "Verifying login..."):
            self.play_btn.setText("Verifying login..." if en else "Giriş doğrulanıyor...")
        if self.pack_name.text() in ("Seçili Profil Yok", "No Profile Selected", "Profil Seçilmedi"):
            self.pack_name.setText("No Profile Selected" if en else "Seçili Profil Yok")

    def set_theme(self, theme_key: str):
        self._active_theme = theme_key
        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            r, g, b = t["rgb"]
            glow = t["glow"]
            primary = t.get("primary", "#8B5CF6")
            bevel_top = t.get("bevel_top", primary)
            self.badge_ver.setStyleSheet(f"background: rgba({r}, {g}, {b}, 0.16); color: {glow}; border: 1px solid rgba({r}, {g}, {b}, 0.28); border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 700;")
            self.badge_loader.setStyleSheet("color: #CBD5E1; font-size: 11px; font-weight: 600; background: transparent;")
            self.badge_ram.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 500; background: transparent;")
            self.folder_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #222228;
                    color: #A1A1AA;
                    border: 1px solid #282830;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: #282830;
                    border-color: {bevel_top};
                    color: #FFFFFF;
                }}
            """)
            if hasattr(self, "play_btn"):
                self.play_btn.style().unpolish(self.play_btn)
                self.play_btn.style().polish(self.play_btn)
                self.play_btn.update()
            if hasattr(self, "progress"):
                self.progress.style().unpolish(self.progress)
                self.progress.style().polish(self.progress)
                self.progress.update()
        except Exception:
            pass

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
                               QDialog, QProgressBar, QInputDialog, QProgressDialog, QApplication, QFrame, QGridLayout)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QFileSystemWatcher
from PySide6.QtGui import QColor
from server_thread import MinecraftServerThread
from mod_manager import ModrinthAPI, ModrinthSearchThread, ModrinthDownloadThread
from profile_store import ProfileAndConfigStore
from runtime_provisioner import RuntimeProvisioner
from server_instance import (
    ServerInstance,
    ServerProperties,
    DEFAULT_SERVER_PROPERTIES,
    CLIENT_MODS_BLACKLIST,
)
from backup_manager import BackupManager, GoogleDriveBackupAdapter
from server_downloader import ServerSoftwareDialog
from sound_manager import SoundManager
from server_console_parser import ServerConsoleParser, ConsoleEvent
from server_process_coordinator import ServerProcessCoordinator, ServerState

def get_base_dir():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    data_dir = os.path.join(appdata, ".vega_launcher")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir

class ProfileSelectDialog(QDialog):
    def __init__(self, profiles, parent=None, lang=None):
        super().__init__(parent)
        if lang is None:
            lang = getattr(parent, "lang", "tr") if parent else "tr"
        self.lang = lang
        en = self.lang == "en"
        self.setWindowTitle("Select Client Profile" if en else "İstemci Profili Seç")
        self.setFixedSize(360, 140)
        self.setStyleSheet("background-color: #2D2D30; color: white;")
        layout = QVBoxLayout(self)
        
        lbl = QLabel("Select client profile to export:" if en else "Aktarılacak istemci profilini seçin:")
        layout.addWidget(lbl)
        
        self.combo = QComboBox()
        self.combo.addItems(profiles)
        self.combo.setStyleSheet("padding: 5px; background: #1E1E1E; color: white;")
        layout.addWidget(self.combo)
        
        
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("Select" if en else "Seç")
        self.btn_ok.setDefault(True)
        self.btn_ok.setStyleSheet("background-color: #007ACC; padding: 6px 15px; font-weight: bold; border-radius: 4px;")
        if not profiles:
            self.btn_ok.setEnabled(False)
        self.btn_cancel = QPushButton("Cancel" if en else "İptal")
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
    
    def __init__(self, server_dir, delete_local=False, server_thread=None, cloud_adapter=None, lang="tr", coordinator=None):
        super().__init__()
        self.server_dir = server_dir
        self.delete_local = delete_local
        self.server_thread = server_thread
        self.cloud_adapter = cloud_adapter
        self.lang = lang
        self.coordinator = coordinator
        
    def run(self):
        en = self.lang == "en"
        coord = self.coordinator
        if coord is None and self.server_thread is not None:
            coord = getattr(self.server_thread, "coordinator", None) or ServerProcessCoordinator()
            if coord._thread is not self.server_thread:
                coord.attach_thread(self.server_thread)
        elif coord is not None and self.server_thread is not None and coord._thread is not self.server_thread:
            coord.attach_thread(self.server_thread)

        quiesce_cm = None

        def _before():
            nonlocal quiesce_cm
            if coord and coord.is_running():
                self.stage_update.emit(
                    "Saving server world (save-off / save-all)..."
                    if en else
                    "Sunucu dünyası kaydediliyor (save-off / save-all)..."
                )
                quiesce_cm = coord.quiesce_for_backup(flush_timeout_sec=3.0)
                quiesce_cm.__enter__()

        def _after():
            nonlocal quiesce_cm
            if quiesce_cm is not None:
                try:
                    quiesce_cm.__exit__(None, None, None)
                finally:
                    quiesce_cm = None

        adapter = self.cloud_adapter or GoogleDriveBackupAdapter(
            base_dir=get_base_dir(),
            app_dir=os.path.dirname(os.path.abspath(__file__)),
        )
        ok, msg = BackupManager.run_server_backup(
            self.server_dir,
            delete_local=self.delete_local,
            on_stage=self.stage_update.emit,
            on_progress=self.progress_update.emit,
            before_archive=_before,
            after_archive=_after,
            cloud_adapter=adapter,
            lang=self.lang,
        )
        self.backup_finished.emit(ok, msg)


class RestoreThread(QThread):
    restore_finished = Signal(bool, str)
    
    def __init__(self, server_dir, zip_path, lang="tr"):
        super().__init__()
        self.server_dir = server_dir
        self.zip_path = zip_path
        self.lang = lang
        
    def run(self):
        en = self.lang == "en"
        try:
            BackupManager.restore_archive_safely(self.zip_path, self.server_dir)
            self.restore_finished.emit(True, "Backup restored successfully!" if en else "Yedek başarıyla geri yüklendi!")
        except Exception as e:
            self.restore_finished.emit(False, f"Restore error: {str(e)}" if en else f"Geri yükleme hatası: {str(e)}")

def detect_server_loader_and_version(server_dir):
    """Detect Minecraft server version and loader from server directory."""
    if not server_dir or not os.path.exists(server_dir):
        return None, None
    spec = RuntimeProvisioner.detect_server_runtime(server_dir)
    return spec.loader, spec.mc_version


class ServerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.server_thread = None
        self._api_threads = []
        self.console_parser = ServerConsoleParser()
        self.process_coordinator = ServerProcessCoordinator(parser=self.console_parser)
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
            
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(14)
        
        # Sol Panel (Başlık + Sunucu Seçici + Sekmeler)
        left_panel = QFrame()
        left_panel.setFixedWidth(280)
        left_panel.setStyleSheet("""
            QFrame#ServerLeftPanel {
                background-color: rgba(20, 20, 25, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
            }
        """)
        left_panel.setObjectName("ServerLeftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 16, 14, 16)
        left_layout.setSpacing(10)
        
        self.lang = "tr"
        self.lbl_srv_title = QLabel("Sunucu Profilleri")
        self.lbl_srv_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #F8FAFC; background: transparent; border: none;")
        left_layout.addWidget(self.lbl_srv_title)
        
        self.lbl_srv_info = QLabel("Farklı sunucular oluşturun ve istediğiniz zaman aralarında geçiş yapın.")
        self.lbl_srv_info.setWordWrap(True)
        self.lbl_srv_info.setStyleSheet("color: #94A3B8; font-size: 12px; margin-bottom: 4px; background: transparent; border: none;")
        left_layout.addWidget(self.lbl_srv_info)
        
        # Kırmızı Kısım: Sunucu Seçici
        server_sel_box = QVBoxLayout()
        server_sel_box.setSpacing(6)
        self.lbl_srv_sel = QLabel("Sunucu Seç:")
        self.lbl_srv_sel.setStyleSheet("font-size: 13px; font-weight: bold; color: #94A3B8; margin-left: 4px; background: transparent; border: none;")
        self.server_selector = QComboBox()
        self.server_selector.setStyleSheet("""
            QComboBox {
                background-color: rgba(22, 22, 32, 0.95);
                color: #F8FAFC;
                padding: 10px 14px;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
                border: 1px solid rgba(139, 92, 246, 0.35);
            }
            QComboBox:hover {
                border: 1px solid #A855F7;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
        """)
        self.server_selector.currentTextChanged.connect(self.on_server_selected)
        server_sel_box.addWidget(self.lbl_srv_sel)
        server_sel_box.addWidget(self.server_selector)
        left_layout.addLayout(server_sel_box)
        
        # Yeşil Kısım: Sol Menü (QListWidget - En soldaki menüyle birebir aynı 18px bold font)
        self.side_tabs = QListWidget()
        self.side_tabs.setFocusPolicy(Qt.NoFocus)
        self.side_tabs.setObjectName("ServerSideTabs")
        tabs = [
            "Kontrol Paneli",
            "Konsol",
            "Ayarlar",
            "Oyuncular",
            "Yedekler",
            "Modlar/Eklentiler"
        ]
        from PySide6.QtCore import QSize
        for t in tabs:
            item = QListWidgetItem(t)
            item.setSizeHint(QSize(100, 50))
            self.side_tabs.addItem(item)
            
        left_layout.addWidget(self.side_tabs, 1)
        main_layout.addWidget(left_panel)
        
        # Sağ İçerik (Mavi Kısım: QStackedWidget)
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget, 1)
        
        # 1. Sayfa: Kontrol Paneli (Orta Özet & Mini Konsol + Sağda Aksiyon Paneli)
        page_kontrol = QWidget()
        page_kontrol_layout = QHBoxLayout(page_kontrol)
        page_kontrol_layout.setContentsMargins(0, 0, 0, 0)
        page_kontrol_layout.setSpacing(12)
        
        # Orta Alan: 2x2 Özet Kartları + Canlı Mini Konsol
        from PySide6.QtWidgets import QSizePolicy
        center_dashboard = QWidget()
        center_dashboard.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        center_dashboard.setMinimumWidth(0)
        center_layout = QVBoxLayout(center_dashboard)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(10)
        
        telemetry_box = QFrame()
        telemetry_box.setObjectName("UnifiedTelemetry")
        telemetry_box.setFixedHeight(102)
        telemetry_box.setStyleSheet("#UnifiedTelemetry { background-color: #1A1A1E; border: 1px solid #282830; border-radius: 6px; }")
        
        cards_grid = QGridLayout(telemetry_box)
        cards_grid.setContentsMargins(8, 4, 8, 4)
        cards_grid.setSpacing(6)
        cards_grid.setColumnStretch(0, 1)
        cards_grid.setColumnStretch(1, 1)
        
        self.summary_cards = []
        self.summary_card_subs = []
        
        def _make_card(header_text, main_text, sub_text, on_click, sound_type="teleport"):
            card = QFrame()
            card.setObjectName("ServerSummaryCard")
            card.setCursor(Qt.PointingHandCursor)
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            card.setStyleSheet("#ServerSummaryCard { background-color: transparent; border: none; } #ServerSummaryCard:hover { background-color: rgba(255, 255, 255, 0.04); border-radius: 4px; }")
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(8, 4, 8, 4)
            c_layout.setSpacing(1)
            lbl_h = QLabel(header_text)
            lbl_h.setMinimumWidth(0)
            lbl_h.setStyleSheet("font-size: 11px; font-weight: bold; color: #888888; background: transparent; border: none;")
            lbl_m = QLabel(main_text)
            lbl_m.setMinimumWidth(0)
            lbl_m.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF; background: transparent; border: none;")
            lbl_s = QLabel(sub_text)
            lbl_s.setMinimumWidth(0)
            lbl_s.setStyleSheet("font-size: 11px; color: #C084FC; background: transparent; border: none;")
            c_layout.addWidget(lbl_h)
            c_layout.addWidget(lbl_m)
            c_layout.addWidget(lbl_s)
            def _handle_card_click(event):
                if event.button() == Qt.LeftButton:
                    try:
                        from sound_manager import SoundManager
                        if sound_type == "pop":
                            SoundManager.get_instance().play_pop()
                        else:
                            self._shortcut_teleport_nav = True
                            SoundManager.get_instance().play_teleport()
                    except Exception:
                        pass
                    on_click()
                    self._shortcut_teleport_nav = False
            card.mousePressEvent = _handle_card_click
            self.summary_cards.append(card)
            self.summary_card_subs.append(lbl_s)
            return card, lbl_h, lbl_m, lbl_s

        card_sw, self.lbl_card_sw_hdr, self.lbl_card_software, self.lbl_card_software_sub = _make_card(
            "YAZILIM & DÜNYA", "Kontrol Ediliyor...", "Ayarlara git ➔",
            lambda: self.side_tabs.setCurrentRow(2),
            sound_type="teleport"
        )
        card_addr, self.lbl_card_addr_hdr, self.lbl_card_address, self.lbl_card_address_sub = _make_card(
            "BAĞLANTI ADRESİ", "localhost:25565", "Kopyala",
            self.copy_server_address,
            sound_type="pop"
        )
        card_pl, self.lbl_card_pl_hdr, self.lbl_card_players, self.lbl_card_players_sub = _make_card(
            "OYUNCULAR", "0 / 20 Çevrimiçi", "Oyunculara git ➔",
            lambda: self.side_tabs.setCurrentRow(3),
            sound_type="teleport"
        )
        card_cnt, self.lbl_card_cnt_hdr, self.lbl_card_content, self.lbl_card_content_sub = _make_card(
            "MOD & YEDEK", "0 Mod • 0 Yedek", "Modlar & Yedekler ➔",
            lambda: self.side_tabs.setCurrentRow(5),
            sound_type="teleport"
        )
        
        cards_grid.addWidget(card_sw, 0, 0)
        cards_grid.addWidget(card_addr, 0, 1)
        cards_grid.addWidget(card_pl, 1, 0)
        cards_grid.addWidget(card_cnt, 1, 1)
        center_layout.addWidget(telemetry_box)
        
        # Alt Kısım: Canlı Mini Konsol (Filtreleme + Log Akışı + Komut Gönderme)
        mini_console_frame = QFrame()
        mini_console_frame.setObjectName("MiniConsoleFrame")
        mini_console_frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        mini_console_frame.setStyleSheet("""
            QFrame#MiniConsoleFrame {
                background-color: #141416;
                border: 1px solid #282830;
                border-radius: 6px;
            }
        """)
        mc_layout = QVBoxLayout(mini_console_frame)
        mc_layout.setContentsMargins(10, 8, 10, 10)
        mc_layout.setSpacing(6)
        
        mc_header = QHBoxLayout()
        mc_header.setSpacing(8)
        self.lbl_mc_title = QLabel("Konsol")
        self.lbl_mc_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #C084FC; background: transparent; border: none;")
        mc_header.addWidget(self.lbl_mc_title)
        mc_header.addStretch()

        chk_style = "QCheckBox { font-size: 11px; color: #CBD5E1; background: transparent; spacing: 4px; }"
        self.mini_chk_info = QCheckBox("INFO")
        self.mini_chk_info.setChecked(True)
        self.mini_chk_info.setStyleSheet(chk_style)
        self.mini_chk_warn = QCheckBox("WARN")
        self.mini_chk_warn.setChecked(True)
        self.mini_chk_warn.setStyleSheet(chk_style)
        self.mini_chk_error = QCheckBox("ERROR")
        self.mini_chk_error.setChecked(True)
        self.mini_chk_error.setStyleSheet(chk_style)
        mc_header.addWidget(self.mini_chk_info)
        mc_header.addWidget(self.mini_chk_warn)
        mc_header.addWidget(self.mini_chk_error)
        
        self.btn_goto_console = QPushButton("Tam Konsol ➔")
        self.btn_goto_console.setCursor(Qt.PointingHandCursor)
        self.btn_goto_console.setStyleSheet("""
            QPushButton {
                background-color: rgba(139, 92, 246, 0.15);
                color: #C084FC;
                border: 1px solid rgba(139, 92, 246, 0.35);
                border-radius: 6px;
                padding: 3px 8px;
                font-family: 'Minecraft Five', 'Segoe UI';
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(139, 92, 246, 0.28);
                color: white;
            }
        """)
        def _on_goto_console(checked=False):
            self._shortcut_teleport_nav = True
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_teleport()
            except Exception:
                pass
            self.side_tabs.setCurrentRow(1)
            self._shortcut_teleport_nav = False
        self.btn_goto_console.clicked.connect(_on_goto_console)
        mc_header.addWidget(self.btn_goto_console)
        mc_layout.addLayout(mc_header)
        
        self.mini_console = QPlainTextEdit()
        self.mini_console.setReadOnly(True)
        self.mini_console.setMinimumSize(0, 0)
        self.mini_console.setMaximumBlockCount(2000)
        self.mini_console.setPlaceholderText("Sunucu logları burada canlı olarak akacaktır...")
        self.mini_console.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0C0C0E;
                color: #E2E8F0;
                font-family: Consolas, monospace;
                font-size: 11px;
                border: 1px solid #242428;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        mc_layout.addWidget(self.mini_console, 1)

        mc_cmd_layout = QHBoxLayout()
        mc_cmd_layout.setSpacing(6)
        self.mini_cmd_input = QLineEdit()
        self.mini_cmd_input.setMinimumWidth(0)
        self.mini_cmd_input.setPlaceholderText("Sunucuya komut gönder... (örn: op isminiz)")
        self.mini_cmd_input.setStyleSheet("""
            QLineEdit {
                background-color: #1A1A1E;
                color: #F8FAFC;
                border: 1px solid #282830;
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #A855F7;
            }
        """)
        self.mini_cmd_input.returnPressed.connect(self.send_mini_command)
        mc_cmd_layout.addWidget(self.mini_cmd_input, 1)

        self.btn_mini_send = QPushButton("Gönder")
        self.btn_mini_send.setCursor(Qt.PointingHandCursor)
        self.btn_mini_send.setStyleSheet("""
            QPushButton {
                background-color: rgba(28, 28, 40, 0.9);
                color: #F8FAFC;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(139, 92, 246, 0.25);
                border: 1px solid #A855F7;
            }
        """)
        self.btn_mini_send.clicked.connect(lambda checked=False: self.send_mini_command())
        mc_cmd_layout.addWidget(self.btn_mini_send)
        mc_layout.addLayout(mc_cmd_layout)

        center_layout.addWidget(mini_console_frame, 1)
        
        kontrol_container = QFrame()
        kontrol_container.setObjectName("ServerControlPanel")
        kontrol_container.setFixedWidth(360)
        kontrol_container.setStyleSheet("""
            QFrame#ServerControlPanel {
                background-color: #1A1A1E;
                border: 1px solid #282830;
                border-radius: 8px;
            }
        """)
        layout_kontrol = QVBoxLayout(kontrol_container)
        layout_kontrol.setContentsMargins(16, 16, 16, 16)
        
        # RAM Ayarı
        ram_layout = QHBoxLayout()
        self.lbl_ram_gb = QLabel("Bellek (RAM) GB:")
        ram_layout.addWidget(self.lbl_ram_gb)
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
        self.progress_ram.setStyleSheet("QProgressBar { border: 1px solid #282830; border-radius: 3px; background: #141416; } QProgressBar::chunk { background-color: #2E8B57; border-radius: 3px; }")
        resource_layout.addWidget(self.progress_ram)
        
        self.lbl_cpu_usage = QLabel("CPU: 0%")
        self.lbl_cpu_usage.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        resource_layout.addWidget(self.lbl_cpu_usage)
        self.progress_cpu = QProgressBar()
        self.progress_cpu.setRange(0, 100)
        self.progress_cpu.setValue(0)
        self.progress_cpu.setTextVisible(False)
        self.progress_cpu.setFixedHeight(14)
        self.progress_cpu.setStyleSheet("QProgressBar { border: 1px solid #282830; border-radius: 3px; background: #141416; } QProgressBar::chunk { background-color: #DAA520; border-radius: 3px; }")
        resource_layout.addWidget(self.progress_cpu)
        
        self._resource_widget.setVisible(False)
        layout_kontrol.addWidget(self._resource_widget)
        
        # Resource monitor timer (2s interval)
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(2000)
        self._resource_timer.timeout.connect(self._update_resource_usage)
        
        # Butonlar
        self.btn_start = QPushButton("Sunucuyu Başlat")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #3C8527;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 13px;
                padding: 12px 14px;
                border: 1px solid #1E3F13;
                border-top: 1.5px solid #5EB836;
                border-bottom: 3.5px solid #1E3F13;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #46992E;
                border-top: 1.5px solid #6AC742;
            }
            QPushButton:pressed {
                background-color: #316E20;
                border-top: 3.5px solid #1E3F13;
                border-bottom: 1px solid #1E3F13;
                padding-top: 14px;
                padding-bottom: 10px;
            }
            QPushButton:disabled {
                background-color: #2A2A30;
                color: #666670;
                border: 1px solid #1F1F24;
                border-top: 1.5px solid #35353D;
                border-bottom: 3.5px solid #18181C;
            }
        """)
        self.btn_start.clicked.connect(self.start_server)
        layout_kontrol.addWidget(self.btn_start)
        
        self.btn_stop = QPushButton("Sunucuyu Durdur")
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #C0392B;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 13px;
                padding: 12px 14px;
                border: 1px solid #78281F;
                border-top: 1.5px solid #E74C3C;
                border-bottom: 3.5px solid #78281F;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #D32F2F;
                border-top: 1.5px solid #EF5350;
            }
            QPushButton:pressed {
                background-color: #962D22;
                border-top: 3.5px solid #78281F;
                border-bottom: 1px solid #78281F;
                padding-top: 14px;
                padding-bottom: 10px;
            }
            QPushButton:disabled {
                background-color: #2A2A30;
                color: #666670;
                border: 1px solid #1F1F24;
                border-top: 1.5px solid #35353D;
                border-bottom: 3.5px solid #18181C;
            }
        """)
        self.btn_stop.clicked.connect(self.stop_server)
        self.btn_stop.setEnabled(False)
        layout_kontrol.addWidget(self.btn_stop)
        
        self.btn_new_server = QPushButton("Yeni Sunucu Oluştur")
        self.btn_new_server.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 12px;
                padding: 10px 14px;
                border: 1px solid #1D4ED8;
                border-top: 1.5px solid #3B82F6;
                border-bottom: 3.5px solid #1D4ED8;
                border-radius: 4px;
                margin-top: 14px;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
                border-top: 1.5px solid #60A5FA;
            }
            QPushButton:pressed {
                background-color: #1E40AF;
                border-top: 3.5px solid #172554;
                border-bottom: 1px solid #172554;
                padding-top: 12px;
                padding-bottom: 8px;
            }
        """)
        self.btn_new_server.clicked.connect(self.create_new_server)
        layout_kontrol.addWidget(self.btn_new_server)
        
        self.btn_change_software = QPushButton("Yazılım/Sürüm Değiştir")
        self.btn_change_software.setStyleSheet("""
            QPushButton {
                background-color: #D97706;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 12px;
                padding: 10px 14px;
                border: 1px solid #92400E;
                border-top: 1.5px solid #F59E0B;
                border-bottom: 3.5px solid #92400E;
                border-radius: 4px;
                margin-top: 6px;
            }
            QPushButton:hover {
                background-color: #B45309;
                border-top: 1.5px solid #FBBF24;
            }
            QPushButton:pressed {
                background-color: #78350F;
                border-top: 3.5px solid #451A03;
                border-bottom: 1px solid #451A03;
                padding-top: 12px;
                padding-bottom: 8px;
            }
        """)
        self.btn_change_software.clicked.connect(self.open_software_dialog)
        layout_kontrol.addWidget(self.btn_change_software)
        
        self.btn_open_folder = QPushButton("Sunucu Dosyalarını Aç (Mod/Plugin Yükle)")
        self.btn_open_folder.setStyleSheet("""
            QPushButton {
                background-color: #2A2A30;
                color: #E4E4E7;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
                padding: 10px 14px;
                border: 1px solid #18181C;
                border-top: 1.5px solid #3E3E48;
                border-bottom: 3.5px solid #18181C;
                border-radius: 4px;
                margin-top: 6px;
            }
            QPushButton:hover {
                background-color: #35353D;
                border-top: 1.5px solid #4C4C58;
            }
            QPushButton:pressed {
                background-color: #1F1F24;
                border-top: 3.5px solid #141416;
                border-bottom: 1px solid #141416;
                padding-top: 12px;
                padding-bottom: 8px;
            }
        """)
        self.btn_open_folder.clicked.connect(self.open_server_folder)
        layout_kontrol.addWidget(self.btn_open_folder)
        
        self.btn_import_profile = QPushButton("İstemci Profilini Sunucuya Aktar")
        self.btn_import_profile.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
                padding: 10px 14px;
                border: 1px solid #4C1D95;
                border-top: 1.5px solid #A78BFA;
                border-bottom: 3.5px solid #4C1D95;
                border-radius: 4px;
                margin-top: 6px;
            }
            QPushButton:hover {
                background-color: #6D28D9;
                border-top: 1.5px solid #C4B5FD;
            }
            QPushButton:pressed {
                background-color: #5B21B6;
                border-top: 3.5px solid #2E1065;
                border-bottom: 1px solid #2E1065;
                padding-top: 12px;
                padding-bottom: 8px;
            }
        """)
        self.btn_import_profile.clicked.connect(self.import_client_profile)
        layout_kontrol.addWidget(self.btn_import_profile)
        
        self.btn_delete_server = QPushButton("Sunucuyu Tamamen Sil")
        self.btn_delete_server.setStyleSheet("""
            QPushButton {
                background-color: #991B1B;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
                padding: 10px 14px;
                border: 1px solid #7F1D1D;
                border-top: 1.5px solid #DC2626;
                border-bottom: 3.5px solid #7F1D1D;
                border-radius: 4px;
                margin-top: 6px;
            }
            QPushButton:hover {
                background-color: #7F1D1D;
                border-top: 1.5px solid #EF4444;
            }
            QPushButton:pressed {
                background-color: #450A0A;
                border-top: 3.5px solid #350808;
                border-bottom: 1px solid #350808;
                padding-top: 12px;
                padding-bottom: 8px;
            }
        """)
        self.btn_delete_server.clicked.connect(lambda checked=False: self.delete_server())
        layout_kontrol.addWidget(self.btn_delete_server)
        
        layout_kontrol.addStretch()
        page_kontrol_layout.addWidget(center_dashboard, 1)
        page_kontrol_layout.addWidget(kontrol_container, 0)
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

        self._log_history = []
        self.chk_info.toggled.connect(lambda val: self._on_filter_toggled("info", val))
        self.chk_warn.toggled.connect(lambda val: self._on_filter_toggled("warn", val))
        self.chk_error.toggled.connect(lambda val: self._on_filter_toggled("error", val))
        self.mini_chk_info.toggled.connect(lambda val: self._on_filter_toggled("info", val))
        self.mini_chk_warn.toggled.connect(lambda val: self._on_filter_toggled("warn", val))
        self.mini_chk_error.toggled.connect(lambda val: self._on_filter_toggled("error", val))
        
        self.console_output = QPlainTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setMaximumBlockCount(5000)
        self.console_output.setStyleSheet("background-color: #0C0C0E; color: #D4D4D4; font-family: Consolas, monospace; border: 1px solid #282830; border-radius: 4px; padding: 8px;")
        layout_konsol.addWidget(self.console_output)
        
        cmd_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Sunucuya komut gönder... (örn: op isminiz)")
        self.cmd_input.setStyleSheet("background-color: #1A1A1E; color: #E4E4E7; border: 1px solid #282830; border-radius: 4px; padding: 6px 10px; font-family: Consolas, monospace;")
        self.cmd_input.returnPressed.connect(self.send_command)
        cmd_layout.addWidget(self.cmd_input)
        
        self.btn_send = QPushButton("Gönder")
        self.btn_send.setStyleSheet("""
            QPushButton {
                background-color: #2A2A30;
                color: #FFFFFF;
                font-family: 'Minecraft Five', 'Segoe UI', sans-serif;
                font-weight: bold;
                padding: 6px 16px;
                border: 1px solid #18181C;
                border-top: 1.5px solid #3E3E48;
                border-bottom: 3px solid #18181C;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #35353D;
                border-top: 1.5px solid #4C4C58;
            }
            QPushButton:pressed {
                background-color: #1F1F24;
                border-top: 3px solid #141416;
                border-bottom: 1px solid #141416;
                padding-top: 8px;
                padding-bottom: 4px;
            }
        """)
        self.btn_send.clicked.connect(lambda checked=False: self.send_command())
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
        self.lbl_prop_max_players = QLabel("Maksimum Oyuncu:")
        form_ayarlar.addRow(self.lbl_prop_max_players, self.spin_max_players)
        
        self.spin_view_distance = QSpinBox()
        self.spin_view_distance.setRange(2, 32)
        self.spin_view_distance.setValue(10)
        self.lbl_prop_view_dist = QLabel("Görüş Mesafesi:")
        form_ayarlar.addRow(self.lbl_prop_view_dist, self.spin_view_distance)
        
        self.combo_difficulty = QComboBox()
        self.combo_difficulty.addItems(["peaceful", "easy", "normal", "hard"])
        self.combo_difficulty.setCurrentText("easy")
        self.lbl_prop_difficulty = QLabel("Zorluk:")
        form_ayarlar.addRow(self.lbl_prop_difficulty, self.combo_difficulty)


        self.line_seed = QLineEdit()
        self.line_seed.setPlaceholderText("Rastgele (Boş bırakın)")
        self.lbl_prop_seed = QLabel("Dünya Seed'i:")
        form_ayarlar.addRow(self.lbl_prop_seed, self.line_seed)

        self.line_level_name = QLineEdit()
        self.line_level_name.setText("world")
        self.line_level_name.setPlaceholderText("world")
        self.lbl_prop_level_name = QLabel("Dünya (Klasör) Adı:")
        form_ayarlar.addRow(self.lbl_prop_level_name, self.line_level_name)

        self.combo_gamemode = QComboBox()
        self.combo_gamemode.addItems(["survival", "creative", "adventure", "spectator"])
        self.combo_gamemode.setCurrentText("survival")
        self.lbl_prop_gamemode = QLabel("Oyun Modu:")
        form_ayarlar.addRow(self.lbl_prop_gamemode, self.combo_gamemode)

        self.line_motd = QLineEdit()
        self.line_motd.setText("A Minecraft Server")
        self.line_motd.setPlaceholderText("Sunucu açıklaması...")
        self.lbl_prop_motd = QLabel("MOTD (Açıklama):")
        form_ayarlar.addRow(self.lbl_prop_motd, self.line_motd)

        self.spin_spawn_protection = QSpinBox()
        self.spin_spawn_protection.setRange(0, 256)
        self.spin_spawn_protection.setValue(16)
        self.lbl_prop_spawn_prot = QLabel("Spawn Koruma Yarıçapı:")
        form_ayarlar.addRow(self.lbl_prop_spawn_prot, self.spin_spawn_protection)

        self.spin_sim_distance = QSpinBox()
        self.spin_sim_distance.setRange(2, 32)
        self.spin_sim_distance.setValue(10)
        self.lbl_prop_sim_dist = QLabel("Simülasyon Mesafesi:")
        form_ayarlar.addRow(self.lbl_prop_sim_dist, self.spin_sim_distance)
        
        self.chk_crack = QCheckBox("Aktif (online-mode=false)")
        self.lbl_prop_crack = QLabel("Crackli Giriş:")
        form_ayarlar.addRow(self.lbl_prop_crack, self.chk_crack)
        
        self.chk_pvp = QCheckBox("Aktif")
        self.chk_pvp.setChecked(True)
        self.lbl_prop_pvp = QLabel("PVP:")
        form_ayarlar.addRow(self.lbl_prop_pvp, self.chk_pvp)
        
        layout_ayarlar.addLayout(form_ayarlar)
        
        self.btn_save_settings = QPushButton("Ayarları Kaydet")
        self.btn_save_settings.clicked.connect(self.save_server_properties)
        layout_ayarlar.addWidget(self.btn_save_settings)
        layout_ayarlar.addStretch()
        
        self.stacked_widget.addWidget(page_ayarlar)
        
        # 4. Sayfa: Oyuncular
        page_oyuncular = QWidget()
        layout_oyuncular = QVBoxLayout(page_oyuncular)
        
        self.lbl_online_count = QLabel("Online: 0")
        self.lbl_online_count.setStyleSheet("font-size: 18px; font-weight: bold; color: #C084FC; margin-bottom: 10px;")
        layout_oyuncular.addWidget(self.lbl_online_count)
        
        self.player_list = QListWidget()
        layout_oyuncular.addWidget(self.player_list)
        
        player_buttons_layout = QHBoxLayout()
        self.btn_op = QPushButton("OP Ver/Al")
        self.btn_op.setStyleSheet("background-color: #DAA520; color: white; padding: 8px; font-weight: bold; border-radius: 5px;")
        self.btn_op.clicked.connect(lambda checked=False: self.toggle_op_player())
        self.btn_msg = QPushButton("Mesaj Gönder")
        self.btn_msg.setStyleSheet("background-color: #4682B4; color: white; padding: 8px; font-weight: bold; border-radius: 5px;")
        self.btn_msg.clicked.connect(lambda checked=False: self.send_message_to_player())
        self.btn_kick = QPushButton("Oyundan At")
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
        
        self.lbl_yedek_title = QLabel("Sunucu Yedekleri")
        self.lbl_yedek_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #F8FAFC;")
        layout_yedekler.addWidget(self.lbl_yedek_title)
        
        self.lbl_yedek_info = QLabel("Sunucu klasörünüzdeki world, plugins, mods, config ve ayar dosyalarını yedekler.")
        self.lbl_yedek_info.setStyleSheet("color: #AAAAAA;")
        layout_yedekler.addWidget(self.lbl_yedek_info)
        
        self.backup_list = QListWidget()
        layout_yedekler.addWidget(self.backup_list)
        
        self.chk_delete_local = QCheckBox("Yedek Drive'a yüklendikten sonra bilgisayarımdaki kopyayı sil")
        self.chk_delete_local.setChecked(False)
        layout_yedekler.addWidget(self.chk_delete_local)
        
        yedek_btn_layout = QHBoxLayout()
        self.btn_take_backup = QPushButton("Yeni Yedek Al")
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
        
        self.lbl_mod_title = QLabel("Modrinth'den Mod/Eklenti İndir")
        self.lbl_mod_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #F8FAFC;")
        layout_modlar.addWidget(self.lbl_mod_title)
        
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
        
        # Canlı dosya sistemi izleyicisi (sekme değiştirmeden anlık güncelleme)
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.directoryChanged.connect(self._on_fs_changed)
        self._fs_watcher.fileChanged.connect(self._on_fs_changed)

        self.server_dir = ""

        # Sekme değişimi bağlaması
        def _on_tab_change(idx):
            if getattr(self, "_shortcut_teleport_nav", False):
                self._shortcut_teleport_nav = False
            else:
                try:
                    from sound_manager import SoundManager
                    SoundManager.get_instance().play_book_flip()
                except Exception:
                    pass
            self.stacked_widget.setCurrentIndex(idx)
            self.update_dashboard_cards()

        self.side_tabs.setCurrentRow(0)
        self.side_tabs.currentRowChanged.connect(_on_tab_change)
        
        self.refresh_server_list()
        
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.cleanup)

    def is_running(self) -> bool:
        th = getattr(self, "server_thread", None)
        if not th:
            return False
        proc = getattr(th, "process", None)
        return bool(
            th.isRunning()
            or getattr(th, "is_running", False)
            or (proc and hasattr(proc, "poll") and proc.poll() is None)
        )

    def set_theme(self, theme_key: str):
        self._active_theme = theme_key
        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            glow = t["glow"]
            if hasattr(self, "side_tabs"):
                self.side_tabs.style().unpolish(self.side_tabs)
                self.side_tabs.style().polish(self.side_tabs)
                self.side_tabs.update()
            if hasattr(self, "summary_cards"):
                for card in self.summary_cards:
                    card.style().unpolish(card)
                    card.style().polish(card)
                    card.update()
            if hasattr(self, "summary_card_subs"):
                for lbl in self.summary_card_subs:
                    lbl.setStyleSheet(f"font-size: 11px; color: {glow}; background: transparent; border: none;")
        except Exception:
            pass

    def set_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        if self.server_thread:
            self.server_thread.lang = lang
        self.lbl_srv_title.setText("Server Profiles" if en else "Sunucu Profilleri")
        self.lbl_srv_info.setText(
            "Create different servers and switch between them anytime."
            if en else
            "Farklı sunucular oluşturun ve istediğiniz zaman aralarında geçiş yapın."
        )
        self.lbl_srv_sel.setText("Select Server:" if en else "Sunucu Seç:")
        tab_texts = (
            ["Dashboard", "Console", "Settings", "Players", "Backups", "Mods/Plugins"]
            if en else
            ["Kontrol Paneli", "Konsol", "Ayarlar", "Oyuncular", "Yedekler", "Modlar/Eklentiler"]
        )
        for i, txt in enumerate(tab_texts):
            if i < self.side_tabs.count():
                self.side_tabs.item(i).setText(txt)

        self.lbl_card_sw_hdr.setText("SOFTWARE & WORLD" if en else "YAZILIM & DÜNYA")
        self.lbl_card_addr_hdr.setText("SERVER ADDRESS" if en else "BAĞLANTI ADRESİ")
        self.lbl_card_address_sub.setText("Copy" if en else "Kopyala")
        self.lbl_card_pl_hdr.setText("PLAYERS" if en else "OYUNCULAR")
        self.lbl_card_players_sub.setText("Go to Players ➔" if en else "Oyunculara git ➔")
        self.lbl_card_cnt_hdr.setText("MODS & BACKUPS" if en else "MOD & YEDEK")
        self.lbl_card_content_sub.setText("Mods & Backups ➔" if en else "Modlar & Yedekler ➔")

        self.lbl_mc_title.setText("Console" if en else "Konsol")
        self.btn_goto_console.setText("Full Console ➔" if en else "Tam Konsol ➔")
        self.mini_console.setPlaceholderText("Live server logs will stream here..." if en else "Sunucu logları burada canlı olarak akacaktır...")
        self.mini_cmd_input.setPlaceholderText("Send command to server... (e.g. op yourname)" if en else "Sunucuya komut gönder... (örn: op isminiz)")
        self.btn_mini_send.setText("Send" if en else "Gönder")

        self.lbl_ram_gb.setText("Memory (RAM) GB:" if en else "Bellek (RAM) GB:")
        is_running = bool(self.server_thread and getattr(self.server_thread, "is_running", False))
        cur_status = self.lbl_server_status.text()
        if "Başlatılıyor" in cur_status or "Starting" in cur_status:
            self.lbl_server_status.setText("🟡 Status: Starting..." if en else "🟡 Durum: Başlatılıyor...")
        elif is_running:
            self.lbl_server_status.setText("🟢 Status: Online" if en else "🟢 Durum: Açık")
        else:
            self.lbl_server_status.setText("🔴 Status: Offline" if en else "🔴 Durum: Kapalı")

        self.btn_start.setText("Start Server" if en else "Sunucuyu Başlat")
        if self.btn_stop.text() in ("Kapatmaya Zorla", "Force Stop"):
            self.btn_stop.setText("Force Stop" if en else "Kapatmaya Zorla")
        else:
            self.btn_stop.setText("Stop Server" if en else "Sunucuyu Durdur")
        self.btn_new_server.setText("Create New Server" if en else "Yeni Sunucu Oluştur")
        self.btn_change_software.setText("Change Software/Version" if en else "Yazılım/Sürüm Değiştir")
        self.btn_open_folder.setText("Open Server Folder (Mods/Plugins)" if en else "Sunucu Dosyalarını Aç (Mod/Plugin Yükle)")
        self.btn_import_profile.setText("Export Client Profile to Server" if en else "İstemci Profilini Sunucuya Aktar")
        self.btn_delete_server.setText("Delete Server Permanently" if en else "Sunucuyu Tamamen Sil")

        self.cmd_input.setPlaceholderText("Send command to server... (e.g. op yourname)" if en else "Sunucuya komut gönder... (örn: op isminiz)")
        self.btn_send.setText("Send" if en else "Gönder")

        if hasattr(self, "lbl_prop_max_players"):
            self.lbl_prop_max_players.setText("Max Players:" if en else "Maksimum Oyuncu:")
            self.lbl_prop_view_dist.setText("View Distance:" if en else "Görüş Mesafesi:")
            self.lbl_prop_difficulty.setText("Difficulty:" if en else "Zorluk:")
            self.lbl_prop_seed.setText("World Seed:" if en else "Dünya Seed'i:")
            self.line_seed.setPlaceholderText("Random (Leave empty)" if en else "Rastgele (Boş bırakın)")
            self.lbl_prop_level_name.setText("World (Folder) Name:" if en else "Dünya (Klasör) Adı:")
            self.lbl_prop_gamemode.setText("Gamemode:" if en else "Oyun Modu:")
            self.lbl_prop_motd.setText("MOTD (Description):" if en else "MOTD (Açıklama):")
            self.line_motd.setPlaceholderText("Server description..." if en else "Sunucu açıklaması...")
            self.lbl_prop_spawn_prot.setText("Spawn Protection Radius:" if en else "Spawn Koruma Yarıçapı:")
            self.lbl_prop_sim_dist.setText("Simulation Distance:" if en else "Simülasyon Mesafesi:")
            self.lbl_prop_crack.setText("Cracked Login:" if en else "Crackli Giriş:")
            self.chk_crack.setText("Enabled (online-mode=false)" if en else "Aktif (online-mode=false)")
            self.lbl_prop_pvp.setText("PVP:")
            self.chk_pvp.setText("Enabled" if en else "Aktif")
        self.btn_save_settings.setText("Save Settings" if en else "Ayarları Kaydet")

        self.btn_op.setText("Toggle OP" if en else "OP Ver/Al")
        self.btn_msg.setText("Send Message" if en else "Mesaj Gönder")
        self.btn_kick.setText("Kick Player" if en else "Oyundan At")
        self.btn_ban.setText("Ban Player" if en else "Uzaklaştır (Ban)")

        self.lbl_yedek_title.setText("Server Backups" if en else "Sunucu Yedekleri")
        self.lbl_yedek_info.setText(
            "Backs up world, plugins, mods, config and properties in your server folder."
            if en else
            "Sunucu klasörünüzdeki world, plugins, mods, config ve ayar dosyalarını yedekler."
        )
        self.chk_delete_local.setText(
            "Delete local copy after uploading backup to Google Drive"
            if en else
            "Yedek Drive'a yüklendikten sonra bilgisayarımdaki kopyayı sil"
        )
        self.btn_take_backup.setText("Take New Backup" if en else "Yeni Yedek Al")
        self.btn_restore_backup.setText("Restore Backup" if en else "Geri Yükle")

        self.lbl_mod_title.setText("Download Mod/Plugin from Modrinth" if en else "Modrinth'den Mod/Eklenti İndir")
        self.mod_search_input.setPlaceholderText("Search Mod or Plugin..." if en else "Mod veya Eklenti ara...")
        self.btn_search_mod.setText("Search" if en else "Ara")
        self.btn_download_mod.setText("Download & Install" if en else "İndir ve Kur")
        self.refresh_player_list()
        self.update_dashboard_cards()
            
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
        if hasattr(self, '_stop_watchdog_timer') and self._stop_watchdog_timer.isActive():
            self._stop_watchdog_timer.stop()
        if self.server_thread and (self.server_thread.isRunning() or getattr(self.server_thread, 'is_running', False)):
            try:
                # Non-blocking / fast 1.0s grace period during app shutdown to prevent UI thread freeze
                self.server_thread.terminate_process(timeout=1.0)
            except Exception:
                self.force_kill_server()
        else:
            self.force_kill_server()
        if hasattr(self, '_fs_watcher'):
            paths = self._fs_watcher.directories() + self._fs_watcher.files()
            if paths:
                self._fs_watcher.removePaths(paths)
        if hasattr(self, '_resource_timer') and self._resource_timer.isActive():
            self._resource_timer.stop()
        if hasattr(self, '_api_threads'):
            for th in list(self._api_threads):
                try:
                    if th.isRunning():
                        if hasattr(th, 'cancel'):
                            th.cancel()
                        th.quit()
                        th.wait(1000)
                except Exception:
                    pass
            self._api_threads.clear()

    def force_kill_server(self):
        if not hasattr(self, "process_coordinator"):
            self.process_coordinator = ServerProcessCoordinator(parser=getattr(self, "console_parser", None))
        if self.server_thread and self.process_coordinator._thread is not self.server_thread:
            self.process_coordinator.attach_thread(self.server_thread)
        self.process_coordinator.force_kill()
        if self.server_thread and self.server_thread.isRunning():
            self.server_thread.wait(2000)

                
    def delete_server(self):
        en = getattr(self, "lang", "tr") == "en"
        if self.server_dir and os.path.exists(self.server_dir):
            if self.server_thread and self.server_thread.is_running:
                QMessageBox.warning(
                    self,
                    "Warning" if en else "Uyarı",
                    "Cannot delete server while it is running." if en else "Sunucu çalışırken silinemez."
                )
                return
            real_target = os.path.realpath(self.server_dir)
            real_base = os.path.realpath(self.servers_dir) + os.sep
            if not real_target.startswith(real_base):
                QMessageBox.warning(
                    self,
                    "Security Warning" if en else "Güvenlik Uyarısı",
                    "Server folder could not be deleted because it is outside the allowed directory."
                    if en else
                    "Sunucu klasörü izin verilen dizin dışında olduğu için silinemedi."
                )
                return
            reply = QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "This action cannot be undone. The server, world, and all backups will be permanently deleted. Do you want to continue?"
                if en else
                "Bu işlem geri alınamaz. Sunucu, dünya ve tüm yedekler tamamen silinecek. Devam etmek istiyor musunuz?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                import shutil
                try:
                    shutil.rmtree(real_target)
                    try:
                        from sound_manager import SoundManager
                        SoundManager.get_instance().play_break()
                    except Exception:
                        pass
                    self.refresh_server_list()
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "Error" if en else "Hata",
                        (
                            f"Deletion failed. One of the files may be in use by another program.\n\nDetails: {str(e)}"
                            if en else
                            f"Silme işlemi başarısız oldu. Dosyalardan biri başka bir program tarafından kullanılıyor olabilir.\n\nDetay: {str(e)}"
                        )
                    )
        
    def _get_config_path(self):
        for target in (self.window(), self.parent()):
            if target and hasattr(target, "config_file") and getattr(target, "config_file"):
                return target.config_file
        appdata_cfg = os.path.join(os.environ.get("APPDATA", ""), ".vega_launcher", "launcher_config.json")
        if os.path.exists(appdata_cfg):
            return appdata_cfg
        return os.path.join(get_base_dir(), "launcher_config.json")

    def _get_profile_store(self) -> ProfileAndConfigStore:
        return ProfileAndConfigStore(
            config_file=self._get_config_path(),
            profiles_dir=getattr(self, "profiles_dir", None),
        )

    def _get_server_instance(self) -> ServerInstance:
        return ServerInstance(getattr(self, "server_dir", ""))

    def _load_last_server(self):
        for target in (self.window(), self.parent()):
            if target and hasattr(target, "settings") and isinstance(target.settings, dict):
                val = target.settings.get("last_server", "")
                if val:
                    return val
        return self._get_profile_store().get_setting("last_server", "") or ""

    def _save_last_server(self, server_name):
        for target in (self.window(), self.parent()):
            if target and hasattr(target, "settings") and isinstance(target.settings, dict):
                target.settings["last_server"] = server_name or ""
                if hasattr(target, "save_config"):
                    try:
                        target.save_config()
                        return
                    except Exception:
                        pass
        self._get_profile_store().update_setting("last_server", server_name or "")

    def refresh_server_list(self, preferred_name=None):
        last_selected = preferred_name or self._load_last_server()
        self.server_selector.blockSignals(True)
        self.server_selector.clear()
        if os.path.exists(self.servers_dir):
            for folder in os.listdir(self.servers_dir):
                if os.path.isdir(os.path.join(self.servers_dir, folder)):
                    self.server_selector.addItem(folder)
        self.server_selector.blockSignals(False)
        if self.server_selector.count() > 0:
            target_idx = -1
            if last_selected:
                target_idx = self.server_selector.findText(last_selected)
            if target_idx >= 0:
                self.server_selector.setCurrentIndex(target_idx)
                self.on_server_selected(self.server_selector.itemText(target_idx))
            else:
                self.server_selector.setCurrentIndex(0)
                self.on_server_selected(self.server_selector.currentText())
        else:
            self.server_dir = ""
            self.btn_start.setEnabled(False)
            self.btn_delete_server.setEnabled(False)
            self._sync_fs_watcher()
            self.load_server_properties()
            self.refresh_backup_list()
            self.refresh_player_list()
            self.update_dashboard_cards()
            self._save_last_server("")
            
    def on_server_selected(self, text):
        en = getattr(self, "lang", "tr") == "en"
        if text:
            self.server_dir = os.path.join(self.servers_dir, text)
            self._detected_tunnel_addr = None
            self.btn_start.setEnabled(True)
            self.btn_delete_server.setEnabled(True)
            self._sync_fs_watcher()
            self.log(f"[INFO] Active server profile: {text}" if en else f"[BİLGİ] Aktif sunucu profili: {text}")
            self.load_server_properties()
            self.refresh_backup_list()
            self.refresh_player_list()
            self.update_dashboard_cards()
            self._save_last_server(text)
        else:
            self._save_last_server("")

    def _sync_fs_watcher(self):
        if not hasattr(self, '_fs_watcher'):
            return
        old_paths = self._fs_watcher.directories() + self._fs_watcher.files()
        if old_paths:
            self._fs_watcher.removePaths(old_paths)
        if not self.server_dir or not os.path.exists(self.server_dir):
            return
        candidates = [
            self.server_dir,
            os.path.join(self.server_dir, "mods"),
            os.path.join(self.server_dir, "plugins"),
            os.path.join(self.server_dir, "backups"),
            os.path.join(self.server_dir, "libraries"),
            os.path.join(self.server_dir, "server.properties"),
        ]
        valid_paths = [p for p in candidates if os.path.exists(p)]
        if valid_paths:
            self._fs_watcher.addPaths(valid_paths)

    def _on_fs_changed(self, path=""):
        self._sync_fs_watcher()
        self.refresh_backup_list()
        self.update_dashboard_cards()
        QTimer.singleShot(250, self.update_dashboard_cards)

    def copy_server_address(self):
        if not hasattr(self, 'lbl_card_address'):
            return
        en = getattr(self, "lang", "tr") == "en"
        addr = self.lbl_card_address.text().strip()
        if addr:
            QApplication.clipboard().setText(addr)
            self.lbl_card_address_sub.setText("Copied!" if en else "Kopyalandı!")
            QTimer.singleShot(
                2000,
                lambda: self.lbl_card_address_sub.setText("Copy" if getattr(self, "lang", "tr") == "en" else "Kopyala")
                if hasattr(self, 'lbl_card_address_sub') else None
            )

    def update_dashboard_cards(self):
        if not hasattr(self, 'lbl_card_software'):
            return
        en = getattr(self, "lang", "tr") == "en"
        if not self.server_dir or not os.path.exists(self.server_dir):
            self.lbl_card_software.setText("No Server Selected" if en else "Sunucu Seçilmedi")
            self.lbl_card_software_sub.setText("Create a new server" if en else "Yeni sunucu oluşturun")
            self.lbl_card_address.setText("localhost:25565")
            self.lbl_card_players.setText("0 / 20 Online" if en else "0 / 20 Çevrimiçi")
            self.lbl_card_content.setText("0 Mods • 0 Backups" if en else "0 Mod • 0 Yedek")
            return

        inst = self._get_server_instance()

        # 1. Software & World
        sw_name = "Not Installed" if en else "Kurulmadı"
        if os.path.exists(os.path.join(self.server_dir, "libraries", "net", "neoforged")):
            sw_name = "NeoForge"
        elif os.path.exists(os.path.join(self.server_dir, "libraries", "net", "minecraftforge")):
            sw_name = "Forge"
        elif os.path.exists(os.path.join(self.server_dir, "fabric-server-launch.jar")) or os.path.exists(os.path.join(self.server_dir, ".fabric")):
            sw_name = "Fabric"
        elif inst.has_launch_artifact():
            sw_name = "Installed (Jar/Engine)" if en else "Kurulu (Jar/Motor)"
        world_name = self.line_level_name.text().strip() or "world"
        diff_name = self.combo_difficulty.currentText()
        self.lbl_card_software.setText(sw_name)
        self.lbl_card_software_sub.setText(f"{world_name} • {diff_name} ➔")

        # 2. Address / Port
        port = inst.read_properties().server_port
        tunnel = getattr(self, '_detected_tunnel_addr', None)
        self.lbl_card_address.setText(tunnel if tunnel else f"localhost:{port}")

        # 3. Players
        online_cnt = len(getattr(self, 'online_players', set()))
        max_cnt = self.spin_max_players.value()
        self.lbl_card_players.setText(f"{online_cnt} / {max_cnt} {'Online' if en else 'Çevrimiçi'}")

        # 4. Mods & Backups
        mod_cnt, bkp_cnt = inst.count_content_and_backups()
        self.lbl_card_content.setText(
            f"{mod_cnt} {'Mods' if en else 'Mod'} • {bkp_cnt} {'Backups' if en else 'Yedek'}"
        )

    def _classify_log(self, text):
        parser = getattr(self, "console_parser", None) or ServerConsoleParser
        return parser.classify_log_level(text)

    def _passes_log_filter(self, text):
        lvl = self._classify_log(text)
        if lvl == "INFO" and not self.chk_info.isChecked():
            return False
        if lvl == "WARN" and not self.chk_warn.isChecked():
            return False
        if lvl == "ERROR" and not self.chk_error.isChecked():
            return False
        return True

    def _format_log_html(self, text):
        parser = getattr(self, "console_parser", None) or ServerConsoleParser
        return parser.format_html(text)

    def _on_filter_toggled(self, kind, val):
        pairs = {
            "info": (self.chk_info, getattr(self, 'mini_chk_info', None)),
            "warn": (self.chk_warn, getattr(self, 'mini_chk_warn', None)),
            "error": (self.chk_error, getattr(self, 'mini_chk_error', None)),
        }
        for chk in pairs.get(kind, ()):
            if chk and chk.isChecked() != val:
                chk.blockSignals(True)
                chk.setChecked(val)
                chk.blockSignals(False)
        self._refilter_consoles()

    def _refilter_consoles(self):
        if not hasattr(self, 'console_output'):
            return
        self.console_output.clear()
        if hasattr(self, 'mini_console'):
            self.mini_console.clear()
        for entry in getattr(self, '_log_history', []):
            if self._passes_log_filter(entry):
                colored_html = self._format_log_html(entry)
                self.console_output.appendHtml(colored_html)
                if hasattr(self, 'mini_console'):
                    self.mini_console.appendHtml(colored_html)

    def log(self, text):
        if not hasattr(self, 'console_parser'):
            self.console_parser = ServerConsoleParser()
        if not hasattr(self, 'process_coordinator'):
            self.process_coordinator = ServerProcessCoordinator(parser=self.console_parser)
        events = self.process_coordinator.handle_stdout_line(text)
        self._log_history = self.console_parser.history

        for ev in events:
            if ev.event_type == "tunnel_detected":
                self._detected_tunnel_addr = ev.data
                self.update_dashboard_cards()
            elif ev.event_type == "online":
                if hasattr(self, 'lbl_server_status'):
                    en = getattr(self, "lang", "tr") == "en"
                    self.lbl_server_status.setText("🟢 Status: Online" if en else "🟢 Durum: Açık (Çevrimiçi)")
                    self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #2E8B57; margin-top: 10px; margin-bottom: 10px;")
            elif ev.event_type == "stopping":
                en = getattr(self, "lang", "tr") == "en"
                self._user_stopped = True
                if hasattr(self, 'lbl_server_status'):
                    self.lbl_server_status.setText("🟡 Status: Stopping..." if en else "🟡 Durum: Kapatılıyor...")
                    self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #DAA520; margin-top: 10px; margin-bottom: 10px;")
                if hasattr(self, 'btn_stop') and self.btn_stop.isEnabled():
                    self.btn_stop.setText("Force Stop" if en else "Kapatmaya Zorla")
                self._start_stop_watchdog(timeout_ms=10000)
            elif ev.event_type == "world_saved":
                self._start_stop_watchdog(timeout_ms=3000)

        if not hasattr(self, 'chk_info'):
            self.console_output.appendPlainText(text)
            if hasattr(self, 'mini_console'):
                self.mini_console.appendPlainText(text)
            return

        if not self._passes_log_filter(text):
            return

        colored_html = self.console_parser.format_html(text)
        self.console_output.appendHtml(colored_html)
        if hasattr(self, 'mini_console'):
            self.mini_console.appendHtml(colored_html)
        
    def start_server(self):
        en = getattr(self, "lang", "tr") == "en"
        self._user_stopped = False
        if not os.path.exists(self.server_dir):
            self.log(f"[ERROR] Server folder not found: {self.server_dir}" if en else f"[HATA] Sunucu klasörü bulunamadı: {self.server_dir}")
            return
            
        try:
            store = self._get_profile_store()
            server_name = os.path.basename(self.server_dir)
            matched_profile = store.find_client_profile_for_server(server_name)
            if matched_profile:
                client_path = matched_profile.get("path", "")
                diff = self._get_server_instance().sync_mods_from_client(client_path)
                if diff.added > 0 or diff.removed > 0:
                    self.log(
                        f"[INFO] Sync completed: {diff.added} added, {diff.removed} removed."
                        if en else
                        f"[BİLGİ] Senkronizasyon tamamlandı: {diff.added} eklendi, {diff.removed} kaldırıldı."
                    )
        except Exception as e:
            self.log(f"[ERROR] Profile sync read error: {e}" if en else f"[HATA] Profil senkronizasyon okuma hatası: {e}")

        self._do_start_server()

    def _do_start_server(self):
        en = getattr(self, "lang", "tr") == "en"
        inst = self._get_server_instance()
        if not inst.has_launch_artifact():
            self.log(
                "[ERROR] Launch file not found (server.jar or run.bat)."
                if en else
                "[HATA] Başlatma dosyası bulunamadı (server.jar veya run.bat)."
            )
            self.log(
                "[INFO] Please install the server engine first using 'Change Software'."
                if en else
                "[BİLGİ] Lütfen önce 'Yazılım Değiştir' ile sunucu motorunu kurun."
            )
            return

        # Zero-restart first launch: ensure eula.txt and server.properties exist before launching
        inst.ensure_boot_ready()
            
        self.log("[INFO] Starting server..." if en else "[BİLGİ] Sunucu başlatılıyor...")
        if hasattr(self, 'lbl_server_status'):
            self.lbl_server_status.setText("🟡 Status: Starting..." if en else "🟡 Durum: Başlatılıyor...")
            self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #DAA520; margin-top: 10px; margin-bottom: 10px;")
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText("Stop Server" if en else "Sunucuyu Durdur")
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
            
        configured_java = (self._get_profile_store().get_setting("java_path", "") or "").strip() or None
        if not hasattr(self, 'process_coordinator'):
            self.process_coordinator = ServerProcessCoordinator(parser=self.console_parser)
        self.server_thread = MinecraftServerThread(
            server_dir=self.server_dir,
            ram_gb=self.ram_spinbox.value(),
            jar_name="server.jar",
            java_path=configured_java,
            parent=None,
            lang=getattr(self, "lang", "tr"),
            coordinator=self.process_coordinator,
        )
        self._api_threads.append(self.server_thread)
        self.process_coordinator.attach_thread(self.server_thread)
        
        self.server_thread.log_ready.connect(self.log)
        self.server_thread.server_stopped.connect(self.on_server_stopped)
        self.server_thread.player_joined.connect(self.on_player_joined)
        self.server_thread.player_left.connect(self.on_player_left)
        
        self._resource_widget.setVisible(True)
        self._resource_timer.start()
        
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_beacon_activate()
        except Exception:
            pass
        self.server_thread.start()
        
    def stop_server(self):
        en = getattr(self, "lang", "tr") == "en"
        self._user_stopped = True
        if self.server_thread and self.server_thread.is_running:
            if not hasattr(self, "process_coordinator"):
                self.process_coordinator = ServerProcessCoordinator(parser=getattr(self, "console_parser", None))
            if self.process_coordinator._thread is not self.server_thread:
                self.process_coordinator.attach_thread(self.server_thread)
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_beacon_deactivate()
            except Exception:
                pass
            if self.btn_stop.text() in ("Kapatmaya Zorla", "Force Stop"):
                self.log("[INFO] Force stopping server..." if en else "[BİLGİ] Sunucu zorla kapatılıyor...")
                self.force_kill_server()
                self.btn_stop.setEnabled(False)
                return

            self.log("[INFO] Sending stop signal to server..." if en else "[BİLGİ] Sunucuya kapatma sinyali gönderiliyor...")
            if hasattr(self, 'lbl_server_status'):
                self.lbl_server_status.setText("🟡 Status: Stopping..." if en else "🟡 Durum: Kapatılıyor...")
                self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #DAA520; margin-top: 10px; margin-bottom: 10px;")
            self.btn_stop.setEnabled(False)
            self.btn_stop.setText("Stopping..." if en else "Kapatılıyor...")
            self.process_coordinator.stop(timeout_sec=10.0)
            self._start_stop_watchdog(timeout_ms=10000)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._arm_force_stop)

    def _arm_force_stop(self):
        if hasattr(self, 'server_thread') and self.server_thread and self.server_thread.is_running:
            en = getattr(self, "lang", "tr") == "en"
            if hasattr(self, 'btn_stop') and self.btn_stop:
                self.btn_stop.setText("Force Stop" if en else "Kapatmaya Zorla")
                self.btn_stop.setEnabled(True)

    def _start_stop_watchdog(self, timeout_ms=10000):
        if hasattr(self, '_stop_watchdog_timer') and self._stop_watchdog_timer.isActive():
            rem = self._stop_watchdog_timer.remainingTime()
            if rem > timeout_ms or rem < 0:
                self._stop_watchdog_timer.stop()
                self._stop_watchdog_timer.start(timeout_ms)
            return

        from PySide6.QtCore import QTimer
        self._stop_watchdog_timer = QTimer(self)
        self._stop_watchdog_timer.setSingleShot(True)
        self._stop_watchdog_timer.timeout.connect(self._on_stop_watchdog_timeout)
        self._stop_watchdog_timer.start(timeout_ms)

    def _on_stop_watchdog_timeout(self):
        if self.server_thread and self.server_thread.is_running:
            en = getattr(self, "lang", "tr") == "en"
            self.log(
                "[INFO] Server shutdown finalized. Terminating inactive background threads..."
                if en else
                "[BİLGİ] Sunucu kapanışı tamamlandı. Kalan arka plan süreçleri güvenle sonlandırılıyor..."
            )
            self.force_kill_server()

    def send_command(self):
        cmd = self.cmd_input.text().strip()
        if cmd and self.server_thread and self.server_thread.is_running:
            if not hasattr(self, "process_coordinator"):
                self.process_coordinator = ServerProcessCoordinator(parser=getattr(self, "console_parser", None))
            if self.process_coordinator._thread is not self.server_thread:
                self.process_coordinator.attach_thread(self.server_thread)
            self.process_coordinator.send_command(cmd)
            self.cmd_input.clear()

    def send_mini_command(self):
        if not hasattr(self, 'mini_cmd_input'):
            return
        cmd = self.mini_cmd_input.text().strip()
        if cmd and self.server_thread and self.server_thread.is_running:
            if not hasattr(self, "process_coordinator"):
                self.process_coordinator = ServerProcessCoordinator(parser=getattr(self, "console_parser", None))
            if self.process_coordinator._thread is not self.server_thread:
                self.process_coordinator.attach_thread(self.server_thread)
            self.process_coordinator.send_command(cmd)
            self.mini_cmd_input.clear()


    def on_server_stopped(self):
        if hasattr(self, '_stop_watchdog_timer') and self._stop_watchdog_timer.isActive():
            self._stop_watchdog_timer.stop()
        en = getattr(self, "lang", "tr") == "en"
        if not getattr(self, "_user_stopped", False):
            self.log(
                "\n[WARNING] Server crashed unexpectedly! Please check the logs.\n"
                if en else
                "\n[UYARI] Sunucu beklenmedik şekilde çöktü! Lütfen logları kontrol edin.\n"
            )
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_error()
            except Exception:
                pass
        self._user_stopped = False
        if hasattr(self, 'process_coordinator'):
            self.process_coordinator.on_process_exited()
        self.log("[INFO] Server stopped." if en else "[BİLGİ] Sunucu kapandı.")
        self.lbl_server_status.setText("🔴 Status: Offline" if en else "🔴 Durum: Kapalı")
        self.lbl_server_status.setStyleSheet("font-size: 16px; font-weight: bold; color: #CD5C5C; margin-top: 10px; margin-bottom: 10px;")
        
        self._resource_timer.stop()
        self._resource_widget.setVisible(False)
        
        # Reset online players and refresh list to show everyone as offline
        self.online_players = set()
        self.refresh_player_list()
        
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Stop Server" if en else "Sunucuyu Durdur")
        self.ram_spinbox.setEnabled(True)
        self.server_selector.setEnabled(True)
        self.btn_new_server.setEnabled(True)
        self.btn_change_software.setEnabled(True)
        self.btn_import_profile.setEnabled(True)
        self.btn_delete_server.setEnabled(True)

    def refresh_player_list(self):
        en = getattr(self, "lang", "tr") == "en"
        if not hasattr(self, 'online_players'):
            self.online_players = set()
            
        self.player_list.clear()
        inst = self._get_server_instance() if self.server_dir else None
        statuses = inst.get_player_statuses(getattr(self, "online_players", set())) if inst else []

        online_tag = "Online" if en else "Çevrimiçi"
        offline_tag = "Offline" if en else "Çevrimdışı"
        for st in statuses:
            tag = online_tag if st.online else offline_tag
            item = QListWidgetItem(f"[{tag}] {st.name}")
            item.setData(Qt.UserRole, st.name)
            item.setForeground(QColor("#2E8B57") if st.online else QColor("#AAAAAA"))
            self.player_list.addItem(item)
            
        # Update header
        if hasattr(self, 'lbl_online_count'):
            self.lbl_online_count.setText(f"Online: {len(self.online_players)}")
        self.update_dashboard_cards()
            
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
        
        player_name = selected.data(Qt.UserRole)
        if not player_name:
            import re
            match = re.search(r'(?:\[[^\]]+\]|[🟢⚪])\s+([^\s]+)', selected.text())
            if not match:
                return
            player_name = match.group(1)
        if self.server_thread and self.server_thread.is_running:
            is_op = self._get_server_instance().is_player_op(player_name)
            if is_op:
                self.server_thread.send_command(f"deop {player_name}")
            else:
                self.server_thread.send_command(f"op {player_name}")
                
    def send_message_to_player(self):
        en = getattr(self, "lang", "tr") == "en"
        selected = self.player_list.currentItem()
        if not selected:
            return
            
        player_name = selected.data(Qt.UserRole)
        if not player_name:
            import re
            match = re.search(r'(?:\[[^\]]+\]|[🟢⚪])\s+([^\s]+)', selected.text())
            if not match:
                return
            player_name = match.group(1)
        
        if not (self.server_thread and self.server_thread.is_running):
            self.log("[ERROR] Cannot send messages while server is offline." if en else "[HATA] Sunucu kapalıyken mesaj gönderemezsiniz.")
            return
            
        from PySide6.QtWidgets import QInputDialog, QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        
        # Özel bir diyalog penceresi oluşturalım ki hem gönderen ismini hem mesajı tek seferde sorabilelim.
        dialog = QDialog(self)
        dialog.setWindowTitle("Send Private Message" if en else "Özel Mesaj Gönder")
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("Sender Name (e.g. Admin, Owner, System):" if en else "Gönderen İsmi (Örn: Yönetici, Kurucu, Sistem):"))
        sender_input = QLineEdit("Admin" if en else "Yönetici")
        layout.addWidget(sender_input)
        
        layout.addWidget(QLabel(f"Message to {player_name}:" if en else f"{player_name} adlı oyuncuya mesajınız:"))
        msg_input = QLineEdit()
        layout.addWidget(msg_input)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("Send" if en else "Gönder")
        btn_cancel = QPushButton("Cancel" if en else "İptal")
        btn_ok.clicked.connect(dialog.accept)
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        if dialog.exec() == QDialog.Accepted:
            sender = sender_input.text().strip() or ("System" if en else "Sistem")
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
        
        player_name = selected.data(Qt.UserRole)
        if not player_name:
            import re
            match = re.search(r'(?:\[[^\]]+\]|[🟢⚪])\s+([^\s]+)', selected.text())
            if not match:
                return
            player_name = match.group(1)
        
        if self.server_thread and self.server_thread.is_running:
            self.server_thread.send_command(f"{cmd_prefix} {player_name}")

    def open_software_dialog(self):
        en = getattr(self, "lang", "tr") == "en"
        if not self.server_dir:
            self.log("[ERROR] Please select or create a server first." if en else "[HATA] Lütfen önce bir sunucu seçin veya oluşturun.")
            return
            
        from server_downloader import ServerSoftwareDialog
        dialog = ServerSoftwareDialog(self, self.server_dir)
        dialog.exec()
        self.update_dashboard_cards()

    def open_server_folder(self):
        en = getattr(self, "lang", "tr") == "en"
        if self.server_dir and os.path.exists(self.server_dir):
            from ui_components import safe_open_path
            if not safe_open_path(self.server_dir):
                return
            self.log(
                "[INFO] Server folder opened. You can drag mods into 'mods' and plugins into 'plugins'."
                if en else
                "[BİLGİ] Sunucu klasörü açıldı. Modlarınızı 'mods', eklentilerinizi 'plugins' klasörüne sürükleyebilirsiniz."
            )

    def import_client_profile(self, checked=False):
        en = getattr(self, "lang", "tr") == "en"
        store = self._get_profile_store()
        profile_names, profiles_dict = store.list_available_client_profiles()
                
        if not profile_names:
            QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "No client profile found to export!" if en else "Aktarılacak istemci profili bulunamadı!"
            )
            return
            
        dlg = ProfileSelectDialog(profile_names, self, lang=getattr(self, "lang", "tr"))
        if dlg.exec():
            selected_profile = dlg.get_selected()
            ok = True
        else:
            selected_profile = None
            ok = False
            
        if not ok or not selected_profile:
            return
            
        new_name, ok = QInputDialog.getText(
            self,
            "Server Name" if en else "Sunucu Adı",
            "Enter a name for the new server:" if en else "Oluşturulacak sunucu için bir isim girin:",
            text=f"{selected_profile}_Server"
        )
        if not ok or not new_name.strip():
            return
            
        new_name = re.sub(r'[\\/*?:"<>|.]', '_', new_name.strip()).strip('_ ')
        if not new_name:
            return
        new_dir = os.path.join(self.servers_dir, new_name)
        if not os.path.realpath(new_dir).startswith(os.path.realpath(self.servers_dir) + os.sep):
            return
        if os.path.exists(new_dir):
            self.log("[ERROR] A folder with this name already exists." if en else "[HATA] Bu isimde bir klasör zaten var.")
            return
            
        client_dir, matched_pdata = store.resolve_client_profile_dir(
            selected_profile,
            profiles_dict=profiles_dict,
            fallback_base_dir=get_base_dir(),
        )
        if not client_dir:
            expected_dir = os.path.join(self.profiles_dir, selected_profile)
            self.log(f"[ERROR] Profile folder not found: {expected_dir}" if en else f"[HATA] Profil klasörü bulunamadı: {expected_dir}")
            QMessageBox.warning(
                self,
                "Error" if en else "Hata",
                f"Profile folder '{selected_profile}' not found!" if en else f"'{selected_profile}' profil klasörü bulunamadı!"
            )
            return
                    
        try:
            ServerInstance(new_dir).import_from_client_profile(client_dir)
            mods_dir = os.path.join(client_dir, "mods")
                
            self.refresh_server_list(preferred_name=new_name)
            
            idx = self.server_selector.findText(new_name)
            if idx >= 0:
                self.server_selector.setCurrentIndex(idx)
            self.server_dir = new_dir
            self.load_server_properties()
                
            self.log(f"[INFO] Client profile exported: {new_name}" if en else f"[BİLGİ] İstemci profili aktarıldı: {new_name}")
            
            # Sürümü ve motoru otomatik bulmaya çalış
            probe_data = dict(matched_pdata) if isinstance(matched_pdata, dict) else {}
            probe_data["path"] = client_dir
            spec = RuntimeProvisioner.detect_client_runtime(probe_data)
            auto_version = spec.mc_version if (probe_data.get("version") or probe_data.get("game_version")) else None
            detected_loader = "fabric" if spec.loader == "quilt" else (spec.loader if spec.loader != "vanilla" else None)
                    
            if not auto_version and os.path.exists(mods_dir):
                mod_files = os.listdir(mods_dir)
                versions_to_check = ["1.21.1", "1.20.4", "1.20.1", "1.19.4", "1.18.2", "1.16.5"]
                version_counts = {v: 0 for v in versions_to_check}
                
                for mod in mod_files:
                    for v in versions_to_check:
                        if v in mod:
                            version_counts[v] += 1
                
                best_version = max(version_counts, key=version_counts.get)
                if version_counts[best_version] > 0:
                    auto_version = best_version
                    
            if not auto_version:
                auto_version = "1.20.1"

            from server_downloader import ServerSoftwareDialog

            if detected_loader == "fabric":
                self.log(
                    f"[INFO] Fabric client profile detected. Installing Fabric server automatically... (Version: {auto_version})"
                    if en else
                    f"[BİLGİ] Fabric istemci profili tespit edildi. Otomatik Fabric sunucusu kuruluyor... (Sürüm: {auto_version})"
                )
                dialog = ServerSoftwareDialog(self, self.server_dir, auto_software="Fabric (Mod)", auto_version=auto_version)
                dialog.exec()
            elif detected_loader in ("forge", "neoforge"):
                loader_display = "Forge" if detected_loader == "forge" else "NeoForge"
                self.log(
                    f"[INFO] {loader_display} client profile detected. Installing {loader_display} server automatically... (Version: {auto_version})"
                    if en else
                    f"[BİLGİ] {loader_display} istemci profili tespit edildi. Otomatik {loader_display} sunucusu kuruluyor... (Sürüm: {auto_version})"
                )
                dialog = ServerSoftwareDialog(self, self.server_dir, auto_software=f"{loader_display} (Mod)", auto_version=auto_version)
                dialog.exec()
            else:
                self.log(
                    f"[INFO] Vanilla or external client profile detected. Opening server software selection... (Version: {auto_version})"
                    if en else
                    f"[BİLGİ] Vanilla veya harici istemci profili tespit edildi. Sunucu yazılımı seçim ekranı açılıyor... (Sürüm: {auto_version})"
                )
                dialog = ServerSoftwareDialog(self, self.server_dir, auto_version=auto_version)
                dialog.exec()
            self.update_dashboard_cards()
            
        except Exception as e:
            self.log(f"[ERROR] Error exporting profile: {e}" if en else f"[HATA] Profil aktarılırken hata oluştu: {e}")

    def create_new_server(self, checked=False):
        from PySide6.QtWidgets import QInputDialog
        en = getattr(self, "lang", "tr") == "en"
        
        new_name, ok = QInputDialog.getText(
            self,
            "New Server" if en else "Yeni Sunucu",
            "New server folder name:" if en else "Yeni sunucu klasörü adı:"
        )
        if ok and new_name.strip():
            clean_name = re.sub(r'[\\/*?:"<>|.]', '_', new_name.strip()).strip('_ ')
            if not clean_name:
                return
            new_dir = os.path.join(self.servers_dir, clean_name)
            if not os.path.realpath(new_dir).startswith(os.path.realpath(self.servers_dir) + os.sep):
                return
            if os.path.exists(new_dir):
                self.log("[ERROR] A folder with this name already exists." if en else "[HATA] Bu isimde bir klasör zaten var.")
                return
                
            try:
                ServerInstance(new_dir).initialize_directory()
                    
                self.refresh_server_list(preferred_name=clean_name)
                
                # Yeni oluşturulanı seç
                idx = self.server_selector.findText(clean_name)
                if idx >= 0:
                    self.server_selector.setCurrentIndex(idx)
                self.server_dir = new_dir
                self.load_server_properties()
                    
                self.log(f"[INFO] New server profile created: {new_dir}" if en else f"[BİLGİ] Yeni sunucu profili oluşturuldu: {new_dir}")
                self.log("[INFO] Opening automatic software installer..." if en else "[BİLGİ] Otomatik yazılım kurulum ekranı açılıyor...")
                
                from server_downloader import ServerSoftwareDialog
                dialog = ServerSoftwareDialog(self, self.server_dir)
                dialog.exec()
                self.update_dashboard_cards()
                
            except Exception as e:
                self.log(f"[ERROR] Could not create folder: {e}" if en else f"[HATA] Klasör oluşturulamadı: {e}")

    def load_server_properties(self):
        props = self._get_server_instance().read_properties() if self.server_dir else ServerProperties()
        self._last_saved_props = None
        self.spin_max_players.setValue(props.max_players)
        self.spin_view_distance.setValue(props.view_distance)
        idx_diff = self.combo_difficulty.findText(props.difficulty)
        if idx_diff >= 0:
            self.combo_difficulty.setCurrentIndex(idx_diff)
        else:
            self.combo_difficulty.setCurrentText("easy")
        self.line_seed.setText(props.level_seed)
        self.line_level_name.setText(props.level_name)
        idx_gm = self.combo_gamemode.findText(props.gamemode)
        if idx_gm >= 0:
            self.combo_gamemode.setCurrentIndex(idx_gm)
        else:
            self.combo_gamemode.setCurrentText("survival")
        self.line_motd.setText(props.motd)
        self.spin_spawn_protection.setValue(props.spawn_protection)
        self.spin_sim_distance.setValue(props.simulation_distance)
        self.chk_crack.setChecked(not props.online_mode)
        self.chk_pvp.setChecked(props.pvp)
                    
    def save_server_properties(self):
        en = getattr(self, "lang", "tr") == "en"
        if not self.server_dir:
            return
        inst = self._get_server_instance()
        current = inst.read_properties()
        props = ServerProperties(
            max_players=self.spin_max_players.value(),
            view_distance=self.spin_view_distance.value(),
            difficulty=self.combo_difficulty.currentText(),
            online_mode=not self.chk_crack.isChecked(),
            pvp=self.chk_pvp.isChecked(),
            level_seed=self.line_seed.text().strip(),
            level_name=self.line_level_name.text().strip() or "world",
            gamemode=self.combo_gamemode.currentText(),
            motd=self.line_motd.text(),
            spawn_protection=self.spin_spawn_protection.value(),
            simulation_distance=self.spin_sim_distance.value(),
            server_port=current.server_port,
        )
        if (
            getattr(self, "_last_saved_props", None) == (self.server_dir, props)
            and props == current
            and os.path.exists(os.path.join(self.server_dir, "server.properties"))
        ):
            return
        inst.write_properties(props)
        self._last_saved_props = (self.server_dir, props)
        self.log("[INFO] Settings saved." if en else "[BİLGİ] Ayarlar kaydedildi.")
        self.update_dashboard_cards()

    def refresh_backup_list(self):
        self.backup_list.clear()
        if not self.server_dir: return
        for file in BackupManager.list_backups(self.server_dir):
            self.backup_list.addItem(file)
        self.update_dashboard_cards()

    def take_backup(self, checked=False):
        if not self.server_dir: return
        lang = getattr(self, "lang", "tr")
        en = lang == "en"
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.btn_take_backup.setEnabled(False)
        self.log("[INFO] Starting backup..." if en else "[BİLGİ] Yedekleme başlatılıyor...")
        
        if not hasattr(self, '_api_threads'): self._api_threads = []
        self._api_threads = [t for t in self._api_threads if t.isRunning()]
        
        # Progress Dialog
        from PySide6.QtWidgets import QProgressDialog
        self._backup_progress = QProgressDialog(
            "Preparing backup..." if en else "Yedekleme hazırlanıyor...",
            None, 0, 100, self
        )
        self._backup_progress.setWindowTitle("Backup Operation" if en else "Yedekleme İşlemi")
        self._backup_progress.setMinimumWidth(400)
        self._backup_progress.setStyleSheet("QProgressDialog { background-color: #2D2D30; color: white; } QProgressBar { border: 1px solid #555; border-radius: 5px; text-align: center; background: #1E1E1E; } QProgressBar::chunk { background-color: #007ACC; border-radius: 5px; } QLabel { color: white; font-size: 13px; }")
        self._backup_progress.setCancelButton(None)
        self._backup_progress.setMinimumDuration(0)
        self._backup_progress.show()
        
        thread = BackupThread(
            self.server_dir,
            delete_local=self.chk_delete_local.isChecked(),
            server_thread=self.server_thread,
            lang=lang,
            coordinator=getattr(self, 'process_coordinator', None),
        )
        self._api_threads.append(thread)
        thread.stage_update.connect(lambda text: self._backup_progress.setLabelText(text) if getattr(self, '_backup_progress', None) else None)
        thread.progress_update.connect(lambda val: self._backup_progress.setValue(val) if getattr(self, '_backup_progress', None) else None)
        thread.backup_finished.connect(self.on_backup_finished)
        thread.start()

    def on_backup_finished(self, success, message):
        en = getattr(self, "lang", "tr") == "en"
        self.btn_take_backup.setEnabled(True)
        if hasattr(self, '_backup_progress') and self._backup_progress:
            self._backup_progress.setValue(100)
            self._backup_progress.close()
            self._backup_progress = None
        if success:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_levelup()
            except Exception:
                pass
            self.log(f"[INFO] {message}" if en else f"[BİLGİ] {message}")
            self.refresh_backup_list()
        else:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            self.log(f"[ERROR] {message}" if en else f"[HATA] {message}")

    def restore_backup(self):
        if not self.server_dir: return
        lang = getattr(self, "lang", "tr")
        en = lang == "en"
        if self.server_thread and (self.server_thread.isRunning() or getattr(self.server_thread, 'is_running', False)):
            QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "Cannot restore backup while the server is running. Please stop the server first."
                if en else
                "Sunucu çalışırken yedek geri yüklenemez. Lütfen önce sunucuyu durdurun."
            )
            return

        lock_path = os.path.join(self.server_dir, "world", "session.lock")
        if os.path.isfile(lock_path):
            try:
                with open(lock_path, "r+b"):
                    pass
            except (PermissionError, OSError):
                QMessageBox.warning(
                    self,
                    "Warning" if en else "Uyarı",
                    "Server world files are currently in use by another process. Please wait for the server to fully shut down."
                    if en else
                    "Sunucu dünya dosyaları başka bir işlem tarafından kilitlenmiş. Lütfen sunucunun tamamen kapanmasını bekleyin."
                )
                return
            
        selected = self.backup_list.currentItem()
        if not selected:
            QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "Please select a backup to restore." if en else "Lütfen geri yüklenecek bir yedek seçin."
            )
            return
        
        reply = QMessageBox.question(
            self,
            "Confirm" if en else "Onay",
            "The selected backup will be restored. Existing files may be overwritten. Are you sure?"
            if en else
            "Seçilen yedek geri yüklenecek. Mevcut dosyalar üzerine yazılabilir. Emin misiniz?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_click()
            except Exception:
                pass
            self.btn_restore_backup.setEnabled(False)
            self.log(f"[INFO] Restoring {selected.text()}..." if en else f"[BİLGİ] {selected.text()} geri yükleniyor...")
            
            if not hasattr(self, '_api_threads'): self._api_threads = []
            self._api_threads = [t for t in self._api_threads if t.isRunning()]
            
            zip_path = os.path.join(self.server_dir, "backups", selected.text())
            thread = RestoreThread(self.server_dir, zip_path, lang=lang)
            self._api_threads.append(thread)
            thread.restore_finished.connect(self.on_restore_finished)
            thread.start()

    def on_restore_finished(self, success, message):
        en = getattr(self, "lang", "tr") == "en"
        self.btn_restore_backup.setEnabled(True)
        if success:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_levelup()
            except Exception:
                pass
            self.log(f"[INFO] {message}" if en else f"[BİLGİ] {message}")
        else:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            self.log(f"[ERROR] {message}" if en else f"[HATA] {message}")

    def search_modrinth(self):
        if not self.btn_search_mod.isEnabled(): return
        query = self.mod_search_input.text().strip()
        if not query: return
        en = getattr(self, "lang", "tr") == "en"
        
        project_type = "mod" if self.mod_type_combo.currentText() == "Mod" else "plugin"
        self.btn_search_mod.setEnabled(False)
        self.lbl_mod_status.setText("Searching..." if en else "Aranıyor...")
        self.mod_result_list.clear()
        
        if not hasattr(self, '_api_threads'): self._api_threads = []
        self._api_threads = [t for t in self._api_threads if t.isRunning()]
        
        loader, version = detect_server_loader_and_version(self.server_dir)
        thread = ModrinthSearchThread(query, project_type, game_version=version, loader=loader)
        self._api_threads.append(thread)
        thread.search_finished.connect(self.on_search_finished)
        thread.start()

    def on_search_finished(self, results):
        en = getattr(self, "lang", "tr") == "en"
        self.btn_search_mod.setEnabled(True)
        if not results:
            self.lbl_mod_status.setText("No results found." if en else "Sonuç bulunamadı.")
            return
        
        self.lbl_mod_status.setText(f"{len(results)} results found." if en else f"{len(results)} sonuç bulundu.")
        for item in results:
            title = item.get("title", "Untitled" if en else "İsimsiz")
            author = item.get("author", "Unknown" if en else "Bilinmiyor")
            desc = item.get("description", "")
            project_id = item.get("project_id", "")
            
            display_text = f"{title} ({author}) - {desc}"
            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.UserRole, project_id)
            self.mod_result_list.addItem(list_item)

    def download_modrinth_project(self):
        if not self.server_dir: return
        lang = getattr(self, "lang", "tr")
        en = lang == "en"
        selected = self.mod_result_list.currentItem()
        if not selected:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            QMessageBox.warning(
                self,
                "Warning" if en else "Uyarı",
                "Please select a mod/plugin to download." if en else "Lütfen indirilecek modu/eklentiyi seçin."
            )
            return
            
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass
            
        project_id = selected.data(Qt.UserRole)
        project_type = "mod" if self.mod_type_combo.currentText() == "Mod" else "plugin"
        
        self.btn_download_mod.setEnabled(False)
        proj_title = selected.text().split(' (')[0]
        self.lbl_mod_status.setText(f"Downloading {proj_title}..." if en else f"{proj_title} indiriliyor...")
        
        if not hasattr(self, '_api_threads'): self._api_threads = []
        self._api_threads = [t for t in self._api_threads if t.isRunning()]
        
        loader, version = detect_server_loader_and_version(self.server_dir)
        thread = ModrinthDownloadThread(project_id, self.server_dir, project_type, game_version=version, loader=loader, lang=lang)
        self._api_threads.append(thread)
        thread.download_finished.connect(self.on_download_finished)
        thread.start()

    def on_download_finished(self, success, message):
        en = getattr(self, "lang", "tr") == "en"
        self.btn_download_mod.setEnabled(True)
        if success:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_levelup()
            except Exception:
                pass
            self.lbl_mod_status.setText("Download completed!" if en else "İndirme tamamlandı!")
            self.log(f"[INFO] {message}" if en else f"[BİLGİ] {message}")
            self.update_dashboard_cards()
        else:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_error()
            except Exception:
                pass
            self.lbl_mod_status.setText("Download failed!" if en else "İndirme başarısız!")
            self.log(f"[ERROR] {message}" if en else f"[HATA] {message}")

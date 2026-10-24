from __future__ import annotations

import os
import re
import time
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QScrollArea,
    QComboBox,
    QGridLayout,
)
from PySide6.QtGui import QPixmap

from mod_manager import (
    ModrinthSearchThread,
    ProjectDetailsThread,
    DEFAULT_CATALOG,
    DEFAULT_CURSEFORGE_CATALOG,
    CompatibilityPolicy,
)
from card_widget import CardWidget, ImageLoaderThread, format_number, _ICON_CACHE
import sys

_ORIG_SEARCH_THREAD = ModrinthSearchThread
_ORIG_DETAILS_THREAD = ProjectDetailsThread
_ACTIVE_BROWSER_THREADS: list = []


def _resolve_details_thread_cls():
    if ProjectDetailsThread is not _ORIG_DETAILS_THREAD:
        return ProjectDetailsThread
    main_mod = sys.modules.get("main")
    if main_mod is not None and hasattr(main_mod, "ProjectDetailsThread"):
        return getattr(main_mod, "ProjectDetailsThread")
    return ProjectDetailsThread


def _resolve_search_thread_cls():
    if ModrinthSearchThread is not _ORIG_SEARCH_THREAD:
        return ModrinthSearchThread
    main_mod = sys.modules.get("main")
    if main_mod is not None and hasattr(main_mod, "ModrinthSearchThread"):
        return getattr(main_mod, "ModrinthSearchThread")
    return ModrinthSearchThread


def _track_browser_thread(thread):
    _ACTIVE_BROWSER_THREADS[:] = [t for t in _ACTIVE_BROWSER_THREADS if getattr(t, "isRunning", lambda: False)()]
    _ACTIVE_BROWSER_THREADS.append(thread)
    if hasattr(thread, "finished") and hasattr(thread.finished, "connect"):
        try:
            thread.finished.connect(lambda t=thread: _ACTIVE_BROWSER_THREADS.remove(t) if t in _ACTIVE_BROWSER_THREADS else None)
        except Exception:
            pass


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
        self.current_data = None
        self._current_preview_pixmap = None
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
        self.current_project = None
        self.current_data = None
        self._current_preview_pixmap = None
        self.hide()
        self.drawer_closed.emit()

    def set_ram(self, amount):
        if getattr(self, "selected_ram", None) == amount:
            return
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
                        background: #7C3AED;
                        border: 1px solid #A855F7;
                        border-radius: 6px;
                        color: #FFFFFF;
                        font-weight: bold;
                        font-size: 11px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: rgba(255, 255, 255, 0.05);
                        border: 1px solid rgba(255, 255, 255, 0.1);
                        border-radius: 6px;
                        color: #94A3B8;
                        font-weight: 600;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background: rgba(255, 255, 255, 0.1);
                        color: #FFFFFF;
                    }
                """)

    def set_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        self.close_btn.setToolTip("Close Panel" if en else "Paneli Kapat")
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
            if v0 in ("En Son Sürüm (Otomatik)", "Latest Version (Auto)", "Default / Latest", "Varsayılan / En Güncel"):
                self.version_combo.setItemText(0, "Latest Version (Auto)" if en else "En Son Sürüm (Otomatik)")
        if not self.current_project:
            self.title.setText("Waiting for Selection" if en else "Seçim Bekleniyor")
            self.download_btn.setText("Install Modpack as New Profile" if en else "Modpack'i Kur ve Profil Oluştur")
        else:
            ptype = self.current_project.get("project_type", "modpack")
            if ptype == "modpack":
                self.download_btn.setText("Install Modpack as New Profile" if en else "Modpack'i Kur ve Profil Oluştur")
            else:
                self.download_btn.setText("Download to Active Profile" if en else "Aktif Profile İndir")

    def update_info(self, data):
        prev = getattr(self, "current_project", None) or getattr(self, "current_data", None)
        parent = self.parentWidget()
        is_panel_open = (
            not self.isHidden()
            and (parent is None or not parent.isHidden())
            and (parent is None or not hasattr(parent, "currentWidget") or parent.currentWidget() is self)
        )
        if is_panel_open and isinstance(prev, dict) and isinstance(data, dict):
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

        self.current_project = data
        self.current_data = data
        self.show()
        en = getattr(self, "lang", "tr") == "en"
        
        ptype = data.get("project_type", "modpack")
        title_str = data.get("title", "Loading..." if en else "Yükleniyor...")
        self.title.setText(title_str)
        
        author = data.get("author") or ""
        self.author_lbl.setText(f"by {author}" if author else "")
        self.author_lbl.setVisible(bool(author))
            
        downloads = data.get("downloads", 0)
        follows = data.get("follows", 0)
        self.downloads_lbl.setText(f"📥 {format_number(downloads)}")
        self.follows_lbl.setText(f"⭐ {format_number(follows)}")
        
        # Clear old tags
        while self.tags_row.count():
            item = self.tags_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        # Add tags
        categories = data.get("categories", [])
        for cat in categories[:4]:
            if cat.lower() in ("modpack", "minecraft"): continue
            pill = QLabel(cat.capitalize(), self)
            pill.setWindowFlags(Qt.Widget)
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
        cat = DEFAULT_CURSEFORGE_CATALOG if data.get("source") == "curseforge" else DEFAULT_CATALOG
        details_cls = _resolve_details_thread_cls()
        thread = details_cls(project_id, version=v_filter, loader=l_filter, catalog=cat)
        self._api_threads.append(thread)
        _track_browser_thread(thread)
        thread.task_finished.connect(self.on_details_loaded)
        thread.start()

    show_project = update_info

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
            self.version_combo.addItem("Default / Latest" if en else "Varsayılan / En Güncel", None)

        gallery = details.get("gallery", [])
        urls_to_load = []
        if gallery:
            for item in gallery:
                url = item.get("url")
                if url:
                    urls_to_load.append(url)
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

    def set_main_preview(self, pixmap):
        cur_pix = getattr(self, "_current_preview_pixmap", None)
        if cur_pix is not None and (
            cur_pix is pixmap
            or (
                hasattr(cur_pix, "cacheKey")
                and hasattr(pixmap, "cacheKey")
                and cur_pix.cacheKey() == pixmap.cacheKey()
            )
        ):
            existing = self.main_gallery_preview.pixmap()
            if existing is not None and not existing.isNull():
                return
        self._current_preview_pixmap = pixmap
        scaled = pixmap.scaled(self.main_gallery_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.main_gallery_preview.setPixmap(scaled)
        self.main_gallery_preview.setText("")

    def clear_gallery(self):
        self._current_preview_pixmap = None
        self._current_gallery_urls.clear()
        self._loaded_thumb_urls.clear()
        self.main_gallery_preview.clear()
        en = getattr(self, "lang", "tr") == "en"
        self.main_gallery_preview.setText("Loading Visuals..." if en else "Görseller Yükleniyor...")
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def on_download_click(self):
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        if not self.current_project: return
        payload = dict(self.current_project)
        payload["selected_ram"] = self.selected_ram
        selected_ver = self.version_combo.currentData()
        if selected_ver:
            payload["selected_version"] = selected_ver
            payload["selected_version_obj"] = selected_ver
        self.download_requested.emit(payload)

    def add_thumbnail(self, pixmap):
        thumb_btn = QPushButton(self.thumb_container)
        thumb_btn.setWindowFlags(Qt.Widget)
        thumb_btn.setFixedSize(48, 48)
        thumb_btn.setCursor(Qt.PointingHandCursor)
        thumb_pix = pixmap.scaled(44, 44, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        from PySide6.QtGui import QIcon
        thumb_btn.setIcon(QIcon(thumb_pix))
        thumb_btn.setIconSize(QSize(44, 44))
        thumb_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 0, 0, 0.4);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 1px;
            }
            QPushButton:hover {
                border-color: #C084FC;
            }
        """)
        thumb_btn.clicked.connect(lambda ch=False, p=pixmap: self.set_main_preview(p))
        self.thumb_layout.addWidget(thumb_btn)


_MODRINTH_CACHE = {}
_MODRINTH_CACHE_TTL = 900  # 15 minutes TTL for instant 0ms tab switching


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
        
        # Search Row + Unified Source Switcher
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        
        self.search_input = QLineEdit()
        self.search_input.setFixedHeight(38)
        self.search_input.setPlaceholderText(f"{project_type.capitalize()} ara... (Yazmaya başlayın)")
        self.search_input.textChanged.connect(self.on_text_changed)
        top_row.addWidget(self.search_input, 1)

        self.current_source = "modrinth"
        self.source_container = QWidget(self)
        self.source_container.setFixedHeight(38)
        source_box_layout = QHBoxLayout(self.source_container)
        source_box_layout.setContentsMargins(4, 4, 4, 4)
        source_box_layout.setSpacing(4)
        self.source_container.setStyleSheet("background: rgba(22, 22, 30, 0.95); border: 1px solid rgba(139, 92, 246, 0.25); border-radius: 8px;")

        self.btn_source_modrinth = QPushButton("Modrinth", self.source_container)
        self.btn_source_modrinth.setFixedHeight(28)
        self.btn_source_modrinth.setCursor(Qt.PointingHandCursor)
        self.btn_source_modrinth.clicked.connect(lambda ch=False: self.set_source("modrinth"))

        self.btn_source_curseforge = QPushButton("CurseForge", self.source_container)
        self.btn_source_curseforge.setFixedHeight(28)
        self.btn_source_curseforge.setCursor(Qt.PointingHandCursor)
        self.btn_source_curseforge.clicked.connect(lambda ch=False: self.set_source("curseforge"))

        source_box_layout.addWidget(self.btn_source_modrinth)
        source_box_layout.addWidget(self.btn_source_curseforge)
        top_row.addWidget(self.source_container)
        self.update_source_styles()

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
        for v in ["1.21.4", "1.21.3", "1.21.2", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.2", "1.20.1", "1.20", "1.19.4", "1.19.2", "1.18.2", "1.16.5", "1.12.2", "1.7.10"]:
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

        # For modpacks, default to "all" so catalog isn't constrained to the active profile's version/loader
        if self.project_type == "modpack":
            self.version_combo.blockSignals(True)
            self.loader_combo.blockSignals(True)
            self.version_combo.setCurrentIndex(1)
            self.loader_combo.setCurrentIndex(1)
            self.version_combo.blockSignals(False)
            self.loader_combo.blockSignals(False)
        
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

    def set_source(self, source):
        if getattr(self, "current_source", "modrinth") == source:
            return
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_click()
        except Exception:
            pass
        self.current_source = source
        self.update_source_styles()
        self.search()

    def update_source_styles(self):
        if not hasattr(self, 'btn_source_modrinth'): return
        if getattr(self, "current_source", "modrinth") == "curseforge":
            self.btn_source_modrinth.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #94A3B8;
                    font-size: 11px;
                    font-weight: 600;
                    border: none;
                    border-radius: 4px;
                    padding: 3px 12px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #FFFFFF;
                }
            """)
            self.btn_source_curseforge.setStyleSheet("""
                QPushButton {
                    background-color: #EA580C;
                    color: #FFFFFF;
                    font-size: 11px;
                    font-weight: bold;
                    border: 1px solid #C2410C;
                    border-top: 1.5px solid #FB923C;
                    border-bottom: 2.5px solid #9A3412;
                    border-radius: 4px;
                    padding: 3px 12px;
                }
            """)
        else:
            self.btn_source_modrinth.setStyleSheet("""
                QPushButton {
                    background-color: #059669;
                    color: #FFFFFF;
                    font-size: 11px;
                    font-weight: bold;
                    border: 1px solid #047857;
                    border-top: 1.5px solid #34D399;
                    border-bottom: 2.5px solid #065F46;
                    border-radius: 4px;
                    padding: 3px 12px;
                }
            """)
            self.btn_source_curseforge.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #94A3B8;
                    font-size: 11px;
                    font-weight: 600;
                    border: none;
                    border-radius: 4px;
                    padding: 3px 12px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    color: #FFFFFF;
                }
            """)

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
        if self.selected_card == card:
            return
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
        source = getattr(self, "current_source", "modrinth")
        catalog = DEFAULT_CURSEFORGE_CATALOG if source == "curseforge" else DEFAULT_CATALOG
        version = self.get_active_version()
        loader = self.get_active_loader()
        sort_index = self.sort_combo.currentData() if hasattr(self, 'sort_combo') else "downloads"
        cache_key = (source, self.project_type, "", sort_index, version, loader, self.current_category)
        now = time.time()
        if cache_key in _MODRINTH_CACHE:
            ts, cached_res = _MODRINTH_CACHE[cache_key]
            if now - ts < _MODRINTH_CACHE_TTL:
                self.populate(cached_res)
                return

        self.clear_grid()
        loading_lbl = QLabel("Loading..." if getattr(self, "lang", "tr") == "en" else "Yükleniyor...", parent=self.grid_container)
        loading_lbl.setAlignment(Qt.AlignCenter)
        loading_lbl.setStyleSheet("color: #C084FC; font-size: 15px; font-weight: 700; margin-top: 40px;")
        self.grid_layout.addWidget(loading_lbl, 0, 0, 1, self.columns)
        
        if not hasattr(self, '_search_threads'):
            self._search_threads = []
            
        self._search_threads = [t for t in self._search_threads if t.isRunning()]
        
        search_cls = _resolve_search_thread_cls()
        thread = search_cls("", self.project_type, sort_index, 24, version, loader, self.current_category, catalog=catalog)
        thread._cache_key = cache_key
        thread.search_finished.connect(self.on_search_finished)
        self._search_threads.append(thread)
        _track_browser_thread(thread)
        self._search_thread = thread
        thread.start()

    def search(self):
        query = self.search_input.text().strip()
        if not query and not self.current_category:
            self.load_trending()
            return

        source = getattr(self, "current_source", "modrinth")
        catalog = DEFAULT_CURSEFORGE_CATALOG if source == "curseforge" else DEFAULT_CATALOG
        version = self.get_active_version()
        loader = self.get_active_loader()
        sort_index = self.sort_combo.currentData() if hasattr(self, 'sort_combo') else "relevance"
        cache_key = (source, self.project_type, query, sort_index, version, loader, self.current_category)
        now = time.time()
        if cache_key in _MODRINTH_CACHE:
            ts, cached_res = _MODRINTH_CACHE[cache_key]
            if now - ts < _MODRINTH_CACHE_TTL:
                self.populate(cached_res)
                return

        self.clear_grid()
        loading_lbl = QLabel("Loading..." if getattr(self, "lang", "tr") == "en" else "Yükleniyor...", parent=self.grid_container)
        loading_lbl.setAlignment(Qt.AlignCenter)
        loading_lbl.setStyleSheet("color: #C084FC; font-size: 15px; font-weight: 700; margin-top: 40px;")
        self.grid_layout.addWidget(loading_lbl, 0, 0, 1, self.columns)
        
        if not hasattr(self, '_search_threads'):
            self._search_threads = []
            
        self._search_threads = [t for t in self._search_threads if t.isRunning()]
        
        search_cls = _resolve_search_thread_cls()
        thread = search_cls(query, self.project_type, sort_index, 24, version, loader, self.current_category, catalog=catalog)
        thread._cache_key = cache_key
        thread.search_finished.connect(self.on_search_finished)
        self._search_threads.append(thread)
        _track_browser_thread(thread)
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

        cache_key = getattr(sender, '_cache_key', None)
        if cache_key and results:
            if len(_MODRINTH_CACHE) >= 120:
                first_k = next(iter(_MODRINTH_CACHE), None)
                if first_k:
                    _MODRINTH_CACHE.pop(first_k, None)
            _MODRINTH_CACHE[cache_key] = (time.time(), results)

        self.populate(results)

    def clear_grid(self):
        self._populate_token = getattr(self, "_populate_token", 0) + 1
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

        if not results:
            return

        self._populate_token = getattr(self, "_populate_token", 0) + 1
        curr_token = self._populate_token

        def render_chunk(start_idx):
            if getattr(self, "_populate_token", 0) != curr_token:
                return
            end_idx = min(start_idx + 6, len(results))
            for i in range(start_idx, end_idx):
                data = results[i]
                card = CardWidget(data, parent=self.grid_container, lang=getattr(self, "lang", "tr"))
                card.clicked.connect(lambda d=data, c=card: self.on_card_clicked(d, c))
                if hasattr(card, 'update_clicked'):
                    card.update_clicked.connect(self.update_item_requested.emit)
                self.cards.append(card)
                row = i // self.columns
                col = i % self.columns
                self.grid_layout.addWidget(card, row, col)
            if end_idx < len(results):
                QTimer.singleShot(10, lambda: render_chunk(end_idx))

        render_chunk(0)


class ContentBrowserPanel(QWidget):
    """
    Consolidated deep content browsing module.
    Presents a clean interface combining the catalog grid and detail drawer.
    """
    install_requested = Signal(object)
    profile_selected = Signal(str)

    def __init__(self, project_type: str = "modpack", parent=None):
        super().__init__(parent)
        self.project_type = project_type
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(12)

        self.browser = ModrinthBrowser(project_type, self)
        self.detail_panel = DetailPanel(self)
        self.detail_panel.hide()

        self.layout.addWidget(self.browser, 1)
        self.layout.addWidget(self.detail_panel)

        self.browser.item_selected.connect(self._on_item_selected)
        self.browser.selection_cleared.connect(self.detail_panel.close_drawer)
        self.detail_panel.drawer_closed.connect(self._on_drawer_closed)
        self.detail_panel.download_requested.connect(self.install_requested.emit)

    def _on_item_selected(self, data):
        self.browser.set_columns(3)
        self.detail_panel.update_info(data)

    def _on_drawer_closed(self):
        self.browser.set_columns(4)
        self.browser.clear_selection()

    def set_language(self, lang: str):
        self.browser.set_language(lang)
        self.detail_panel.set_language(lang)


# Semantic Aliases adhering to Deep Module specifications
ModDetailDrawer = DetailPanel
ContentBrowserWidget = ContentBrowserPanel
SearchToolbar = QWidget
GridScrollArea = QScrollArea

__all__ = [
    "DetailPanel",
    "ModDetailDrawer",
    "ModrinthBrowser",
    "ContentBrowserPanel",
    "ContentBrowserWidget",
    "SearchToolbar",
    "GridScrollArea",
    "_MODRINTH_CACHE",
    "_MODRINTH_CACHE_TTL",
]

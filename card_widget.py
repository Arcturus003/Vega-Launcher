from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QSizePolicy)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QPixmap
import requests

def format_number(val):
    if not val:
        return "0"
    try:
        val = int(val)
    except (ValueError, TypeError):
        return str(val)
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    elif val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return str(val)

_ICON_CACHE = {}
_PIXMAP_CACHE = {}
_MAX_CACHE_SIZE = 300
_MAX_CONCURRENT_ICON_THREADS = 6
_PENDING_ICON_QUEUE = []
_IN_FLIGHT_REQUESTS = {}

def _cache_icon(url, data_bytes):
    if not url or not data_bytes:
        return
    if len(_ICON_CACHE) >= _MAX_CACHE_SIZE:
        try:
            first_key = next(iter(_ICON_CACHE))
            del _ICON_CACHE[first_key]
            _PIXMAP_CACHE.pop(first_key, None)
        except (StopIteration, KeyError):
            pass
    _ICON_CACHE[url] = data_bytes

def _process_icon_queue():
    while _PENDING_ICON_QUEUE and len(CardWidget._active_threads) < _MAX_CONCURRENT_ICON_THREADS:
        item = _PENDING_ICON_QUEUE.pop(0)
        if isinstance(item, tuple):
            card_ref, url = item
            if url not in _IN_FLIGHT_REQUESTS:
                _IN_FLIGHT_REQUESTS[url] = []
            _IN_FLIGHT_REQUESTS[url].append(card_ref)
        else:
            url = item

        if not url:
            continue

        if url in _PIXMAP_CACHE or url in _ICON_CACHE:
            refs = _IN_FLIGHT_REQUESTS.pop(url, [])
            cached_pix = _PIXMAP_CACHE.get(url)
            cached_data = _ICON_CACHE.get(url)
            val = cached_pix if cached_pix is not None else cached_data
            for ref in refs:
                c = ref() if hasattr(ref, "__call__") else ref
                if c:
                    try:
                        c.set_icon(val)
                    except (RuntimeError, Exception):
                        pass
            continue

        thread = ImageLoaderThread(url)
        CardWidget._active_threads.add(thread)

        def _on_loaded(data, u=url):
            _cache_icon(u, data)
            scaled = None
            try:
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    scaled = pixmap.scaled(38, 38, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    if len(_PIXMAP_CACHE) >= _MAX_CACHE_SIZE:
                        first_k = next(iter(_PIXMAP_CACHE), None)
                        if first_k:
                            _PIXMAP_CACHE.pop(first_k, None)
                    _PIXMAP_CACHE[u] = scaled
            except Exception:
                pass
            refs = _IN_FLIGHT_REQUESTS.pop(u, [])
            for ref in refs:
                c = ref() if hasattr(ref, "__call__") else ref
                if c:
                    try:
                        c.set_icon(scaled if scaled is not None else data)
                    except (RuntimeError, Exception):
                        pass

        def _on_finished(th=thread, u=url):
            CardWidget._active_threads.discard(th)
            _IN_FLIGHT_REQUESTS.pop(u, None)
            _process_icon_queue()

        thread.loaded.connect(_on_loaded)
        thread.finished.connect(_on_finished)
        thread.start()

class ImageLoaderThread(QThread):
    loaded = Signal(bytes)
    loaded_with_url = Signal(str, bytes)
    def __init__(self, url):
        super().__init__()
        self.url = url
    def run(self):
        try:
            resp = requests.get(self.url, timeout=7, headers={"User-Agent": "VegaLauncher/2.0.0"})
            if resp.status_code == 200:
                self.loaded.emit(resp.content)
                self.loaded_with_url.emit(self.url, resp.content)
        except Exception:
            pass

class CardWidget(QFrame):
    clicked = Signal(object)
    update_clicked = Signal(object)
    _active_threads = set()
    
    def __init__(self, data, parent=None, lang=None):
        super().__init__(parent, Qt.Widget)
        self.setWindowFlags(Qt.Widget)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.data = data
        if lang is None:
            lang = "tr"
            p = parent
            while p is not None:
                if hasattr(p, "lang"):
                    lang = p.lang
                    break
                if hasattr(p, "settings") and isinstance(p.settings, dict):
                    lang = p.settings.get("language", "tr")
                    break
                p = p.parent() if hasattr(p, "parent") and callable(p.parent) else None
        self.lang = lang
        en = self.lang == "en"
        self.setObjectName("ModpackCard")
        self.setMinimumWidth(210)
        self.setFixedHeight(126)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.img_thread = None
        self.is_selected = False
        self.is_hovered = False
        self._active_theme = None
        self.cat_pills = []
        self.destroyed.connect(lambda obj=None: self.cleanup())
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Header (Icon + Title & Author + Version Badge)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        header_layout.setAlignment(Qt.AlignVCenter)

        pt = (data.get("project_type") or "").lower()
        cats = [str(c).lower() for c in (data.get("categories") or [])]
        if "shader" in pt or any("shader" in c for c in cats):
            fallback_sym = ""
        elif "mod" in pt or any("mod" in c for c in cats):
            fallback_sym = ""
        else:
            fallback_sym = ""

        self.icon_lbl = QLabel(fallback_sym, self)
        self.icon_lbl.setWindowFlags(Qt.Widget)
        self.icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.icon_lbl.setFixedSize(38, 38)
        self.icon_lbl.setStyleSheet("background-color: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.25); border-radius: 6px; font-size: 18px;")
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.icon_lbl)
        
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.setAlignment(Qt.AlignVCenter)
        
        self.title = QLabel(data.get("title", "Untitled" if en else "İsimsiz"), self)
        self.title.setWindowFlags(Qt.Widget)
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.title.setObjectName("CardTitle")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 13px; font-weight: 700; color: #F8FAFC; background: transparent; border: none;")
        self.title.setMaximumHeight(32)
        title_box.addWidget(self.title)
        
        author = data.get("author") or ""
        self.author_lbl = QLabel(f"by {author}" if author else "", self)
        self.author_lbl.setWindowFlags(Qt.Widget)
        self.author_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.author_lbl.setStyleSheet("font-size: 11px; color: #94A3B8; font-weight: 500; background: transparent; border: none;")
        self.author_lbl.setVisible(bool(author))
        title_box.addWidget(self.author_lbl)
        
        header_layout.addLayout(title_box, 1)

        # Version badge on top right
        versions = data.get("versions") or []
        v_text = versions[-1] if versions else "Unknown"
        self.version = QLabel(f"v {v_text}", self)
        self.version.setWindowFlags(Qt.Widget)
        self.version.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.version.setObjectName("CardVersionBadge")
        self.version.setStyleSheet("background: rgba(139, 92, 246, 0.18); color: #C084FC; border: 1px solid rgba(139, 92, 246, 0.32); border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700;")
        self.version.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.version)
        
        self.update_btn = QPushButton("Update" if en else "Güncelle", self)
        self.update_btn.setWindowFlags(Qt.Widget)
        self.update_btn.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F59E0B, stop:1 #D97706); color: white; font-weight: 700; border: none; border-radius: 4px; padding: 2px 6px; font-size: 10px;")
        self.update_btn.setVisible(False)
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(lambda checked=False: self.update_clicked.emit(self.data) if hasattr(self, 'update_clicked') else None)
        header_layout.addWidget(self.update_btn)

        layout.addLayout(header_layout)
        
        # Desc
        desc_text = (data.get("description") or "").strip()
        self.desc = QLabel(desc_text, self)
        self.desc.setWindowFlags(Qt.Widget)
        self.desc.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.desc.setObjectName("CardSubtitle")
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("font-size: 11px; color: #94A3B8; line-height: 1.3; background: transparent; border: none;")
        self.desc.setMaximumHeight(28)
        layout.addWidget(self.desc)
        
        # Stats & Tags Row (Bottom)
        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        stats_row.setAlignment(Qt.AlignVCenter)
        
        downloads = data.get("downloads") or 0
        self.downloads_lbl = QLabel(format_number(downloads), self)
        self.downloads_lbl.setToolTip("Downloads" if en else "İndirme")
        self.downloads_lbl.setWindowFlags(Qt.Widget)
        self.downloads_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.downloads_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 500; background: transparent; border: none;")
        stats_row.addWidget(self.downloads_lbl)

        sep1 = QLabel("•", self)
        sep1.setStyleSheet("color: #475569; font-size: 10px; background: transparent; border: none;")
        stats_row.addWidget(sep1)
        
        follows = data.get("follows") or 0
        self.follows_lbl = QLabel(format_number(follows), self)
        self.follows_lbl.setToolTip("Followers" if en else "Takipçi")
        self.follows_lbl.setWindowFlags(Qt.Widget)
        self.follows_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.follows_lbl.setStyleSheet("color: #FBBF24; font-size: 11px; font-weight: 500; background: transparent; border: none;")
        stats_row.addWidget(self.follows_lbl)

        # Loader / Category pill
        categories = data.get("categories") or []
        cat_name = ""
        for cat in categories:
            if cat.lower() not in ("modpack", "minecraft"):
                cat_name = cat.capitalize()
                break
        if not cat_name and data.get("client_side") == "required":
            cat_name = "Client"
        if cat_name:
            sep2 = QLabel("•", self)
            sep2.setStyleSheet("color: #475569; font-size: 10px; background: transparent; border: none;")
            stats_row.addWidget(sep2)
            self.cat_pill = QLabel(cat_name, self)
            self.cat_pill.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 500; background: transparent; border: none;")
            self.cat_pills.append(self.cat_pill)
            stats_row.addWidget(self.cat_pill)

        stats_row.addStretch()
        layout.addLayout(stats_row)
        
        # Load Icon
        icon_url = data.get("icon_url")
        if icon_url:
            if icon_url in _PIXMAP_CACHE:
                self.set_icon(_PIXMAP_CACHE[icon_url])
            elif icon_url in _ICON_CACHE:
                self.set_icon(_ICON_CACHE[icon_url])
            elif icon_url in _IN_FLIGHT_REQUESTS:
                import weakref
                _IN_FLIGHT_REQUESTS[icon_url].append(weakref.ref(self))
            else:
                import weakref
                _IN_FLIGHT_REQUESTS[icon_url] = [weakref.ref(self)]
                _PENDING_ICON_QUEUE.append(icon_url)
                _process_icon_queue()
            
        self._update_style()

    def set_language(self, lang="tr"):
        self.lang = lang
        en = lang == "en"
        if hasattr(self, "update_btn"):
            self.update_btn.setText("Update" if en else "Güncelle")
        if hasattr(self, "title") and not self.data.get("title"):
            self.title.setText("Untitled" if en else "İsimsiz")

    def _update_style(self):
        if self.is_selected:
            base = """
                #ModpackCard {
                    background-color: #2B1D42;
                    border: 2px solid #C084FC;
                    border-radius: 6px;
                }
                #ModpackCard:hover {
                    background-color: #2B1D42;
                    border: 2px solid #C084FC;
                }
                QLabel {
                    background: transparent;
                    border: none;
                }
            """
        else:
            base = """
                #ModpackCard {
                    background-color: #1A1A1E;
                    border: 1px solid #282830;
                    border-top: 1px solid #34343E;
                    border-bottom: 2px solid #141416;
                    border-radius: 6px;
                }
                #ModpackCard:hover {
                    background-color: #212128;
                    border: 1px solid #3C3C48;
                    border-top: 1px solid #484856;
                    border-bottom: 2px solid #141416;
                }
                QLabel {
                    background: transparent;
                    border: none;
                }
            """
        theme_key = getattr(self, "_active_theme", None)
        if not theme_key:
            try:
                win = self.window()
                if win and hasattr(win, "settings") and isinstance(win.settings, dict):
                    theme_key = win.settings.get("theme", "electric_amethyst")
            except Exception:
                theme_key = "electric_amethyst"

        if theme_key and theme_key != "electric_amethyst":
            import theme_manager
            themed = theme_manager.generate_theme_qss(base, theme_key)
            self.setStyleSheet(themed)
        else:
            self.setStyleSheet(base)
        if getattr(self, "_last_badged_theme", None) != (theme_key or "electric_amethyst"):
            self._update_accent_badges(theme_key or "electric_amethyst")
            self._last_badged_theme = theme_key or "electric_amethyst"

    def _update_accent_badges(self, theme_key="electric_amethyst"):
        try:
            import theme_manager
            t = theme_manager.get_theme(theme_key)
            r, g, b = t["rgb"]
            glow = t["glow"]
            prim_light = t["primary_light"]
            if hasattr(self, "icon_lbl") and self.icon_lbl:
                self.icon_lbl.setStyleSheet(f"background-color: rgba({r}, {g}, {b}, 0.15); border: 1px solid rgba({r}, {g}, {b}, 0.25); border-radius: 10px;")
            if hasattr(self, "version") and self.version:
                self.version.setStyleSheet(f"background: rgba({r}, {g}, {b}, 0.18); color: {glow}; border: 1px solid rgba({r}, {g}, {b}, 0.3); border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 700;")
            if hasattr(self, "cat_pills") and self.cat_pills:
                for pill in self.cat_pills:
                    pill.setStyleSheet(f"color: {prim_light}; font-size: 10px; font-weight: 600; background: rgba({r}, {g}, {b}, 0.15); border: 1px solid rgba({r}, {g}, {b}, 0.25); border-radius: 5px; padding: 1px 5px;")
        except Exception:
            pass

    def set_theme(self, theme_key: str):
        self._active_theme = theme_key
        self._update_style()

    def enterEvent(self, event):
        self.is_hovered = True
        try:
            super().enterEvent(event)
        except Exception:
            pass

    def leaveEvent(self, event):
        self.is_hovered = False
        try:
            super().leaveEvent(event)
        except Exception:
            pass

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()
            
    def set_icon(self, data_or_pixmap):
        try:
            if hasattr(self, 'icon_lbl') and self.icon_lbl:
                if isinstance(data_or_pixmap, QPixmap):
                    self.icon_lbl.setPixmap(data_or_pixmap)
                elif isinstance(data_or_pixmap, (bytes, bytearray)):
                    pixmap = QPixmap()
                    pixmap.loadFromData(data_or_pixmap)
                    scaled = pixmap.scaled(self.icon_lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.icon_lbl.setPixmap(scaled)
                    url = (getattr(self, "data", {}) or {}).get("icon_url")
                    if url:
                        if len(_PIXMAP_CACHE) >= _MAX_CACHE_SIZE:
                            first_k = next(iter(_PIXMAP_CACHE), None)
                            if first_k:
                                _PIXMAP_CACHE.pop(first_k, None)
                        _PIXMAP_CACHE[url] = scaled
        except Exception:
            pass

    def cleanup(self):
        self.img_thread = None

    @classmethod
    def cleanup_all_threads(cls):
        global _PENDING_ICON_QUEUE, _IN_FLIGHT_REQUESTS
        _PENDING_ICON_QUEUE.clear()
        _IN_FLIGHT_REQUESTS.clear()
        for th in list(cls._active_threads):
            try:
                if th.isRunning():
                    th.quit()
                    th.wait(500)
                    if th.isRunning():
                        th.terminate()
                        th.wait(200)
            except Exception:
                pass
        cls._active_threads.clear()

    def mousePressEvent(self, event):
        self.clicked.emit(self.data)
        super().mousePressEvent(event)

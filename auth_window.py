import sys
import os
import re
import uuid
import urllib.parse
from typing import Optional

import requests
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTabWidget, QWidget, QMessageBox, QApplication,
    QFrame
)
from PySide6.QtCore import QUrl, Qt, QThread, Signal, QTimer
from PySide6.QtGui import QDesktopServices, QPixmap, QImage
import minecraft_launcher_lib

from auth_vault import AuthenticationVault

CLIENT_ID = "00000000402b5328"
REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"
OFFICIAL_AUTH_URL = (
    f"https://login.live.com/oauth20_authorize.srf"
    f"?client_id={CLIENT_ID}"
    f"&response_type=code"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    f"&scope=service::user.auth.xboxlive.com::MBI_SSL"
)


def needs_rebind_token(data: str) -> bool:
    """Returns True if token is plaintext, contains a legacy portable suffix, or its DPAPI layer cannot be decrypted."""
    return AuthenticationVault.needs_rebind(data)


def protect_token(token: str) -> str:
    """Encrypts token strictly using Windows DPAPI."""
    return AuthenticationVault.encrypt_secret(token)


def unprotect_token(data: str) -> str:
    """Decrypts token strictly via Windows DPAPI; returns empty string if bound to another machine/user."""
    return AuthenticationVault.decrypt_secret(data)


def extract_auth_code(text: str) -> Optional[str]:
    """Extract authorization code from a redirect URL or raw code string."""
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    if "code=" in s:
        m = re.search(r"[?&#]code=([a-zA-Z0-9_\-\.]+)", s)
        if m:
            return m.group(1)
    if s.startswith("M.") or s.startswith("M_") or (len(s) >= 16 and " " not in s and "/" not in s and ":" not in s):
        return s
    return None


def complete_official_login(auth_code: str) -> dict:
    """Exchange auth_code from login.live.com (client_id 00000000402b5328) for full Minecraft profile."""
    token_url = "https://login.live.com/oauth20_token.srf"
    token_data = {
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "scope": "service::user.auth.xboxlive.com::MBI_SSL",
    }
    r = requests.post(token_url, data=token_data, timeout=15)
    if r.status_code != 200:
        err = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        desc = err.get("error_description") or err.get("error") or f"HTTP {r.status_code}"
        raise RuntimeError(f"Microsoft token error: {desc}")
    ms_tokens = r.json()
    ms_access_token = ms_tokens["access_token"]
    ms_refresh_token = ms_tokens.get("refresh_token")

    # Xbox Live authenticate
    xbl_res = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(ms_access_token)
    if not xbl_res or "Token" not in xbl_res:
        raise RuntimeError("Xbox Live authentication failed")
    xbl_token = xbl_res["Token"]
    userhash = xbl_res["DisplayClaims"]["xui"][0]["uhs"]

    # XSTS authorize
    xsts_res = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl_token)
    if not xsts_res or "Token" not in xsts_res:
        xsts_err = xsts_res.get("XErr", "Unknown XSTS error") if isinstance(xsts_res, dict) else "Failed"
        raise RuntimeError(f"XSTS authentication error ({xsts_err})")
    xsts_token = xsts_res["Token"]

    # Minecraft services login
    mc_auth = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(userhash, xsts_token)
    if not mc_auth or "access_token" not in mc_auth:
        raise RuntimeError("Minecraft services authentication failed (Account might not own Minecraft Java Edition)")
    mc_token = mc_auth["access_token"]

    # Fetch player profile
    profile = minecraft_launcher_lib.microsoft_account.get_profile(mc_token)
    if not profile or (isinstance(profile, dict) and profile.get("error") == "NOT_FOUND"):
        raise RuntimeError("Account does not own Minecraft Java Edition")

    account_data = dict(profile)
    account_data["type"] = "ms"
    account_data["access_token"] = mc_token
    account_data["refresh_token"] = ms_refresh_token
    return account_data


def create_offline_account(username: str) -> dict:
    """Generate a standard offline Minecraft account using Mojang deterministic offline UUID."""
    name = (username or "").strip()
    if not name:
        name = "Player"
    offline_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{name}")).replace("-", "")
    return {
        "type": "offline",
        "name": name,
        "id": offline_uuid,
        "access_token": "0",
        "refresh_token": None,
        "skins": [{
            "id": offline_uuid,
            "state": "ACTIVE",
            "url": f"https://minotar.net/skin/{name}",
            "variant": "CLASSIC",
            "alias": "STEVE"
        }],
        "capes": []
    }


class LoginWorkerThread(QThread):
    finished_login = Signal(bool, object, str)

    def __init__(self, *args, parent=None, **kwargs):
        super().__init__(parent)
        if len(args) >= 3:
            self.client_id = args[0]
            self.redirect_uri = args[1]
            self.auth_code = args[2]
            self.code_verifier = args[3] if len(args) > 3 else None
        elif len(args) == 1:
            self.auth_code = args[0]
            self.client_id = CLIENT_ID
            self.redirect_uri = REDIRECT_URI
            self.code_verifier = None
        else:
            self.auth_code = kwargs.get("auth_code", "")
            self.client_id = kwargs.get("client_id", CLIENT_ID)
            self.redirect_uri = kwargs.get("redirect_uri", REDIRECT_URI)
            self.code_verifier = kwargs.get("code_verifier")

    def run(self):
        try:
            if self.client_id != CLIENT_ID:
                data = minecraft_launcher_lib.microsoft_account.complete_login(
                    self.client_id, None, self.redirect_uri, self.auth_code, self.code_verifier
                )
            else:
                data = complete_official_login(self.auth_code)
            self.finished_login.emit(True, data, "")
        except Exception as e:
            self.finished_login.emit(False, None, str(e))


class SkinPreviewThread(QThread):
    preview_loaded = Signal(str, bytes)

    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self.username = username

    def run(self):
        if not self.username or len(self.username) < 3:
            return
        url = f"https://minotar.net/helm/{self.username}/64.png"
        try:
            resp = requests.get(url, timeout=3, headers={"User-Agent": "VegaLauncher/2.0.4"})
            if resp.status_code == 200 and resp.content:
                self.preview_loaded.emit(self.username, resp.content)
        except Exception:
            pass


class AccountLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.login_data = None
        self._is_logging_in = False
        self._login_worker = None
        self._preview_worker = None
        self._browser_opened = False
        self._last_processed_code = ""

        lang = "tr"
        p = parent
        while p:
            if hasattr(p, "settings") and isinstance(p.settings, dict):
                lang = p.settings.get("language", "tr")
                break
            if hasattr(p, "lang") and isinstance(p.lang, str):
                lang = p.lang
                break
            p = getattr(p, "parent", lambda: None)()
        self.lang = lang
        en = (self.lang == "en")

        self.setWindowTitle("Sign in with Microsoft" if en else "Microsoft ile Giriş Yap")
        self.setFixedSize(520, 480)
        self.setStyleSheet("""
            QDialog {
                background-color: #12131C;
                color: #F8FAFC;
            }
            QTabWidget::pane {
                border: 1px solid #2D3149;
                background-color: #181926;
                border-radius: 8px;
                padding: 12px;
            }
            QTabBar::tab {
                background-color: #1A1C29;
                color: #94A3B8;
                border: 1px solid #2D3149;
                padding: 8px 18px;
                font-weight: 600;
                font-size: 13px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #24273A;
                color: #C084FC;
                border-bottom: 2px solid #A855F7;
            }
            QLineEdit {
                background-color: #12131C;
                border: 1.5px solid #2D3149;
                border-radius: 6px;
                color: #FFFFFF;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1.5px solid #A855F7;
            }
            QPushButton {
                font-weight: 700;
                font-size: 13px;
                border-radius: 6px;
                padding: 10px 16px;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Tabs
        self.tabs = QTabWidget(self)
        main_layout.addWidget(self.tabs)

        # 1. Tab: Microsoft
        self.tab_ms = QWidget()
        self._setup_microsoft_tab(en)
        self.tabs.addTab(self.tab_ms, "🌐 " + ("Microsoft Account" if en else "Microsoft Hesabı"))

        # 2. Tab: Offline
        self.tab_offline = QWidget()
        self._setup_offline_tab(en)
        self.tabs.addTab(self.tab_offline, "🎮 " + ("Offline Player" if en else "Çevrimdışı Oyuncu"))

        # Overlay loading label
        self.lbl_loading = QLabel(
            "Completing login, please wait..." if en else
            "Giriş tamamlanıyor, lütfen bekleyin...",
            self
        )
        self.loading_label = self.lbl_loading
        self.lbl_loading.setAlignment(Qt.AlignCenter)
        self.lbl_loading.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: bold;
                color: #FFFFFF;
                background-color: rgba(18, 19, 28, 0.95);
                border: 1px solid #7C3AED;
                border-radius: 8px;
                padding: 24px;
            }
        """)
        self.lbl_loading.hide()
        main_layout.addWidget(self.lbl_loading)

        # Clipboard poll timer
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.setInterval(400)
        self._clipboard_timer.timeout.connect(self._check_clipboard)

    def _setup_microsoft_tab(self, en: bool):
        lay = QVBoxLayout(self.tab_ms)
        lay.setSpacing(12)
        lay.setContentsMargins(8, 8, 8, 8)

        lbl_desc = QLabel(
            "<b>Official Minecraft & Microsoft Sign-In:</b><br>"
            "Click the button below to sign in via your web browser. No third-party apps (Prism etc.) will be shown.<br><br>"
            "<i>Once you log in, simply copy (Ctrl+C) the blank page's address bar. Vega Launcher will automatically detect it!</i>"
            if en else
            "<b>Resmi Minecraft & Microsoft Girişi:</b><br>"
            "Aşağıdaki butona tıklayarak tarayıcınızda resmi Microsoft sayfasından giriş yapın.<br><br>"
            "<i>Giriş yaptıktan sonra açılan sayfanın adresini kopyalamanız (Ctrl+C) yeterlidir. Başlatıcı linki otomatik algılayacaktır!</i>"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #CBD5E1; font-size: 12px; line-height: 1.4;")
        lay.addWidget(lbl_desc)

        # Step 1: Open browser button
        self.btn_open_browser = QPushButton("🚀 " + ("1. Open Sign-In in Browser" if en else "1. Tarayıcıda Giriş Sayfasını Aç"))
        self.btn_open_browser.setCursor(Qt.PointingHandCursor)
        self.btn_open_browser.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED;
                color: #FFFFFF;
                border: none;
            }
            QPushButton:hover {
                background-color: #8B5CF6;
            }
        """)
        self.btn_open_browser.clicked.connect(self._on_open_browser_clicked)
        lay.addWidget(self.btn_open_browser)

        # Status badge
        self.lbl_ms_status = QLabel("Ready. Click button above to open browser." if en else "Hazır. Tarayıcıyı açmak için butona tıklayın.")
        self.lbl_ms_status.setAlignment(Qt.AlignCenter)
        self.lbl_ms_status.setStyleSheet("""
            QLabel {
                background-color: #12131C;
                border: 1px dashed #3B4261;
                border-radius: 6px;
                padding: 10px;
                color: #94A3B8;
                font-size: 12px;
                font-weight: 600;
            }
        """)
        lay.addWidget(self.lbl_ms_status)

        # Manual entry section
        lbl_manual = QLabel("Manual fallback:" if en else "Manuel yapıştırma:")
        lbl_manual.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 600; margin-top: 6px;")
        lay.addWidget(lbl_manual)

        self.txt_code = QLineEdit()
        self.txt_code.setPlaceholderText("https://login.live.com/oauth20_desktop.srf?code=..." if en else "https://login.live.com/... linkini veya kodunu buraya yapıştırın...")
        lay.addWidget(self.txt_code)

        btn_row = QHBoxLayout()
        self.btn_paste = QPushButton("📋 " + ("Paste from Clipboard" if en else "Panodan Yapıştır"))
        self.btn_paste.setCursor(Qt.PointingHandCursor)
        self.btn_paste.setStyleSheet("background-color: #2D3149; color: #E2E8F0;")
        self.btn_paste.clicked.connect(self._on_paste_clicked)
        btn_row.addWidget(self.btn_paste)

        self.btn_submit_code = QPushButton("✓ " + ("Complete Login" if en else "Girişi Tamamla"))
        self.btn_submit_code.setCursor(Qt.PointingHandCursor)
        self.btn_submit_code.setStyleSheet("background-color: #059669; color: #FFFFFF;")
        self.btn_submit_code.clicked.connect(self._on_manual_submit_clicked)
        btn_row.addWidget(self.btn_submit_code)

        lay.addLayout(btn_row)
        lay.addStretch()

    def _setup_offline_tab(self, en: bool):
        lay = QVBoxLayout(self.tab_offline)
        lay.setSpacing(14)
        lay.setContentsMargins(8, 8, 8, 8)

        lbl_desc = QLabel(
            "<b>Offline Player Profile:</b><br>"
            "Play offline without a Microsoft account. You only need a nickname.<br>"
            "<i>Note: Offline accounts work on singleplayer worlds and servers with online-mode=false.</i>"
            if en else
            "<b>Çevrimdışı Oyuncu Profili:</b><br>"
            "Microsoft hesabı olmadan, yalnızca bir takma ad belirleyerek hemen oynayın.<br>"
            "<i>Not: Çevrimdışı hesaplar tek oyunculu dünyalarda ve çevrimdışı (online-mode=false) sunucularda çalışır.</i>"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #CBD5E1; font-size: 12px; line-height: 1.4;")
        lay.addWidget(lbl_desc)

        # Avatar & Nickname card
        card_frame = QFrame()
        card_frame.setStyleSheet("background-color: #12131C; border: 1px solid #2D3149; border-radius: 8px; padding: 12px;")
        card_lay = QHBoxLayout(card_frame)
        card_lay.setSpacing(16)

        # Avatar Preview Image
        self.lbl_avatar = QLabel()
        self.lbl_avatar.setFixedSize(64, 64)
        self.lbl_avatar.setStyleSheet("background-color: #1E2030; border: 1px solid #434969; border-radius: 6px;")
        self.lbl_avatar.setAlignment(Qt.AlignCenter)
        self.lbl_avatar.setText("👤")
        card_lay.addWidget(self.lbl_avatar)

        # Nickname inputs
        input_lay = QVBoxLayout()
        input_lay.setSpacing(6)
        lbl_nick = QLabel("Player Nickname:" if en else "Oyuncu Adı (Nickname):")
        lbl_nick.setStyleSheet("color: #E2E8F0; font-weight: 700; font-size: 12px;")
        input_lay.addWidget(lbl_nick)

        self.txt_offline_name = QLineEdit()
        self.txt_offline_name.setMaxLength(16)
        self.txt_offline_name.setPlaceholderText("Steve, Alex, ProGamer..." if en else "örn: Steve, Alex, Oyuncu123...")
        self.txt_offline_name.textChanged.connect(self._on_offline_name_changed)
        input_lay.addWidget(self.txt_offline_name)

        card_lay.addLayout(input_lay)
        lay.addWidget(card_frame)

        # Offline Submit Button
        self.btn_offline_submit = QPushButton("✓ " + ("Play Offline with this Name" if en else "Bu İsimle Çevrimdışı Başlat"))
        self.btn_offline_submit.setCursor(Qt.PointingHandCursor)
        self.btn_offline_submit.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #3B82F6;
            }
        """)
        self.btn_offline_submit.clicked.connect(self._on_offline_submit_clicked)
        lay.addWidget(self.btn_offline_submit)

        lay.addStretch()

        # Avatar debounce timer
        self._skin_timer = QTimer(self)
        self._skin_timer.setSingleShot(True)
        self._skin_timer.setInterval(500)
        self._skin_timer.timeout.connect(self._fetch_avatar_preview)

    def _on_open_browser_clicked(self):
        en = (self.lang == "en")
        self._browser_opened = True
        QDesktopServices.openUrl(QUrl(OFFICIAL_AUTH_URL))
        self.lbl_ms_status.setText(
            "⏳ Listening to clipboard: Copy (Ctrl+C) the blank page URL after login..." if en else
            "⏳ Pano dinleniyor: Giriş sonrası tarayıcıdaki linki kopyalayın (Ctrl+C)..."
        )
        self.lbl_ms_status.setStyleSheet("""
            QLabel {
                background-color: #1E1B4B;
                border: 1px solid #8B5CF6;
                border-radius: 6px;
                padding: 10px;
                color: #C084FC;
                font-size: 12px;
                font-weight: 700;
            }
        """)
        self._clipboard_timer.start()

    def _check_clipboard(self):
        if self._is_logging_in or not self._browser_opened:
            return
        try:
            cb = QApplication.clipboard()
            text = cb.text().strip()
            if text and ("login.live.com" in text or "code=" in text):
                code = extract_auth_code(text)
                if code and code != self._last_processed_code:
                    self._last_processed_code = code
                    self.txt_code.setText(code)
                    self._start_login(code)
        except Exception:
            pass

    def _on_paste_clicked(self):
        cb = QApplication.clipboard()
        text = cb.text().strip()
        if text:
            self.txt_code.setText(text)
            code = extract_auth_code(text)
            if code:
                self._start_login(code)

    def _on_manual_submit_clicked(self):
        code = extract_auth_code(self.txt_code.text().strip())
        if not code:
            en = (self.lang == "en")
            QMessageBox.warning(
                self,
                "Invalid Code" if en else "Geçersiz Link/Kod",
                "Please enter a valid Microsoft authorization URL or code." if en else
                "Lütfen geçerli bir Microsoft giriş linki veya kodu yapıştırın."
            )
            return
        self._start_login(code)

    def _start_login(self, auth_code: str):
        if self._is_logging_in:
            return
        self._is_logging_in = True
        self._clipboard_timer.stop()

        self.tabs.hide()
        self.lbl_loading.show()

        self._login_worker = LoginWorkerThread(auth_code, parent=self)
        self._login_worker.finished_login.connect(self._on_login_finished)
        self._login_worker.start()

    def _on_login_finished(self, success: bool, data: object, error_msg: str):
        en = (self.lang == "en")
        self.lbl_loading.hide()
        self.tabs.show()
        self._is_logging_in = False

        if success and data:
            self.login_data = data
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Sign-In Error" if en else "Giriş Hatası",
                f"{'Login could not be completed:' if en else 'Giriş tamamlanamadı:'}\n{error_msg}"
            )
            self.lbl_ms_status.setText("Failed. Please try opening browser again." if en else "Başarısız. Lütfen tarayıcıyı tekrar açmayı deneyin.")

    def _on_offline_name_changed(self, text: str):
        self._skin_timer.start()

    def _fetch_avatar_preview(self):
        name = self.txt_offline_name.text().strip()
        if len(name) >= 3:
            if self._preview_worker and self._preview_worker.isRunning():
                try:
                    self._preview_worker.preview_loaded.disconnect()
                except Exception:
                    pass
                self._preview_worker.quit()
                self._preview_worker.wait(300)
            self._preview_worker = SkinPreviewThread(name, parent=self)
            self._preview_worker.preview_loaded.connect(self._on_avatar_loaded)
            self._preview_worker.start()

    def _on_avatar_loaded(self, username: str, image_bytes: bytes):
        if self.txt_offline_name.text().strip().lower() == username.lower():
            img = QImage()
            if img.loadFromData(image_bytes):
                pix = QPixmap.fromImage(img).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_avatar.setPixmap(pix)

    def _on_offline_submit_clicked(self):
        en = (self.lang == "en")
        name = self.txt_offline_name.text().strip()
        if not re.match(r"^[a-zA-Z0-9_]{3,16}$", name):
            QMessageBox.warning(
                self,
                "Invalid Username" if en else "Geçersiz Kullanıcı Adı",
                "Username must be 3-16 characters long and contain only letters, numbers, and underscores."
                if en else
                "Kullanıcı adı 3-16 karakter uzunluğunda olmalı, yalnızca harf, rakam ve alt çizgi (_) içermelidir."
            )
            return

        self.login_data = create_offline_account(name)
        self.accept()

    def _cleanup_worker(self):
        if hasattr(self, "_clipboard_timer") and self._clipboard_timer.isActive():
            self._clipboard_timer.stop()
        if hasattr(self, "_skin_timer") and self._skin_timer.isActive():
            self._skin_timer.stop()
        if self._preview_worker and self._preview_worker.isRunning():
            try:
                self._preview_worker.preview_loaded.disconnect()
            except Exception:
                pass
            self._preview_worker.quit()
            self._preview_worker.wait(500)
            self._preview_worker = None
        if self._login_worker and self._login_worker.isRunning():
            try:
                self._login_worker.finished_login.disconnect()
            except Exception:
                pass
            self._login_worker.quit()
            self._login_worker.wait(1000)
            self._login_worker = None

    def accept(self):
        self._cleanup_worker()
        super().accept()

    def reject(self):
        self._cleanup_worker()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_worker()
        super().closeEvent(event)

    def get_account_data(self):
        return self.login_data


# Backwards compatibility alias
MicrosoftLoginDialog = AccountLoginDialog

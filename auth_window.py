import sys
import os
import base64
import ctypes
from ctypes import wintypes
from urllib.parse import urlparse, parse_qs
from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox, QLabel
from PySide6.QtCore import QUrl, Qt, QThread, Signal
import minecraft_launcher_lib

CLIENT_ID = "00000000402b5328"
REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"

from auth_vault import AuthenticationVault

def _dpapi_decrypt_raw(dpapi_b64: str):
    if not dpapi_b64:
        return None
    dec = AuthenticationVault.decrypt_secret(f"dpapi:{dpapi_b64}")
    return dec if dec else None

def needs_rebind_token(data: str) -> bool:
    """Returns True if token is plaintext, contains a legacy portable suffix, or its DPAPI layer cannot be decrypted."""
    return AuthenticationVault.needs_rebind(data)

def protect_token(token: str) -> str:
    """Encrypts token strictly using Windows DPAPI."""
    return AuthenticationVault.encrypt_secret(token)

def unprotect_token(data: str) -> str:
    """Decrypts token strictly via Windows DPAPI; returns empty string if bound to another machine/user."""
    return AuthenticationVault.decrypt_secret(data)

class LoginWorkerThread(QThread):
    finished_login = Signal(bool, object, str)

    def __init__(self, client_id, redirect_uri, auth_code, code_verifier, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.auth_code = auth_code
        self.code_verifier = code_verifier

    def run(self):
        try:
            data = minecraft_launcher_lib.microsoft_account.complete_login(
                self.client_id, None, self.redirect_uri, self.auth_code, self.code_verifier
            )
            self.finished_login.emit(True, data, "")
        except Exception as e:
            self.finished_login.emit(False, None, str(e))

class MicrosoftLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.login_data = None
        self._is_logging_in = False
        self._login_worker = None

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
        self.resize(500, 600)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.loading_label = QLabel(
            "Completing login, please wait..." if en else "Giriş tamamlanıyor, lütfen bekleyin...",
            self
        )
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #FFFFFF; background-color: #1E1E2E; padding: 20px;")
        self.loading_label.hide()
        layout.addWidget(self.loading_label)

        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.browser = QWebEngineView()
        layout.addWidget(self.browser)
        
        self.browser.urlChanged.connect(self.on_url_changed)
        
        login_url, self.state, self.code_verifier = minecraft_launcher_lib.microsoft_account.get_secure_login_data(CLIENT_ID, REDIRECT_URI)
        self.browser.setUrl(QUrl(login_url))

    def _cleanup_worker(self):
        if self._login_worker and self._login_worker.isRunning():
            try:
                self._login_worker.finished_login.disconnect()
            except Exception:
                pass
            self._login_worker.quit()
            self._login_worker.wait(1000)

    def reject(self):
        self._cleanup_worker()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_worker()
        super().closeEvent(event)
        
    def on_url_changed(self, url: QUrl):
        if self._is_logging_in:
            return

        en = (self.lang == "en")
        url_str = url.toString()
        parsed = urlparse(url_str)
        params = parse_qs(parsed.query)
        if not params and parsed.fragment:
            params = parse_qs(parsed.fragment)

        # 1. OAuth hata veya iptal kontrolü
        if "error" in params or "error_description" in params:
            err_code = params.get("error", ["unknown"])[0]
            err_desc = params.get("error_description", [err_code])[0]
            if err_code == "access_denied":
                QMessageBox.information(
                    self,
                    "Login Cancelled" if en else "Giriş İptal Edildi",
                    "Microsoft sign-in was cancelled." if en else "Microsoft oturum açma işlemi iptal edildi."
                )
            else:
                QMessageBox.warning(
                    self,
                    "Login Error" if en else "Giriş Hatası",
                    f"{'Microsoft sign-in error' if en else 'Microsoft oturum açma hatası'} ({err_code}):\n{err_desc}"
                )
            self.reject()
            return

        # 2. Yetkilendirme kodu kontrolü
        if minecraft_launcher_lib.microsoft_account.url_contains_auth_code(url_str):
            try:
                auth_code = minecraft_launcher_lib.microsoft_account.parse_auth_code_url(url_str, self.state)
            except (AssertionError, KeyError, Exception) as e:
                QMessageBox.critical(
                    self,
                    "Error" if en else "Hata",
                    f"{'Could not resolve authorization code:' if en else 'Yetkilendirme kodu çözülemedi:'}\n{str(e)}"
                )
                self.reject()
                return

            if auth_code:
                self._is_logging_in = True
                self.browser.hide()
                self.loading_label.show()
                self._login_worker = LoginWorkerThread(CLIENT_ID, REDIRECT_URI, auth_code, self.code_verifier, parent=self)
                self._login_worker.finished_login.connect(self._on_login_finished)
                self._login_worker.start()
            else:
                QMessageBox.critical(
                    self,
                    "Error" if en else "Hata",
                    "Authorization code could not be retrieved." if en else "Yetkilendirme kodu alınamadı."
                )
                self.reject()
            return

        # 3. Yönlendirme URL'sine kodsuz ulaşıldıysa askıda bırakma
        if url_str.startswith(REDIRECT_URI):
            QMessageBox.warning(
                self,
                "Incomplete Login" if en else "Giriş Tamamlanamadı",
                "Authorization could not be completed or was cancelled." if en else "Yetkilendirme tamamlanamadı veya iptal edildi."
            )
            self.reject()

    def _on_login_finished(self, success, data, error_msg):
        en = (self.lang == "en")
        if success:
            self.login_data = data
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Error" if en else "Hata",
                f"{'Login could not be completed:' if en else 'Giriş tamamlanamadı:'}\n{error_msg}"
            )
            self.reject()

    def get_account_data(self):
        return self.login_data

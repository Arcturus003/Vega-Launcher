from urllib.parse import urlparse, parse_qs
from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QUrl
import minecraft_launcher_lib

CLIENT_ID = "00000000402b5328"
REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"

class MicrosoftLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Microsoft ile Giriş Yap")
        self.resize(500, 600)
        self.login_data = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.browser = QWebEngineView()
        layout.addWidget(self.browser)
        
        self.browser.urlChanged.connect(self.on_url_changed)
        
        login_url, self.state, self.code_verifier = minecraft_launcher_lib.microsoft_account.get_secure_login_data(CLIENT_ID, REDIRECT_URI)
        self.browser.setUrl(QUrl(login_url))
        
    def on_url_changed(self, url: QUrl):
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
                QMessageBox.information(self, "Giriş İptal Edildi", "Microsoft oturum açma işlemi iptal edildi.")
            else:
                QMessageBox.warning(self, "Giriş Hatası", f"Microsoft oturum açma hatası ({err_code}):\n{err_desc}")
            self.reject()
            return

        # 2. Yetkilendirme kodu kontrolü
        if minecraft_launcher_lib.microsoft_account.url_contains_auth_code(url_str):
            try:
                auth_code = minecraft_launcher_lib.microsoft_account.parse_auth_code_url(url_str, self.state)
            except (AssertionError, KeyError, Exception) as e:
                QMessageBox.critical(self, "Hata", f"Yetkilendirme kodu çözülemedi:\n{str(e)}")
                self.reject()
                return

            if auth_code:
                try:
                    self.login_data = minecraft_launcher_lib.microsoft_account.complete_login(CLIENT_ID, None, REDIRECT_URI, auth_code, self.code_verifier)
                    self.accept()
                except Exception as e:
                    QMessageBox.critical(self, "Hata", f"Giriş tamamlanamadı:\n{str(e)}")
                    self.reject()
            else:
                QMessageBox.critical(self, "Hata", "Yetkilendirme kodu alınamadı.")
                self.reject()
            return

        # 3. Yönlendirme URL'sine kodsuz ulaşıldıysa askıda bırakma
        if url_str.startswith(REDIRECT_URI):
            QMessageBox.warning(self, "Giriş Tamamlanamadı", "Yetkilendirme tamamlanamadı veya iptal edildi.")
            self.reject()

    def get_account_data(self):
        return self.login_data

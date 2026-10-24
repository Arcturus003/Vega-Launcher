"""GitHub Releases tabanli otomatik guncelleme.

Akis: arka planda (QThread) latest release sorgulanir -> surum yeniyse kullaniciya
sorulur -> .exe asset'i ilerleme ile indirilir -> Inno Setup sessiz modda
calistirilir -> uygulama kapanir. Setup bittikten sonra setup.iss [Run]
bolumu uygulamayi yeniden baslatir.
Cevrimdisi / rate-limit / herhangi bir hata durumunda sessizce hicbir sey yapmaz.
"""
import os
import re
import sys
import json
import tempfile
import urllib.request

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication

GITHUB_REPO = "Arcturus003/Vega-Launcher"
LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = "VegaLauncher-Updater"


def parse_version(text):
    """'v1.2.3' / '1.2' / '1.2.3-beta' -> (1, 2, 3). Gecersizse None."""
    if not text:
        return None
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(text))
    if not m:
        return None
    parts = [int(p) for p in m.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(remote, local):
    r, l = parse_version(remote), parse_version(local)
    if r is None or l is None:
        return False
    n = max(len(r), len(l))
    r = r + (0,) * (n - len(r))
    l = l + (0,) * (n - len(l))
    return r > l


def pick_installer_asset(release):
    """Release icinden kurulum .exe'sini sec (Setup iceren tercih edilir)."""
    assets = [a for a in (release.get("assets") or [])
              if str(a.get("name", "")).lower().endswith(".exe") and a.get("browser_download_url")]
    if not assets:
        return None
    for a in assets:
        if "setup" in a["name"].lower():
            return a
    return assets[0]


class UpdateCheckThread(QThread):
    update_available = Signal(str, str, str, int)  # tag, url, name, size
    no_update = Signal()
    check_failed = Signal(str)

    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.asset_digest = ""

    def run(self):
        try:
            req = urllib.request.Request(LATEST_URL, headers={
                "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                release = json.loads(resp.read().decode("utf-8"))
            if release.get("draft") or release.get("prerelease"):
                self.no_update.emit()
                return
            tag = release.get("tag_name", "")
            if not is_newer(tag, self.current_version):
                self.no_update.emit()
                return
            asset = pick_installer_asset(release)
            if not asset:
                self.no_update.emit()
                return
            digest = str(asset.get("digest") or "").strip()
            if not digest:
                body = release.get("body") or ""
                m = re.search(r'(?i)sha256[:\s=]+([a-f0-9]{64})', body)
                if m:
                    digest = f"sha256:{m.group(1).lower()}"
                else:
                    asset_name = asset.get("name", "").lower()
                    for other in release.get("assets", []):
                        o_name = other.get("name", "").lower()
                        if o_name in (f"{asset_name}.sha256", "sha256sums.txt", "checksums.txt"):
                            try:
                                d_req = urllib.request.Request(other["browser_download_url"], headers={"User-Agent": USER_AGENT})
                                with urllib.request.urlopen(d_req, timeout=5) as d_resp:
                                    txt = d_resp.read().decode("utf-8", errors="ignore")
                                    cm = re.search(r'\b([a-f0-9]{64})\b', txt, re.IGNORECASE)
                                    if cm:
                                        digest = f"sha256:{cm.group(1).lower()}"
                                        break
                            except Exception:
                                pass
            self.asset_digest = digest
            self.update_available.emit(tag, asset["browser_download_url"],
                                       asset["name"], int(asset.get("size") or 0))
        except Exception as e:  # offline, 403 rate limit, JSON hatasi...
            print(f"[Updater] Guncelleme kontrolu atlandi: {e}")
            self.check_failed.emit(str(e))


class UpdateDownloadThread(QThread):
    progress = Signal(int)            # 0-100, bilinmiyorsa -1
    download_finished = Signal(bool, str)  # basari, dosya yolu / hata mesaji

    def __init__(self, url, filename, parent=None, lang="tr", expected_digest=""):
        super().__init__(parent)
        self.url = url
        self.filename = os.path.basename(filename) or "VegaLauncher_Setup.exe"
        self.lang = lang
        self.expected_digest = str(expected_digest or "").strip()
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import hashlib
        en = self.lang == "en"
        temp_dir = tempfile.mkdtemp(prefix="vega_update_")
        dest = os.path.join(temp_dir, self.filename)
        part = dest + ".part"
        hasher = hashlib.sha256()
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    if self._cancel:
                        raise RuntimeError("Cancelled" if en else "Iptal edildi")
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    done += len(chunk)
                    self.progress.emit(int(done * 100 / total) if total else -1)
            if total and done != total:
                raise RuntimeError("Incomplete download" if en else "Indirme eksik kaldi")
            if self.expected_digest:
                expected_hex = self.expected_digest.split(":", 1)[1].strip().lower() if ":" in self.expected_digest else self.expected_digest.strip().lower()
                if expected_hex and hasher.hexdigest().lower() != expected_hex:
                    raise RuntimeError("Installer SHA-256 verification failed" if en else "Kurulum dosyası SHA-256 doğrulaması başarısız")
            if os.path.exists(dest):
                os.remove(dest)
            os.replace(part, dest)
            self.download_finished.emit(True, dest)
        except Exception as e:
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            self.download_finished.emit(False, str(e))


def launch_installer(path):
    """Kurulumu sessiz baslat. ShellExecute UAC yukseltmesini destekler."""
    args = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /SP-"
    if sys.platform == "win32":
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(None, "open", path, args, None, 1)
        return rc > 32
    return False


class AppUpdater(QObject):
    """Ana pencereye bagli guncelleyici. Thread referanslarini tutar."""

    def __init__(self, parent_window, current_version):
        super().__init__(parent_window if isinstance(parent_window, QObject) else None)
        self.window = parent_window
        self.current_version = current_version
        self._threads = []
        self._last_check_thread = None
        self._progress_dialog = None

    def _lang(self):
        if self.window and hasattr(self.window, "settings") and isinstance(self.window.settings, dict):
            return self.window.settings.get("language", "tr")
        return getattr(self.window, "lang", "tr")

    def _keep(self, t):
        self._threads.append(t)
        t.finished.connect(lambda t=t: self._threads.remove(t) if t in self._threads else None)

    def check(self, manual=False):
        if getattr(self, "_last_check_thread", None) and self._last_check_thread.isRunning():
            return False
        btn = getattr(self.window, "btn_check_updates", None) if self.window else None
        if btn and hasattr(btn, "setEnabled"):
            btn.setEnabled(False)
        t = UpdateCheckThread(self.current_version)
        self._last_check_thread = t
        if btn and hasattr(btn, "setEnabled"):
            t.finished.connect(lambda b=btn: b.setEnabled(True))
        t.update_available.connect(self._on_update_available)
        if manual:
            t.no_update.connect(lambda: QMessageBox.information(
                self.window,
                "Up to Date" if self._lang() == "en" else "Güncel",
                f"Vega Launcher is up to date! (Version: v{self.current_version})"
                if self._lang() == "en" else
                f"Vega Launcher güncel! (Sürüm: v{self.current_version})"
            ))
            t.check_failed.connect(lambda err: QMessageBox.warning(
                self.window,
                "Update Check" if self._lang() == "en" else "Güncelleme Kontrolü",
                f"Could not reach update server:\n{err}"
                if self._lang() == "en" else
                f"Güncelleme sunucusuna ulaşılamadı:\n{err}"
            ))
        self._keep(t)
        t.start()
        return True

    def _on_update_available(self, tag, url, name, size):
        lang = self._lang()
        en = lang == "en"
        size_txt = f" ({size / 1024 / 1024:.1f} MB)" if size else ""
        ans = QMessageBox.question(
            self.window,
            "Update" if en else "Güncelleme",
            (
                f"A new version is available ({tag}){size_txt}. Update now?\n\n"
                f"Current version: v{self.current_version}"
            ) if en else (
                f"Yeni sürüm var ({tag}){size_txt}. Şimdi güncellensin mi?\n\n"
                f"Mevcut sürüm: v{self.current_version}"
            ),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ans != QMessageBox.Yes:
            return
        dlg = QProgressDialog(
            "Downloading update..." if en else "Güncelleme indiriliyor...",
            "Cancel" if en else "İptal",
            0, 100, self.window
        )
        dlg.setWindowTitle("Vega Launcher Update" if en else "Vega Launcher Güncelleme")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        self._progress_dialog = dlg

        digest = getattr(getattr(self, "_last_check_thread", None), "asset_digest", "")
        t = UpdateDownloadThread(url, name, lang=lang, expected_digest=digest)
        t.progress.connect(self._on_progress)
        t.download_finished.connect(self._on_download_finished)
        dlg.canceled.connect(t.cancel)
        self._keep(t)
        t.start()
        dlg.show()

    def _on_progress(self, pct):
        dlg = self._progress_dialog
        if not dlg:
            return
        if pct < 0:
            dlg.setRange(0, 0)
        else:
            dlg.setRange(0, 100)
            dlg.setValue(pct)

    def _on_download_finished(self, ok, result):
        en = self._lang() == "en"
        dlg, self._progress_dialog = self._progress_dialog, None
        was_canceled = dlg.wasCanceled() if dlg else False
        if dlg:
            dlg.close()
        if not ok:
            if not was_canceled:
                QMessageBox.warning(
                    self.window,
                    "Update" if en else "Güncelleme",
                    f"Could not download update:\n{result}" if en else f"Güncelleme indirilemedi:\n{result}"
                )
            return
        if not launch_installer(result):
            QMessageBox.warning(
                self.window,
                "Update" if en else "Güncelleme",
                f"Could not start installer. You can run it manually:\n{result}"
                if en else
                f"Kurulum başlatılamadı. Elle çalıştırabilirsiniz:\n{result}"
            )
            return
        # Kurulum dosyalari degistirebilsin diye uygulamayi kapat.
        self.window.close()
        QApplication.instance().quit()

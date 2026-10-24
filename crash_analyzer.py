from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import requests

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


@dataclass
class CrashReport:
    exit_code: int
    title: str
    severity: str
    diagnosis: str
    suggested_action: str
    culprit_mod: Optional[str] = None
    culprit_file: Optional[str] = None
    culprit_path: Optional[str] = None
    can_auto_fix: bool = False
    raw_log: str = ""
    log_file_path: Optional[str] = None
    mclogs_url: Optional[str] = None


class CrashAnalyzer:
    """
    Intelligent AST & log signature diagnostic engine for Minecraft crashes.
    Parses crash-reports, latest.log, and JVM logs to pinpoint conflicting
    mods, missing dependencies, Java version mismatches, and memory exhaustion.
    """

    JAVA_CLASS_VERSION_MAP = {
        "65.0": "Java 21",
        "61.0": "Java 17",
        "60.0": "Java 16",
        "52.0": "Java 8",
    }

    @classmethod
    def find_latest_crash_file(
        cls,
        profile_root: str | Path,
        prefer_crash: bool = False,
    ) -> Optional[tuple[str, bool]]:
        if not profile_root:
            return None
        root = Path(profile_root)
        if not root.exists():
            return None

        # 1. Check crash-reports/ directory
        crash_dir = root / "crash-reports"
        latest_crash = None
        if crash_dir.is_dir():
            files = [f for f in crash_dir.iterdir() if f.is_file() and f.suffix in (".txt", ".log")]
            if files:
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                latest_crash = str(files[0])

        # 2. Check logs/latest.log
        latest_log = root / "logs" / "latest.log"

        # 3. Check hs_err_pid*.log
        hs_errs = list(root.glob("hs_err_pid*.log"))
        if hs_errs:
            hs_errs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return str(hs_errs[0]), True

        if latest_crash:
            if (
                prefer_crash
                or not latest_log.is_file()
                or os.path.getmtime(latest_crash) >= os.path.getmtime(str(latest_log)) - 10
            ):
                return latest_crash, True

        if latest_log.is_file():
            return str(latest_log), False

        if latest_crash:
            return latest_crash, True

        return None

    @classmethod
    def analyze_profile(
        cls,
        profile_root: str | Path,
        exit_code: int = 1,
        lang: str = "tr",
    ) -> CrashReport:
        found = cls.find_latest_crash_file(profile_root, prefer_crash=(exit_code != 0))

        if not found:
            en = lang == "en"
            return CrashReport(
                exit_code=exit_code,
                title="Unknown Crash" if en else "Bilinmeyen Çökme",
                severity="ERROR",
                diagnosis=(
                    f"Game process exited with non-zero code {exit_code}, but no crash report or log was created."
                    if en else
                    f"Oyun {exit_code} kodu ile sonlandı, ancak profil dizininde henüz log veya kaza raporu oluşmadı."
                ),
                suggested_action=(
                    "Verify system memory and Java arguments."
                    if en else
                    "Sistem belleğini ve Java başlatma parametrelerini kontrol edin."
                ),
                raw_log="",
            )

        log_path, is_crash = found
        try:
            file_size = os.path.getsize(log_path)
            buffer_size = min(file_size, 350000)
            with open(log_path, "rb") as f:
                if file_size > buffer_size:
                    f.seek(file_size - buffer_size)
                raw_bytes = f.read()
            text = raw_bytes.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            content = "".join(lines[-600:])
        except Exception as e:
            content = f"Error reading log file: {e}"

        return cls.analyze_text(
            content=content,
            exit_code=exit_code,
            profile_root=profile_root,
            log_file_path=log_path,
            lang=lang,
        )

    @classmethod
    def analyze_text(
        cls,
        content: str,
        exit_code: int = 1,
        profile_root: Optional[str | Path] = None,
        log_file_path: Optional[str] = None,
        lang: str = "tr",
    ) -> CrashReport:
        en = lang == "en"
        mods_dir = Path(profile_root) / "mods" if profile_root else None
        installed_jars = []
        if mods_dir and mods_dir.is_dir():
            installed_jars = [f.name for f in mods_dir.iterdir() if f.is_file() and f.suffix == ".jar"]

        def _resolve_culprit_jar(hint: str) -> Optional[tuple[str, str]]:
            if not mods_dir or not hint:
                return None
            hint_clean = re.sub(r'[\-_.]mixins?.*|\.jar$', '', hint.lower()).strip()
            for jar_name in installed_jars:
                if hint_clean and hint_clean in jar_name.lower():
                    return jar_name, str(mods_dir / jar_name)
            return None

        # 1. OutOfMemoryError
        if "OutOfMemoryError" in content or "Java heap space" in content or "GC overhead limit exceeded" in content:
            return CrashReport(
                exit_code=exit_code,
                title="Out of Memory (RAM)" if en else "Bellek (RAM) Yetersizliği",
                severity="CRITICAL",
                diagnosis=(
                    "The JVM ran out of heap memory. Minecraft exhausted all allocated RAM."
                    if en else
                    "Java Sanal Makinesi (JVM) bellek sınırına ulaştı (`OutOfMemoryError`). Minecraft tahsis edilen RAM miktarını tüketti."
                ),
                suggested_action=(
                    "Increase allocated RAM to 6 GB or 8 GB in Launcher Settings or Profile Edit."
                    if en else
                    "Ayarlar veya Profil Düzenle bölümünden tahsis edilen RAM miktarını 6 GB veya 8 GB'a yükseltin."
                ),
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 2. UnsupportedClassVersionError (Java Version Mismatch)
        class_ver_match = re.search(r"class file version (\d+\.\d+)", content)
        if "UnsupportedClassVersionError" in content or class_ver_match:
            target_class = class_ver_match.group(1) if class_ver_match else "higher"
            req_java = cls.JAVA_CLASS_VERSION_MAP.get(target_class, "Java 17 / 21")
            return CrashReport(
                exit_code=exit_code,
                title="Incompatible Java Version" if en else "Uyumsuz Java Sürümü",
                severity="CRITICAL",
                diagnosis=(
                    f"A mod or Minecraft version was compiled for a newer runtime (class version {target_class}). Requires {req_java}."
                    if en else
                    f"Bir mod veya Minecraft sürümü daha yeni bir Java ile derlenmiş (sürüm {target_class}). Bu oyun için {req_java} gereklidir."
                ),
                suggested_action=(
                    f"Install and select {req_java} in Launcher Settings."
                    if en else
                    f"Ayarlar menüsünden {req_java} seçin veya sisteminize {req_java} kurun."
                ),
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 3. Mixin Conflict / Crash
        if "MixinApplyError" in content or "MixinTransformerError" in content or "MixinPrepareError" in content:
            mixin_json_match = re.search(r"([a-zA-Z0-9_\-]+?)(?:\.mixins?\.json)", content, re.IGNORECASE)
            fallback_match = re.search(r"(?:MixinTransformerError|MixinApplyError|MixinPrepareError).*?(?:from|into|in)\s+([a-zA-Z0-9_\-\.]+)", content)
            hint = mixin_json_match.group(1) if mixin_json_match else (fallback_match.group(1) if fallback_match else "")
            hint = re.sub(r"^(?:mixins?\.)", "", hint)
            culprit_info = _resolve_culprit_jar(hint)
            culprit_file = culprit_info[0] if culprit_info else (hint if hint else None)
            culprit_path = culprit_info[1] if culprit_info else None
            can_fix = bool(culprit_path and os.path.exists(culprit_path))

            mod_name = culprit_file or (hint if hint else "Unknown Mod")
            return CrashReport(
                exit_code=exit_code,
                title=f"Mixin Conflict: {mod_name}" if en else f"Mixin Mod Çakışması: {mod_name}",
                severity="CRITICAL",
                diagnosis=(
                    f"Mixin transformation failed caused by '{mod_name}'. The mod attempted to patch bytecode in an incompatible manner."
                    if en else
                    f"'{mod_name}' modunun sebep olduğu Mixin çakışması tespit edildi. Mod oyun kodunu enjekte ederken başka bir modla çakıştı."
                ),
                suggested_action=(
                    f"Disable or update '{mod_name}'. You can click the button below to quarantine it."
                    if en else
                    f"'{mod_name}' modunu devre dışı bırakın veya güncelleyin. Aşağıdaki butona tıklayarak modu otomatik olarak kapatabilirsiniz."
                ),
                culprit_mod=mod_name,
                culprit_file=culprit_file,
                culprit_path=culprit_path,
                can_auto_fix=can_fix,
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 4. Missing Mandatory Dependencies
        dep_match = re.search(r"requires\s+([a-zA-Z0-9_\-]+)[^\n]{0,80}", content, re.IGNORECASE)
        missing_match = re.search(r"Missing or unsupported mandatory dependencies[^\n]*\n([^\n]+)", content, re.IGNORECASE)
        if dep_match or missing_match or "ModResolutionException" in content:
            detail = (missing_match.group(1) if missing_match else (dep_match.group(0) if dep_match else "")).strip()
            return CrashReport(
                exit_code=exit_code,
                title="Missing Mod Dependency" if en else "Eksik Mod Bağımlılığı (Kütüphane)",
                severity="ERROR",
                diagnosis=(
                    f"One or more installed mods require missing libraries:\n{detail}"
                    if en else
                    f"Kurulu modlardan biri eksik bir kütüphaneye ihtiyaç duyuyor:\n{detail}"
                ),
                suggested_action=(
                    "Install the missing dependency (e.g., Fabric API, Cloth Config, Architecturey) from the Mods tab."
                    if en else
                    "Modlar sekmesinden eksik olan kütüphane modunu (ör. Fabric API, Cloth Config) indirip kurun."
                ),
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 5. Duplicate Mod ID
        dup_match = re.search(r"Duplicate mod ID found:\s*([a-zA-Z0-9_\-]+)", content, re.IGNORECASE)
        if dup_match or "DuplicateModsFoundException" in content:
            dup_id = dup_match.group(1) if dup_match else "duplicate mod"
            return CrashReport(
                exit_code=exit_code,
                title=f"Duplicate Mod: {dup_id}" if en else f"Çift / Yinelenen Mod: {dup_id}",
                severity="ERROR",
                diagnosis=(
                    f"Two different files for '{dup_id}' exist in your mods folder."
                    if en else
                    f"Mods klasörünüzde '{dup_id}' moduna ait birden fazla farklı sürüm veya dosya bulunuyor."
                ),
                suggested_action=(
                    "Open the mods directory and delete the older duplicate .jar file."
                    if en else
                    "Mods klasörünü açarak eski sürüm kopyayı silin."
                ),
                culprit_mod=dup_id,
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 6. GLFW / OpenGL / Graphics Driver
        if "GLFW error 65542" in content or "Pixel format not accelerated" in content or "WGL:" in content:
            return CrashReport(
                exit_code=exit_code,
                title="Graphics Driver / OpenGL Error" if en else "Ekran Kartı / OpenGL Hatası",
                severity="CRITICAL",
                diagnosis=(
                    "Minecraft failed to initialize OpenGL window (GLFW error 65542). Your GPU driver may lack OpenGL 3.2+ support."
                    if en else
                    "Minecraft OpenGL penceresi başlatamadı (GLFW hatası 65542). Ekran kartı sürücünüz güncel olmayabilir veya entegre grafik kartı yetersiz."
                ),
                suggested_action=(
                    "Update your graphics card driver (NVIDIA, AMD, or Intel) and ensure Minecraft runs on the dedicated GPU."
                    if en else
                    "Ekran kartı sürücünüzü (NVIDIA / AMD / Intel) güncelleyin ve Windows Grafik Ayarları'ndan Minecraft'ı Yüksek Performanslı GPU'ya atayın."
                ),
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 7. Corrupt Config File
        config_match = re.search(r"(?:JsonSyntaxException|MalformedJsonException).*?(?:config[/\\]([a-zA-Z0-9_\-\.]+))", content)
        if "JsonSyntaxException" in content and config_match:
            bad_cfg = config_match.group(1)
            return CrashReport(
                exit_code=exit_code,
                title=f"Corrupted Config: {bad_cfg}" if en else f"Bozuk Ayar Dosyası: {bad_cfg}",
                severity="ERROR",
                diagnosis=(
                    f"The configuration file '{bad_cfg}' is corrupted and has invalid JSON syntax."
                    if en else
                    f"'{bad_cfg}' ayar dosyası bozulmuş veya geçersiz JSON sözdizimine sahip."
                ),
                suggested_action=(
                    f"Delete or rename 'config/{bad_cfg}' so Minecraft can regenerate clean defaults."
                    if en else
                    f"'config/{bad_cfg}' dosyasını silin veya adını değiştirin; oyun varsayılan ayarları yeniden oluşturacaktır."
                ),
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 8. JVM / Native Crash (EXCEPTION_ACCESS_VIOLATION / SIGSEGV)
        if "EXCEPTION_ACCESS_VIOLATION" in content or "SIGSEGV" in content or "fatal error has been detected" in content:
            return CrashReport(
                exit_code=exit_code,
                title="JVM / Native Crash" if en else "JVM / Yerel Çökme (Native Crash)",
                severity="CRITICAL",
                diagnosis=(
                    "A fatal native memory access violation (SIGSEGV/0xc0000005) occurred in the JVM runtime or a native graphics library."
                    if en else
                    "Java Sanal Makinesi veya yerel bir grafik kütüphanesinde ölümcül bellek erişim hatası (0xc0000005) meydana geldi."
                ),
                suggested_action=(
                    "Update graphics drivers and ensure your Java version matches your Minecraft loader."
                    if en else
                    "Ekran kartı sürücülerinizi güncelleyin ve Java sürümünüzün Minecraft sürümüyle uyumlu olduğunu doğrulayın."
                ),
                raw_log=content,
                log_file_path=log_file_path,
            )

        # 9. Fallback Generic Crash with snippet
        snippet_lines = []
        for line in content.splitlines():
            if any(k in line for k in ("Exception:", "Error:", "FATAL", "Caused by:")):
                snippet_lines.append(line.strip())
        snippet = "\n".join(snippet_lines[:3]) if snippet_lines else f"Process return code: {exit_code}"

        return CrashReport(
            exit_code=exit_code,
            title="Game Crash Detected" if en else "Oyun Çökmesi Tespit Edildi",
            severity="ERROR",
            diagnosis=(
                f"Minecraft terminated unexpectedly (Exit Code: {exit_code}).\n{snippet}"
                if en else
                f"Minecraft beklenmedik biçimde kapandı (Çıkış Kodu: {exit_code}).\n{snippet}"
            ),
            suggested_action=(
                "Inspect the full session log below or upload to mclo.gs for assistance."
                if en else
                "Aşağıdaki tam oturum logunu inceleyin veya destek almak için tek tıkla mclo.gs'e yükleyin."
            ),
            raw_log=content,
            log_file_path=log_file_path,
        )

    @classmethod
    def disable_culprit_mod(cls, report: CrashReport) -> tuple[bool, str]:
        if not report.culprit_path or not os.path.exists(report.culprit_path):
            return False, "File not found."

        try:
            disabled_path = report.culprit_path + ".disabled"
            if os.path.exists(disabled_path):
                os.remove(disabled_path)
            os.rename(report.culprit_path, disabled_path)
            report.culprit_path = disabled_path
            report.can_auto_fix = False
            return True, os.path.basename(disabled_path)
        except Exception as e:
            return False, str(e)

    @classmethod
    def sanitize_log(cls, log_content: str) -> str:
        """Redacts Windows/Unix usernames, tokens, and session identifiers before public upload."""
        if not log_content:
            return ""
        s = log_content
        # 1. Windows & Unix user directory paths (escape backslashes in replacement string)
        s = re.sub(r'(?i)([a-z]:\\(?:users|documents and settings)\\[^\\/\s:;,]+)', r'C:\\Users\\<user>', s)
        s = re.sub(r'(?i)(/(?:home|users)/[^\\/\s:;,]+)', r'/home/<user>', s)
        # 2. Auth tokens, access tokens, bearer headers
        s = re.sub(r'(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{20,}', r'\g<1><redacted_token>', s)
        s = re.sub(r'(?i)([\?&]?(?:access_token|sessionToken|token|auth)=)[a-zA-Z0-9_\-\.]{16,}', r'\g<1><redacted>', s)
        # 3. Minecraft launcher argument session IDs
        s = re.sub(r'(?i)(--uuid\s+)[a-f0-9\-]{32,36}', r'\g<1><redacted_uuid>', s)
        s = re.sub(r'(?i)(--accessToken\s+)[^\s]+', r'\g<1><redacted_token>', s)
        return s

    @classmethod
    def upload_to_mclogs(cls, log_content: str) -> Optional[dict]:
        """Upload log to open-source mclo.gs service and return URL."""
        if not log_content or not log_content.strip():
            return None
        url = "https://api.mclo.gs/1/log"
        sanitized = cls.sanitize_log(log_content)
        try:
            r = requests.post(
                url,
                data={"content": sanitized[:350000]},
                headers={"User-Agent": "VegaLauncher/2.0.0"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    return {"url": data.get("url"), "raw": data.get("raw"), "id": data.get("id")}
        except Exception as e:
            print(f"[CrashAnalyzer] upload_to_mclogs failed: {e}")
        return None


class McloGsUploadThread(QThread):
    upload_finished = Signal(bool, object)

    def __init__(self, log_content: str, parent=None):
        super().__init__(parent)
        self.log_content = log_content

    def run(self):
        try:
            res = CrashAnalyzer.upload_to_mclogs(self.log_content)
            if res and res.get("url"):
                self.upload_finished.emit(True, res)
            else:
                self.upload_finished.emit(False, "Service rejected or unavailable.")
        except Exception as e:
            self.upload_finished.emit(False, str(e))


class VegaCrashDetectiveModal(QDialog):
    """
    Modern obsidian-surfaced Game Crash Detective modal dialog.
    Presents intelligent diagnosis, one-click culprit mod quarantine,
    mclo.gs pastebin upload, and syntax-highlighted error logs.
    """
    mod_disabled = Signal(str)

    def __init__(self, report: CrashReport, parent=None, lang: str = "tr"):
        super().__init__(parent)
        self.report = report
        self.lang = lang
        self._upload_thread = None
        en = self.lang == "en"

        self.setWindowTitle("Crash Detective" if en else "Kaza Dedektifi")
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.resize(760, 560)
        self.setMinimumSize(640, 480)

        self.setStyleSheet("""
            QDialog {
                background-color: #121218;
                color: #F8FAFC;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            QLabel {
                background: transparent;
                color: #F8FAFC;
            }
            QTabWidget::pane {
                border: 1px solid #282834;
                background-color: #161620;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #1A1A24;
                color: #94A3B8;
                font-size: 11px;
                font-weight: 600;
                padding: 6px 14px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: #2D1B4E;
                color: #C084FC;
                font-weight: bold;
                border: 1px solid #581C87;
                border-bottom: none;
            }
            QPushButton {
                background-color: #22222E;
                color: #E2E8F0;
                font-size: 11px;
                font-weight: 600;
                border: 1px solid #333344;
                border-radius: 6px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #2D2D3E;
                color: #FFFFFF;
                border-color: #444458;
            }
            QLineEdit {
                background-color: #1A1A24;
                color: #F8FAFC;
                border: 1px solid #2E2E3E;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Header: Danger Title + Exit Code Badge
        header = QHBoxLayout()
        header.setSpacing(10)

        title_lbl = QLabel(f"⚠️  {self.report.title}", self)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #F87171;")
        header.addWidget(title_lbl, 1)

        code_badge = QLabel(f"Exit Code: {self.report.exit_code}" if en else f"Çıkış Kodu: {self.report.exit_code}", self)
        code_badge.setStyleSheet("background: rgba(239, 68, 68, 0.18); color: #FCA5A5; border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 4px; padding: 3px 8px; font-size: 10px; font-weight: 700;")
        header.addWidget(code_badge)
        layout.addLayout(header)

        # Diagnosis Banner Box
        diag_box = QFrame(self)
        diag_box.setStyleSheet("background-color: rgba(30, 20, 28, 0.85); border: 1.5px solid #EF4444; border-radius: 8px; padding: 4px;")
        diag_layout = QVBoxLayout(diag_box)
        diag_layout.setContentsMargins(12, 10, 12, 10)
        diag_layout.setSpacing(6)

        self.diag_desc = QLabel(self.report.diagnosis, diag_box)
        self.diag_desc.setWordWrap(True)
        self.diag_desc.setStyleSheet("color: #FECACA; font-size: 12px; font-weight: 600; line-height: 1.4;")
        diag_layout.addWidget(self.diag_desc)

        action_hint = QLabel(f"💡 {self.report.suggested_action}", diag_box)
        action_hint.setWordWrap(True)
        action_hint.setStyleSheet("color: #FDE047; font-size: 11px; font-weight: 600;")
        diag_layout.addWidget(action_hint)

        layout.addWidget(diag_box)

        # Tabs: Tab 1 (Log Viewer) & Tab 2 (Details)
        self.tabs = QTabWidget(self)

        # Tab 1: Highlighted Log Console
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(6)

        # Filter row
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        search_lbl = QLabel("Filter:" if en else "Filtrele:", log_tab)
        search_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        search_row.addWidget(search_lbl)

        self.log_search_input = QLineEdit(log_tab)
        self.log_search_input.setPlaceholderText("Search error or mod name..." if en else "Hata veya mod adı ara...")
        self.log_search_input.textChanged.connect(self._filter_log_view)
        search_row.addWidget(self.log_search_input, 1)
        log_layout.addLayout(search_row)

        self.log_text_edit = QTextEdit(log_tab)
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #0B0B10;
                color: #CBD5E1;
                border: 1px solid #1E1E28;
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                line-height: 1.3;
            }
        """)
        self._populate_highlighted_log(self.report.raw_log)
        log_layout.addWidget(self.log_text_edit, 1)

        self.tabs.addTab(log_tab, "Session Log" if en else "Oturum Logu")
        layout.addWidget(self.tabs, 1)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        # One-click Auto-fix button if culprit detected
        if self.report.can_auto_fix and self.report.culprit_path:
            self.fix_btn = QPushButton(
                f"🚨 Disable Culprit ({self.report.culprit_file})" if en else f"🚨 Suçlu Modu Kapat ({self.report.culprit_file})",
                self
            )
            self.fix_btn.setCursor(Qt.PointingHandCursor)
            self.fix_btn.setStyleSheet("""
                QPushButton {
                    background-color: #DC2626;
                    color: white;
                    font-weight: bold;
                    border: 1px solid #B91C1C;
                    border-radius: 6px;
                    padding: 6px 14px;
                }
                QPushButton:hover {
                    background-color: #EF4444;
                }
            """)
            self.fix_btn.clicked.connect(self._on_disable_culprit_clicked)
            btn_row.addWidget(self.fix_btn)

        # mclo.gs upload button
        self.btn_mclogs = QPushButton("🌐 Upload to mclo.gs" if en else "🌐 mclo.gs'e Yükle ve Link Al", self)
        self.btn_mclogs.setCursor(Qt.PointingHandCursor)
        self.btn_mclogs.clicked.connect(self._on_upload_mclogs_clicked)
        btn_row.addWidget(self.btn_mclogs)

        # Copy log button
        btn_copy = QPushButton("📋 Copy Log" if en else "📋 Logu Kopyala", self)
        btn_copy.setCursor(Qt.PointingHandCursor)
        btn_copy.clicked.connect(self._on_copy_clicked)
        btn_row.addWidget(btn_copy)

        # Open logs folder
        if self.report.log_file_path:
            btn_open_folder = QPushButton("📁 Open Logs Folder" if en else "📁 Log Klasörünü Aç", self)
            btn_open_folder.setCursor(Qt.PointingHandCursor)
            btn_open_folder.clicked.connect(self._on_open_folder_clicked)
            btn_row.addWidget(btn_open_folder)

        btn_row.addStretch()

        btn_close = QPushButton("Close" if en else "Kapat", self)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.close)
        btn_row.addWidget(btn_close)

        layout.addLayout(btn_row)

    def _populate_highlighted_log(self, text: str):
        self.log_text_edit.clear()
        if not text:
            self.log_text_edit.setPlainText("No log lines available.")
            return

        cursor = self.log_text_edit.textCursor()
        lines = text.splitlines()

        fmt_fatal = QTextCharFormat()
        fmt_fatal.setForeground(QColor("#EF4444"))
        fmt_fatal.setFontWeight(QFont.Bold)

        fmt_warn = QTextCharFormat()
        fmt_warn.setForeground(QColor("#FBBF24"))

        fmt_info = QTextCharFormat()
        fmt_info.setForeground(QColor("#94A3B8"))

        fmt_normal = QTextCharFormat()
        fmt_normal.setForeground(QColor("#E2E8F0"))

        for line in lines:
            if any(k in line for k in ("[FATAL]", "[ERROR]", "Exception:", "Caused by:")):
                cursor.insertText(line + "\n", fmt_fatal)
            elif "[WARN]" in line:
                cursor.insertText(line + "\n", fmt_warn)
            elif "[INFO]" in line:
                cursor.insertText(line + "\n", fmt_info)
            else:
                cursor.insertText(line + "\n", fmt_normal)

        sb = self.log_text_edit.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _filter_log_view(self, query: str):
        q = query.strip().lower()
        if not q:
            self._populate_highlighted_log(self.report.raw_log)
            return

        filtered_lines = [
            line for line in self.report.raw_log.splitlines()
            if q in line.lower()
        ]
        self._populate_highlighted_log("\n".join(filtered_lines))

    def _on_disable_culprit_clicked(self):
        en = self.lang == "en"
        ok, res = CrashAnalyzer.disable_culprit_mod(self.report)
        if ok:
            try:
                from sound_manager import SoundManager
                SoundManager.get_instance().play_levelup()
            except Exception:
                pass
            if hasattr(self, "fix_btn"):
                self.fix_btn.setEnabled(False)
                self.fix_btn.setText("✓ Disabled" if en else "✓ Devre Dışı Bırakıldı")
                self.fix_btn.setStyleSheet("background-color: #059669; color: white; border: none; border-radius: 6px; padding: 6px 14px;")
            self.diag_desc.setText(
                f"Culprit mod '{self.report.culprit_file}' has been safely renamed to '{res}'. You can launch the game again!"
                if en else
                f"Suçlu mod '{self.report.culprit_file}' güvenle '{res}' olarak adlandırıldı. Oyunu tekrar başlatabilirsiniz!"
            )
            self.mod_disabled.emit(self.report.culprit_file or "")
        else:
            QMessageBox.warning(self, "Error" if en else "Hata", res)

    def _on_upload_mclogs_clicked(self):
        en = self.lang == "en"
        self.btn_mclogs.setEnabled(False)
        self.btn_mclogs.setText("Uploading..." if en else "Yükleniyor...")

        self._upload_thread = McloGsUploadThread(self.report.raw_log, parent=self)

        def _on_done(success: bool, data_or_err):
            self.btn_mclogs.setEnabled(True)
            if success and isinstance(data_or_err, dict) and data_or_err.get("url"):
                url = data_or_err["url"]
                self.report.mclogs_url = url
                self.btn_mclogs.setText("✓ Link Copied!" if en else "✓ Link Kopyalandı!")
                QApplication.clipboard().setText(url)
                QMessageBox.information(
                    self,
                    "Log Uploaded" if en else "Log Yüklendi",
                    f"Log uploaded successfully to mclo.gs!\n\nLink copied to clipboard:\n{url}"
                    if en else
                    f"Log mclo.gs'e başarıyla yüklendi!\n\nLink panoya kopyalandı:\n{url}"
                )
            else:
                self.btn_mclogs.setText("🌐 Upload to mclo.gs" if en else "🌐 mclo.gs'e Yükle ve Link Al")
                QMessageBox.warning(
                    self,
                    "Upload Failed" if en else "Yükleme Başarısız",
                    "Could not upload log to mclo.gs. Check your internet connection."
                    if en else
                    "Log mclo.gs'e yüklenemedi. İnternet bağlantınızı kontrol edin."
                )

        self._upload_thread.upload_finished.connect(_on_done)
        self._upload_thread.start()

    def _on_copy_clicked(self):
        en = self.lang == "en"
        txt = (
            f"=== VEGA CRASH REPORT ===\n"
            f"Title: {self.report.title}\n"
            f"Exit Code: {self.report.exit_code}\n"
            f"Diagnosis: {self.report.diagnosis}\n"
            f"Suggested Action: {self.report.suggested_action}\n"
            f"Culprit Mod: {self.report.culprit_mod or 'None'}\n\n"
            f"=== SESSION LOG ===\n"
            f"{self.report.raw_log}\n"
        )
        QApplication.clipboard().setText(txt)
        try:
            from sound_manager import SoundManager
            SoundManager.get_instance().play_pop()
        except Exception:
            pass
        QMessageBox.information(self, "Copied" if en else "Kopyalandı", "Report copied to clipboard!" if en else "Rapor panoya kopyalandı!")

    def _on_open_folder_clicked(self):
        if self.report.log_file_path and os.path.exists(self.report.log_file_path):
            folder = os.path.dirname(self.report.log_file_path)
            os.startfile(folder)

    def _cleanup_worker(self):
        if getattr(self, "_upload_thread", None) and self._upload_thread.isRunning():
            try:
                self._upload_thread.upload_finished.disconnect()
            except Exception:
                pass
            self._upload_thread.quit()
            self._upload_thread.wait(500)
            self._upload_thread = None

    def reject(self):
        self._cleanup_worker()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_worker()
        super().closeEvent(event)

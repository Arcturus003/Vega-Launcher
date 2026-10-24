from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal


def get_java_major_version(java_exe: str) -> Optional[int]:
    """Inspects a java or javaw executable and extracts its major version (e.g. 8, 17, 21)."""
    if not java_exe or not os.path.isfile(java_exe):
        return None
    try:
        proc = subprocess.run(
            [java_exe, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = proc.stdout or ""
        match = re.search(r'version ["\'](?:1\.)?(\d+)', output)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def get_java_full_version_string(java_exe: str) -> Optional[str]:
    """Inspects a java or javaw executable and extracts its full version string (e.g. 21.0.4+7)."""
    if not java_exe or not os.path.isfile(java_exe):
        return None
    try:
        proc = subprocess.run(
            [java_exe, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = proc.stdout or ""
        match = re.search(r'version ["\']([^"\']+)["\']', output)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


DEFAULT_WINDOWS_JAVA_GLOBS: tuple[str, ...] = (
    r"C:\Program Files\Eclipse Adoptium\jdk-*\bin\javaw.exe",
    r"C:\Program Files\Eclipse Adoptium\jdk-*\bin\java.exe",
    r"C:\Program Files\Microsoft\jdk-*\bin\javaw.exe",
    r"C:\Program Files\Microsoft\jdk-*\bin\java.exe",
    r"C:\Program Files\BellSoft\LibericaJDK-*\bin\javaw.exe",
    r"C:\Program Files\BellSoft\LibericaJDK-*\bin\java.exe",
    r"C:\Program Files\Amazon Corretto\jdk-*\bin\javaw.exe",
    r"C:\Program Files\Amazon Corretto\jdk-*\bin\java.exe",
    r"C:\Program Files\Zulu\*\bin\javaw.exe",
    r"C:\Program Files\Zulu\*\bin\java.exe",
    r"C:\Program Files\Java\jdk-*\bin\javaw.exe",
    r"C:\Program Files\Java\jdk-*\bin\java.exe",
    r"C:\Program Files\Java\jre*\bin\javaw.exe",
    r"C:\Program Files\Java\jre*\bin\java.exe",
    r"C:\Program Files (x86)\Java\jre*\bin\javaw.exe",
    r"C:\Program Files (x86)\Java\jre*\bin\java.exe",
)


class JavaProvisioner:
    """
    Manages detection, version-matching, downloading, and verification of
    portable Adoptium (Eclipse Temurin) OpenJDK runtimes.
    """

    ADOPTIUM_API_BASE = "https://api.adoptium.net/v3"
    SUPPORTED_MAJORS = (8, 17, 21)

    def __init__(self, default_mc_dir: Optional[str] = None):
        self.default_mc_dir = default_mc_dir or os.path.join(os.getenv("APPDATA", ""), ".minecraft")

    @staticmethod
    def get_required_java_version(mc_version: str) -> int:
        """
        Determines the strictly required Java major version for any Minecraft version.
        - <= 1.16.5: Java 8
        - 1.17 to 1.20.4: Java 17
        - 1.20.5+: Java 21
        """
        if not mc_version:
            return 21

        match = re.search(r'(?<![\d\.])1\.(\d+)(?:\.(\d+))?', str(mc_version))
        if not match:
            return 21

        minor = int(match.group(1))
        patch = int(match.group(2)) if match.group(2) else 0

        if minor <= 16:
            return 8
        if minor == 17:
            return 17
        if 18 <= minor <= 19:
            return 17
        if minor == 20:
            return 21 if patch >= 5 else 17
        return 21

    @staticmethod
    def is_java_compatible(java_exe: str, target_major: int) -> bool:
        """
        Validates if the given java executable matches the required major generation.
        Strict generation separation is necessary to avoid Forge/NeoForge mod crashes.
        """
        major = get_java_major_version(java_exe)
        if major is None:
            return False

        if target_major == 8:
            return major == 8
        if target_major == 17:
            return major in (16, 17)
        if target_major == 21:
            return major >= 21
        return major >= target_major

    def get_temurin_install_dir(self, target_major: int, mc_dir: Optional[str] = None) -> str:
        """Returns the target folder for portable Temurin installation."""
        base = mc_dir or self.default_mc_dir
        return os.path.join(base, "runtime", f"temurin-{target_major}")

    def find_portable_temurin(self, target_major: int, mc_dir: Optional[str] = None) -> Optional[str]:
        """
        Looks for an existing portable Temurin installation in <mc_dir>/runtime/temurin-{target_major}/.
        Prefers javaw.exe over java.exe on Windows.
        """
        target_dir = self.get_temurin_install_dir(target_major, mc_dir)
        if not os.path.isdir(target_dir):
            return None

        candidates = []
        for root, _dirs, files in os.walk(target_dir):
            for f in files:
                f_lower = f.lower()
                if f_lower in ("javaw.exe", "javaw"):
                    candidates.insert(0, os.path.join(root, f))
                elif f_lower in ("java.exe", "java"):
                    candidates.append(os.path.join(root, f))

        for cand in candidates:
            if self.is_java_compatible(cand, target_major):
                if sys.platform != "win32":
                    try:
                        os.chmod(cand, 0o755)
                    except Exception:
                        pass
                return cand

        return None

    def get_portable_java_executable(self, target_major: int, mc_dir: Optional[str] = None) -> Optional[str]:
        """Alias for `find_portable_temurin(target_major, mc_dir)`."""
        return self.find_portable_temurin(target_major, mc_dir)

    def find_mojang_runtime(
        self,
        mc_version: str,
        target_major: int,
        mc_dir: Optional[str] = None,
    ) -> Optional[str]:
        """
        Looks for a Mojang official runtime in `<mc_dir>/runtime/<component>/` that
        satisfies `is_java_compatible(..., target_major)`.
        """
        base = mc_dir or self.default_mc_dir
        runtime_root = os.path.join(base, "runtime")
        if not os.path.isdir(runtime_root):
            return None

        component_map = {
            21: ["java-runtime-delta"],
            17: ["java-runtime-gamma", "java-runtime-beta"],
            16: ["java-runtime-alpha"],
            8: ["jre-legacy"],
        }
        preferred_components = list(component_map.get(target_major, []))
        try:
            import minecraft_launcher_lib
            for comp in preferred_components:
                comp_dir = os.path.join(runtime_root, comp)
                if os.path.isdir(comp_dir):
                    try:
                        exe = minecraft_launcher_lib.runtime.get_executable_path(comp, base)
                        if exe and os.path.isfile(exe) and self.is_java_compatible(exe, target_major):
                            return exe
                    except Exception:
                        pass
        except Exception:
            pass

        for comp in preferred_components:
            comp_dir = os.path.join(runtime_root, comp)
            if not os.path.isdir(comp_dir):
                continue
            candidates: list[str] = []
            for root, _dirs, files in os.walk(comp_dir):
                for f in files:
                    f_lower = f.lower()
                    if f_lower in ("javaw.exe", "javaw"):
                        candidates.insert(0, os.path.join(root, f))
                    elif f_lower in ("java.exe", "java"):
                        candidates.append(os.path.join(root, f))
            for cand in candidates:
                if self.is_java_compatible(cand, target_major):
                    return cand

        return None

    def find_system_compatible_java(self, target_major: int) -> Optional[str]:
        """
        Scans system paths (JAVA_HOME, PATH, Program Files) for a Java runtime
        matching the specific target_major.
        """
        candidates: list[str] = []

        jh = os.getenv("JAVA_HOME")
        if jh:
            for binary in ("javaw.exe", "java.exe", "java"):
                p = os.path.join(jh, "bin", binary)
                if os.path.isfile(p):
                    candidates.append(p)

        which_javaw = shutil.which("javaw")
        if which_javaw:
            candidates.append(which_javaw)
        which_java = shutil.which("java")
        if which_java:
            candidates.append(which_java)

        if os.name == "nt":
            for pat in DEFAULT_WINDOWS_JAVA_GLOBS:
                matches = glob.glob(pat)
                if matches:
                    candidates.extend(reversed(sorted(matches)))

        seen = set()
        for cand in candidates:
            norm = os.path.normcase(os.path.abspath(cand))
            if norm in seen:
                continue
            seen.add(norm)
            if self.is_java_compatible(cand, target_major):
                return cand

        return None

    def resolve_java_runtime(
        self,
        mc_version: str,
        mc_dir: Optional[str] = None,
        custom_java: Optional[str] = None,
        custom_java_path: Optional[str] = None,
    ) -> tuple[int, Optional[str]]:
        """
        Resolves the best compatible Java executable for a given Minecraft version.
        Returns: (required_major, executable_path_or_none)
        Priority:
        1. Custom user-specified java_path (if compatible)
        2. Portable Temurin runtime in <mc_dir>/runtime/temurin-{major}/
        3. Official Mojang runtime in <mc_dir>/runtime/<component>/
        4. Compatible system Java matching required generation
        """
        req_major = self.get_required_java_version(mc_version)

        effective_custom = custom_java or custom_java_path
        effective_mc_dir = mc_dir
        if (
            effective_custom is None
            and effective_mc_dir
            and (
                os.path.isfile(effective_mc_dir)
                or os.path.basename(effective_mc_dir).lower() in ("java", "javaw", "java.exe", "javaw.exe")
            )
        ):
            effective_custom = effective_mc_dir
            effective_mc_dir = self.default_mc_dir

        # 1. Check custom path if provided
        if effective_custom and os.path.isfile(effective_custom):
            if self.is_java_compatible(effective_custom, req_major):
                return req_major, effective_custom

        # 2. Check portable Temurin runtime
        portable = self.find_portable_temurin(req_major, effective_mc_dir)
        if portable:
            return req_major, portable

        # 3. Check official Mojang runtime inside <mc_dir>/runtime/
        mojang_rt = self.find_mojang_runtime(mc_version, req_major, effective_mc_dir)
        if mojang_rt:
            return req_major, mojang_rt

        # 4. Check compatible system Java
        sys_java = self.find_system_compatible_java(req_major)
        if sys_java:
            return req_major, sys_java

        return req_major, None


    @staticmethod
    def get_system_architecture() -> str:
        machine = platform.machine().lower()
        if machine in ("amd64", "x86_64"):
            return "x64"
        if "arm" in machine or "aarch64" in machine:
            return "aarch64"
        return "x86"

    def download_and_install_temurin(
        self,
        target_major: int,
        mc_dir: Optional[str] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        lang: str = "tr",
    ) -> str:
        """
        Downloads the official Adoptium Temurin JDK portable zip for Windows,
        extracts to <mc_dir>/runtime/temurin-{target_major}/, and returns javaw.exe path.
        """
        en = lang == "en"
        arch = self.get_system_architecture()
        target_dir = self.get_temurin_install_dir(target_major, mc_dir)
        os.makedirs(target_dir, exist_ok=True)

        sys_os = "windows" if sys.platform == "win32" else ("linux" if sys.platform.startswith("linux") else "mac")
        url = f"{self.ADOPTIUM_API_BASE}/binary/latest/{target_major}/ga/{sys_os}/{arch}/jdk/hotspot/normal/eclipse"
        headers = {
            "User-Agent": f"VegaLauncher/1.0 ({sys_os}; {arch}) AdoptiumProvisioner",
            "Accept": "application/octet-stream",
        }

        msg_connecting = (
            f"Connecting to Adoptium for Java {target_major} ({arch})..."
            if en else
            f"Adoptium Java {target_major} ({arch}) sunucusuna bağlanılıyor..."
        )
        if on_progress:
            on_progress(0, 100, msg_connecting)

        req = urllib.request.Request(url, headers=headers)
        temp_zip = os.path.join(target_dir, f"temurin_{target_major}_download.zip.tmp")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                total_bytes = int(resp.headers.get("Content-Length", 0) or 0)
                downloaded = 0
                chunk_size = 65536

                with open(temp_zip, "wb") as f_out:
                    while True:
                        if is_cancelled and is_cancelled():
                            raise Exception("Download cancelled by user." if en else "İndirme kullanıcı tarafından iptal edildi.")
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            percent = int(downloaded * 100 / total_bytes) if total_bytes > 0 else 0
                            mb_cur = downloaded / (1024 * 1024)
                            mb_tot = total_bytes / (1024 * 1024)
                            stat = (
                                f"Downloading Adoptium Java {target_major}: {mb_cur:.1f} MB / {mb_tot:.1f} MB (%{percent})"
                                if en else
                                f"Adoptium Java {target_major} İndiriliyor: {mb_cur:.1f} MB / {mb_tot:.1f} MB (%{percent})"
                            )
                            on_progress(downloaded, total_bytes if total_bytes > 0 else 100, stat)

            # Extraction
            msg_extract = (
                f"Extracting Adoptium Java {target_major} runtime..."
                if en else
                f"Adoptium Java {target_major} dosyaları ayıklanıyor..."
            )
            if on_progress:
                on_progress(100, 100, msg_extract)

            if zipfile.is_zipfile(temp_zip):
                with zipfile.ZipFile(temp_zip, "r") as zf:
                    target_real = os.path.realpath(target_dir)
                    for member in zf.infolist():
                        if is_cancelled and is_cancelled():
                            raise Exception("Extraction cancelled by user." if en else "Ayıklama kullanıcı tarafından iptal edildi.")
                        # Safe zip extraction against Zip Slip
                        extracted_path = os.path.realpath(os.path.join(target_dir, member.filename))
                        if not extracted_path.startswith(target_real):
                            raise RuntimeError(f"Zip slip security error detected for {member.filename}")
                        zf.extract(member, target_dir)
            elif tarfile.is_tarfile(temp_zip):
                with tarfile.open(temp_zip, "r:*") as tf:
                    target_real = os.path.realpath(target_dir)
                    for member in tf.getmembers():
                        if is_cancelled and is_cancelled():
                            raise Exception("Extraction cancelled by user." if en else "Ayıklama kullanıcı tarafından iptal edildi.")
                        extracted_path = os.path.realpath(os.path.join(target_dir, member.name))
                        if not extracted_path.startswith(target_real):
                            raise RuntimeError(f"Tar slip security error detected for {member.name}")
                        tf.extract(member, target_dir)
            else:
                raise ValueError(
                    f"Downloaded Temurin archive is neither a valid zip nor tar archive: {temp_zip}"
                    if en else
                    f"İndirilen Adoptium arşivi geçerli bir zip veya tar dosyası değil: {temp_zip}"
                )

            # Cleanup temp zip
            try:
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
            except Exception:
                pass

            # Locate installed executable
            portable = self.find_portable_temurin(target_major, mc_dir)
            if portable and os.path.isfile(portable):
                return portable

            raise RuntimeError(
                f"Adoptium Java {target_major} was installed, but Java executable could not be verified."
                if en else
                f"Adoptium Java {target_major} kuruldu ancak Java yürütülebilir dosyası doğrulanamadı."
            )

        except Exception as exc:
            # Clean up temp file on failure
            try:
                if os.path.exists(temp_zip):
                    os.remove(temp_zip)
            except Exception:
                pass
            raise exc

    def get_runtime_status(self, target_major: int, mc_dir: Optional[str] = None) -> dict:
        """Returns the availability and status details of a specific Java version."""
        portable = self.find_portable_temurin(target_major, mc_dir)
        if portable:
            ver_str = get_java_full_version_string(portable) or f"{target_major}.x"
            return {
                "major": target_major,
                "installed": True,
                "is_portable": True,
                "source": "Temurin (Dahili)",
                "path": portable,
                "version_str": ver_str,
            }

        sys_cand = self.find_system_compatible_java(target_major)
        if sys_cand:
            ver_str = get_java_full_version_string(sys_cand) or f"{target_major}.x"
            return {
                "major": target_major,
                "installed": True,
                "is_portable": False,
                "source": "Sistem Java",
                "path": sys_cand,
                "version_str": ver_str,
            }

        return {
            "major": target_major,
            "installed": False,
            "is_portable": False,
            "source": "Yok",
            "path": None,
            "version_str": None,
        }

    def get_all_statuses(self, mc_dir: Optional[str] = None) -> dict[int, dict]:
        """Returns runtime status for all supported generations (8, 17, 21)."""
        return {ver: self.get_runtime_status(ver, mc_dir) for ver in self.SUPPORTED_MAJORS}


class JavaDownloadThread(QThread):
    """
    Background worker thread to download and provision Adoptium Temurin runtimes
    without blocking the PySide6 UI event loop.
    """
    progress_val = Signal(int, int)
    progress_status = Signal(str)
    download_finished = Signal(bool, str)

    def __init__(
        self,
        target_major: int,
        mc_dir: Optional[str] = None,
        provisioner: Optional[JavaProvisioner] = None,
        lang: str = "tr",
        parent=None,
    ):
        super().__init__(parent)
        self.target_major = target_major
        self.mc_dir = mc_dir
        self.provisioner = provisioner or DEFAULT_JAVA_PROVISIONER
        self.lang = lang
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            exe_path = self.provisioner.download_and_install_temurin(
                target_major=self.target_major,
                mc_dir=self.mc_dir,
                on_progress=lambda cur, tot, stat: (
                    self.progress_val.emit(cur, tot),
                    self.progress_status.emit(stat),
                ),
                is_cancelled=lambda: self._is_cancelled,
                lang=self.lang,
            )
            if self._is_cancelled:
                self.download_finished.emit(False, "Cancelled")
            else:
                self.download_finished.emit(True, exe_path)
        except Exception as e:
            self.download_finished.emit(False, str(e))


DEFAULT_JAVA_PROVISIONER = JavaProvisioner()

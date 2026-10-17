from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal


@dataclass(frozen=True)
class RuntimeSpec:
    """Typed specification for a Minecraft client or server runtime environment."""
    mc_version: str
    loader: str = "vanilla"  # "vanilla", "fabric", "quilt", "forge", "neoforge", "purpur"
    loader_version: Optional[str] = None
    is_server: bool = False

    @property
    def normalized_loader(self) -> str:
        return self.loader.lower().strip()


class DefaultClientInstallerBackend:
    """Production adapter delegating to minecraft_launcher_lib."""
    def install_vanilla(self, version_id: str, mc_dir: str, callback: Optional[dict] = None) -> None:
        import minecraft_launcher_lib
        minecraft_launcher_lib.install.install_minecraft_version(version_id, mc_dir, callback=callback)

    def install_fabric(self, mc_version: str, mc_dir: str, loader_version: Optional[str] = None, callback: Optional[dict] = None) -> str:
        import minecraft_launcher_lib
        if not loader_version:
            loader_version = minecraft_launcher_lib.fabric.get_latest_loader_version()
        minecraft_launcher_lib.fabric.install_fabric(mc_version, mc_dir, loader_version=loader_version, callback=callback)
        return f"fabric-loader-{loader_version}-{mc_version}"

    def install_quilt(self, mc_version: str, mc_dir: str, loader_version: Optional[str] = None, callback: Optional[dict] = None) -> str:
        import minecraft_launcher_lib
        if loader_version:
            minecraft_launcher_lib.quilt.install_quilt(mc_version, mc_dir, loader_version=loader_version, callback=callback)
            return f"quilt-loader-{loader_version}-{mc_version}"
        else:
            minecraft_launcher_lib.quilt.install_quilt(mc_version, mc_dir, callback=callback)
            return f"quilt-loader-{mc_version}"

    def install_forge(self, mc_version: str, mc_dir: str, forge_version: Optional[str] = None, callback: Optional[dict] = None) -> str:
        import minecraft_launcher_lib
        if not forge_version:
            forge_version = minecraft_launcher_lib.forge.find_forge_version(mc_version)
            if not forge_version:
                raise Exception(f"Forge {mc_version} için bulunamadı.")
        target_version_arg = forge_version if f"{mc_version}-" in str(forge_version) else f"{mc_version}-{forge_version}"
        minecraft_launcher_lib.forge.install_forge_version(target_version_arg, mc_dir, callback=callback)

        # Forge sürüm adını klasör mtime veya doğrudan ID ile doğrula
        versions_dir = os.path.join(mc_dir, "versions")
        if os.path.isdir(versions_dir):
            forge_dirs = []
            for d in os.listdir(versions_dir):
                if "forge" in d.lower() and mc_version in d:
                    dpath = os.path.join(versions_dir, d)
                    if os.path.isdir(dpath):
                        forge_dirs.append((d, os.path.getmtime(dpath)))
            if forge_dirs:
                forge_dirs.sort(key=lambda x: x[1], reverse=True)
                return forge_dirs[0][0]
        return f"{mc_version}-forge-{forge_version}"

    def install_neoforge(self, mc_version: str, mc_dir: str, loader_version: Optional[str] = None, callback: Optional[dict] = None) -> str:
        import minecraft_launcher_lib.mod_loader
        neo = minecraft_launcher_lib.mod_loader.get_mod_loader("neoforge")
        if not loader_version:
            loader_version = neo.get_latest_loader_version(mc_version)
            if not loader_version:
                raise Exception(f"NeoForge {mc_version} için bulunamadı veya desteklenmiyor.")
        installed_ver = neo.install(mc_version, loader_version, mc_dir, callback=callback)
        if not installed_ver:
            installed_ver = neo.get_installed_version(mc_version, loader_version)
        return installed_ver if installed_ver else f"neoforge-{loader_version}-{mc_version}"


class RuntimeProvisioner:
    """
    Deep module responsible for runtime detection, client engine installation
    (Vanilla, Fabric, Quilt, Forge, NeoForge), and server software provisioning
    (Purpur, Fabric, Forge, NeoForge).
    """
    def __init__(self, installer_backend=None, mc_dir: Optional[str] = None):
        self.backend = installer_backend or DefaultClientInstallerBackend()
        self.mc_dir = mc_dir or os.path.join(os.getenv("APPDATA", ""), ".minecraft")

    @staticmethod
    def extract_base_version(ver_str: Optional[str], default: Optional[str] = "1.20.1") -> Optional[str]:
        if not ver_str:
            return default
        match = re.search(r'(?<![\d\.])(1\.(?:[7-9]|\d{2})(?:\.\d+)?)(?![\d\.])', str(ver_str))
        if match:
            return match.group(1)
        fallback = re.search(r'(\d+\.\d+(?:\.\d+)?)', str(ver_str))
        return fallback.group(1) if fallback else default

    @staticmethod
    def detect_client_runtime(pdata: Optional[dict]) -> RuntimeSpec:
        if not pdata or not isinstance(pdata, dict):
            return RuntimeSpec(mc_version="1.20.1", loader="vanilla")

        mc_ver = str(pdata.get("game_version") or "")
        if not mc_ver:
            mc_ver = RuntimeProvisioner.extract_base_version(pdata.get("version"))

        loader_val = str(pdata.get("loader") or "").lower().strip()
        if loader_val in ("fabric", "forge", "neoforge", "quilt"):
            return RuntimeSpec(mc_version=mc_ver, loader=loader_val)

        ver_str = str(pdata.get("version") or "").lower()
        for known in ("neoforge", "fabric", "quilt", "forge"):
            if known in ver_str:
                return RuntimeSpec(mc_version=mc_ver, loader=known)

        prof_path = pdata.get("path") or ""
        if prof_path and os.path.isdir(prof_path):
            mods_dir = os.path.join(prof_path, "mods")
            if os.path.isdir(mods_dir):
                try:
                    files = [f.lower() for f in os.listdir(mods_dir) if f.endswith(".jar")]
                    neo_cnt = sum(1 for f in files if "neoforge" in f)
                    fab_cnt = sum(1 for f in files if "fabric" in f)
                    quilt_cnt = sum(1 for f in files if "quilt" in f)
                    forge_cnt = sum(1 for f in files if "forge" in f and "neoforge" not in f)
                    counts = {"neoforge": neo_cnt, "fabric": fab_cnt, "quilt": quilt_cnt, "forge": forge_cnt}
                    top_loader = max(counts, key=counts.get)
                    if counts[top_loader] > 0:
                        return RuntimeSpec(mc_version=mc_ver, loader=top_loader)
                except Exception:
                    pass

        return RuntimeSpec(mc_version=mc_ver, loader="vanilla")

    @staticmethod
    def detect_server_runtime(server_dir: str | Path) -> RuntimeSpec:
        s_dir = str(server_dir)
        if not s_dir or not os.path.exists(s_dir):
            return RuntimeSpec(mc_version="1.20.1", loader="purpur", is_server=True)

        loader = "purpur"
        version = None
        try:
            files = os.listdir(s_dir)
            jar_files = [f.lower() for f in files if f.endswith(".jar") and f != "installer.jar"]

            for jf in jar_files:
                if "purpur" in jf:
                    loader = "purpur"
                    break
                elif "paper" in jf:
                    loader = "paper"
                    break
                elif "spigot" in jf:
                    loader = "spigot"
                    break
                elif "neoforge" in jf:
                    loader = "neoforge"
                    break
                elif "forge" in jf:
                    loader = "forge"
                    break
                elif "fabric" in jf:
                    loader = "fabric"
                    break

            libs_dir = os.path.join(s_dir, "libraries")
            if os.path.exists(libs_dir):
                if os.path.exists(os.path.join(libs_dir, "net", "neoforged")):
                    loader = "neoforge"
                elif os.path.exists(os.path.join(libs_dir, "net", "minecraftforge")):
                    loader = "forge"
                elif os.path.exists(os.path.join(libs_dir, "net", "fabricmc")):
                    loader = "fabric"

            for jf in jar_files:
                match = re.search(r'(?<![\d\.])(1\.(?:[7-9]|\d{2})(?:\.\d+)?)(?![\d\.])', jf)
                if match:
                    version = match.group(1)
                    break

            if not version:
                for f in files:
                    if f.endswith(".txt") or f.endswith(".json") or f.endswith(".log"):
                        fpath = os.path.join(s_dir, f)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                                content = fh.read(2048)
                                match = re.search(r'Minecraft (1\.\d+(\.\d+)?)', content)
                                if match:
                                    version = match.group(1)
                                    break
                        except Exception:
                            pass
        except Exception:
            pass

        return RuntimeSpec(
            mc_version=version if version else "1.20.1",
            loader=loader,
            is_server=True,
        )

    def install_client_runtime(
        self,
        spec: RuntimeSpec,
        mc_dir: Optional[str] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        lang: str = "tr",
    ) -> str:
        target_mc_dir = mc_dir or self.mc_dir
        loader = spec.normalized_loader
        mc_ver = spec.mc_version
        en = lang == "en"
        cancel_msg = "Download cancelled by user." if en else "İndirme kullanıcı tarafından iptal edildi."

        def _cancelled() -> bool:
            return bool(is_cancelled and is_cancelled())

        max_val_holder = [0]

        def _set_status(txt: str):
            if _cancelled():
                raise Exception(cancel_msg)
            if on_progress:
                on_progress(0, 0, txt)

        def _set_max(m: int):
            max_val_holder[0] = m if m and m > 0 else 0

        def _set_progress(p: int):
            if _cancelled():
                raise Exception(cancel_msg)
            if on_progress:
                max_v = max_val_holder[0]
                norm = int((p / max_v) * 100) if max_v > 0 else p
                on_progress(min(100, max(0, norm)), 100, "")

        cb = {
            "setStatus": _set_status,
            "setProgress": _set_progress,
            "setMax": _set_max,
        }

        if _cancelled():
            raise Exception(cancel_msg)

        if loader == "vanilla":
            if on_progress:
                on_progress(0, 100, f"Downloading Vanilla {mc_ver}..." if en else f"Vanilla {mc_ver} indiriliyor...")
            self.backend.install_vanilla(mc_ver, target_mc_dir, callback=cb)
            return mc_ver

        if loader == "fabric":
            if on_progress:
                on_progress(0, 100, f"Installing Fabric {mc_ver}..." if en else f"Fabric {mc_ver} kuruluyor...")
            return self.backend.install_fabric(mc_ver, target_mc_dir, loader_version=spec.loader_version, callback=cb)

        if loader == "quilt":
            if on_progress:
                on_progress(0, 100, f"Installing Quilt {mc_ver}..." if en else f"Quilt {mc_ver} kuruluyor...")
            return self.backend.install_quilt(mc_ver, target_mc_dir, loader_version=spec.loader_version, callback=cb)

        if loader == "forge":
            if on_progress:
                on_progress(0, 100, f"Installing Forge {mc_ver}..." if en else f"Forge {mc_ver} kuruluyor...")
            return self.backend.install_forge(mc_ver, target_mc_dir, forge_version=spec.loader_version, callback=cb)

        if loader == "neoforge":
            if on_progress:
                on_progress(0, 100, f"Installing NeoForge {mc_ver}..." if en else f"NeoForge {mc_ver} kuruluyor...")
            return self.backend.install_neoforge(mc_ver, target_mc_dir, loader_version=spec.loader_version, callback=cb)

        # Fallback to vanilla
        self.backend.install_vanilla(mc_ver, target_mc_dir, callback=cb)
        return mc_ver

    def provision_server_runtime(
        self,
        software: str,
        version: str,
        target_path: str,
        on_progress: Optional[Callable[[int], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        lang: str = "tr",
    ) -> Path:
        en = lang == "en"
        def _log(msg: str):
            if on_log:
                on_log(msg)

        def _prog(pct: int):
            if on_progress:
                on_progress(pct)

        def _cancelled() -> bool:
            return bool(is_cancelled and is_cancelled())

        from mod_manager import ModrinthAPI

        url = ""
        is_installer = False

        if "purpur" in software.lower():
            url = f"https://api.purpurmc.org/v2/purpur/{version}/latest/download"
        elif "fabric" in software.lower():
            _log("Fetching Fabric metadata..." if en else "Fabric meta verileri alınıyor...")
            req_meta = urllib.request.Request("https://meta.fabricmc.net/v2/versions/loader", headers=ModrinthAPI.HEADERS)
            with urllib.request.urlopen(req_meta, timeout=15) as meta_resp:
                meta_json = json.loads(meta_resp.read().decode("utf-8"))
                latest_loader = next((item["version"] for item in meta_json if item.get("stable")), None)
                if not latest_loader and meta_json:
                    latest_loader = meta_json[0].get("version")
                if not latest_loader:
                    latest_loader = "0.15.11"
            url = f"https://meta.fabricmc.net/v2/versions/loader/{version}/{latest_loader}/1.0.1/server/jar"
        elif "forge" in software.lower() and "neoforge" not in software.lower():
            _log("Fetching Forge version data..." if en else "Forge sürüm verileri alınıyor...")
            req_forge = urllib.request.Request("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json", headers=ModrinthAPI.HEADERS)
            with urllib.request.urlopen(req_forge, timeout=15) as forge_resp:
                forge_data = json.loads(forge_resp.read().decode("utf-8"))
                promos = forge_data.get("promos", {})
                forge_version = promos.get(f"{version}-recommended") or promos.get(f"{version}-latest")
                if not forge_version:
                    raise Exception(f"Forge version not found for {version}." if en else f"{version} için Forge sürümü bulunamadı.")
                url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{version}-{forge_version}/forge-{version}-{forge_version}-installer.jar"
            is_installer = True
        elif "neoforge" in software.lower():
            _log("Fetching NeoForge version data..." if en else "NeoForge sürüm verileri alınıyor...")
            req_neo = urllib.request.Request("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge", headers=ModrinthAPI.HEADERS)
            with urllib.request.urlopen(req_neo, timeout=15) as neo_resp:
                neo_data = json.loads(neo_resp.read().decode("utf-8"))
                versions = neo_data.get("versions", [])
                prefix = ""
                if version == "1.21.1": prefix = "21.1."
                elif version == "1.21": prefix = "21.0."
                elif version == "1.20.4": prefix = "20.4."
                elif version == "1.20.2": prefix = "20.2."
                else:
                    raise Exception(f"NeoForge version is not supported for {version}." if en else f"{version} için NeoForge sürümü desteklenmiyor.")
                valid_versions = [v for v in versions if v.startswith(prefix)]
                if not valid_versions:
                    raise Exception(f"NeoForge version not found for {version}." if en else f"{version} için NeoForge sürümü bulunamadı.")
                valid_versions.sort(key=lambda x: [int(p) for p in x.split(".") if p.isdigit()])
                latest = valid_versions[-1]
                url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{latest}/neoforge-{latest}-installer.jar"
            is_installer = True
        else:
            raise Exception("Unsupported software." if en else "Desteklenmeyen yazılım.")

        _log(f"[INFO] Downloading: {software} {version}" if en else f"[BİLGİ] İndiriliyor: {software} {version}")
        server_dir = os.path.dirname(target_path)
        os.makedirs(server_dir, exist_ok=True)
        download_path = os.path.join(server_dir, "installer.jar") if is_installer else target_path

        req = urllib.request.Request(url, headers=ModrinthAPI.HEADERS)
        with urllib.request.urlopen(req, timeout=20) as response:
            total_size = int(response.getheader("Content-Length", 0))
            downloaded = 0
            chunk_size = 8192
            with open(download_path, "wb") as f:
                while True:
                    if _cancelled():
                        raise Exception("Server download cancelled." if en else "Sunucu indirme işlemi iptal edildi.")
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        _prog(int(downloaded * 100 / total_size))

        if is_installer:
            _log(f"[INFO] Installing {software}, please wait..." if en else f"[BİLGİ] {software} kuruluyor, lütfen bekleyin...")
            installer_path = download_path
            try:
                java_exe = "java"
                if os.name == "nt":
                    matches = (
                        glob.glob(r"C:\Program Files\Microsoft\jdk-*\bin\java.exe")
                        + glob.glob(r"C:\Program Files\Eclipse Adoptium\jdk-*\bin\java.exe")
                        + glob.glob(r"C:\Program Files\Java\jdk-*\bin\java.exe")
                    )
                    if matches:
                        for candidate in reversed(sorted(matches)):
                            if os.path.exists(candidate):
                                java_exe = candidate
                                break
                    if java_exe == "java" and "JAVA_HOME" in os.environ:
                        jh = os.path.join(os.environ["JAVA_HOME"], "bin", "java.exe")
                        if os.path.exists(jh):
                            java_exe = jh

                process = subprocess.Popen(
                    [java_exe, "-jar", installer_path, "--installServer"],
                    cwd=server_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                for line in iter(process.stdout.readline, ""):
                    if line:
                        _log(f"Installing: {line.strip()[:80]}" if en else f"Kurulum: {line.strip()[:80]}")
                process.wait()
                if process.returncode == 0:
                    _log(f"[INFO] {software} installation completed." if en else f"[BİLGİ] {software} kurulumu tamamlandı.")
                    for f in os.listdir(server_dir):
                        if (f.startswith("forge-") or f.startswith("neoforge-")) and f.endswith(".jar") and f != "installer.jar":
                            try:
                                os.replace(os.path.join(server_dir, f), os.path.join(server_dir, "server.jar"))
                                break
                            except Exception:
                                pass
                else:
                    raise Exception(
                        f"{software} installation failed (Code: {process.returncode})."
                        if en else
                        f"{software} kurulumu başarısız oldu (Kod: {process.returncode})."
                    )
            finally:
                if os.path.exists(installer_path):
                    try:
                        os.remove(installer_path)
                    except Exception:
                        pass

        # Otomatik Playit.gg İndirme
        _log("Downloading Playit.gg plugin/mod..." if en else "Playit.gg altyapısı indiriliyor...")
        try:
            playit_url = ""
            dest_folder = ""
            if "purpur" in software.lower():
                playit_url = "https://github.com/playit-cloud/playit-minecraft-plugin/releases/latest/download/playit-minecraft-plugin.jar"
                dest_folder = "plugins"
            elif any(k in software.lower() for k in ("fabric", "forge", "neoforge")):
                loader_id = "fabric"
                if "forge" in software.lower() and "neoforge" not in software.lower():
                    loader_id = "forge"
                elif "neoforge" in software.lower():
                    loader_id = "neoforge"

                req_playit = urllib.request.Request(
                    f"https://api.modrinth.com/v2/project/playit-companion/version?game_versions=[%22{version}%22]&loaders=[%22{loader_id}%22]",
                    headers=ModrinthAPI.HEADERS,
                )
                with urllib.request.urlopen(req_playit, timeout=15) as playit_resp:
                    playit_json = json.loads(playit_resp.read().decode("utf-8"))
                    if playit_json:
                        playit_url = playit_json[0]["files"][0]["url"]
                dest_folder = "mods"

            if playit_url and dest_folder:
                os.makedirs(os.path.join(server_dir, dest_folder), exist_ok=True)
                playit_target = os.path.join(server_dir, dest_folder, f"playit-{software.split(' ')[0].lower()}.jar")
                req_dl = urllib.request.Request(playit_url, headers=ModrinthAPI.HEADERS)
                with urllib.request.urlopen(req_dl, timeout=15) as p_resp:
                    with open(playit_target, "wb") as pf:
                        pf.write(p_resp.read())
                _log("[INFO] Playit.gg installed successfully." if en else "[BİLGİ] Playit.gg başarıyla kuruldu.")
        except Exception as pe:
            _log(f"[WARNING] Could not auto-download Playit.gg: {pe}" if en else f"[UYARI] Playit.gg otomatik indirilemedi: {pe}")

        _prog(100)
        _log("[INFO] Software downloaded and installed successfully!" if en else "[BİLGİ] Yazılım başarıyla indirildi ve kuruldu!")
        return Path(target_path)


DEFAULT_PROVISIONER = RuntimeProvisioner()


# --- Reusable Qt Thread Adapter ---

class RuntimeInstallThread(QThread):
    progress_val = Signal(int)
    progress_update = Signal(str)
    task_finished = Signal(bool, str)

    def __init__(
        self,
        spec: RuntimeSpec,
        mc_dir: Optional[str] = None,
        provisioner: Optional[RuntimeProvisioner] = None,
        lang: str = "tr",
    ):
        super().__init__()
        self.spec = spec
        self.mc_dir = mc_dir
        self.provisioner = provisioner or DEFAULT_PROVISIONER
        self.lang = lang
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            def on_progress(cur: int, tot: int, text: str):
                if cur > 0:
                    self.progress_val.emit(cur)
                if text:
                    self.progress_update.emit(text)

            installed_ver = self.provisioner.install_client_runtime(
                self.spec,
                mc_dir=self.mc_dir,
                on_progress=on_progress,
                is_cancelled=lambda: self._is_cancelled,
                lang=self.lang,
            )
            self.task_finished.emit(True, installed_ver)
        except Exception as e:
            self.task_finished.emit(False, str(e))

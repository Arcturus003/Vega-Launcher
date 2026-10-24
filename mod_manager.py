from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import requests
from PySide6.QtCore import QThread, Signal
from curseforge_api import CurseForgeAPI


def detect_profile_loader(pdata: Optional[dict]) -> Optional[str]:
    if not pdata or not isinstance(pdata, dict):
        return None
    if pdata.get("loader"):
        return str(pdata.get("loader")).lower()
    from runtime_provisioner import RuntimeProvisioner
    spec = RuntimeProvisioner.detect_client_runtime(pdata)
    ldr = spec.loader if spec.loader != "vanilla" else None
    if ldr:
        pdata["loader"] = ldr
    return ldr


def detect_profile_game_version(pdata: Optional[dict]) -> Optional[str]:
    if not pdata or not isinstance(pdata, dict):
        return None
    ver = str(pdata.get("game_version") or "")
    if ver:
        return ver
    ver_str = pdata.get("version")
    if not ver_str:
        return None
    from runtime_provisioner import RuntimeProvisioner
    return RuntimeProvisioner.extract_base_version(ver_str, default=None)


@dataclass(frozen=True)
class CompatibilityPolicy:
    """
    Strict type-based resolution rules (see GLOSSARY.md):
    - mod / plugin: requires matching game_version AND loader (quilt expands to quilt + fabric).
    - shader: requires matching game_version only (loader is ignored).
    - modpack_update: requires matching loader (tries game_version + loader first, then loader-only).
    - modpack: optional filters for browsing/initial selection.
    """
    content_type: str  # "mod", "plugin", "shader", "modpack", "modpack_update"
    game_version: Optional[str] = None
    loader: Optional[str | Sequence[str]] = None

    @classmethod
    def for_profile(cls, pdata: Optional[dict], content_type: str) -> "CompatibilityPolicy":
        game_ver = detect_profile_game_version(pdata)
        ldr = None if content_type == "shader" else detect_profile_loader(pdata)
        return cls(content_type=content_type, game_version=game_ver, loader=ldr)

    @property
    def effective_loaders(self) -> tuple[str, ...]:
        if self.content_type == "shader" or not self.loader:
            return ()
        if isinstance(self.loader, (list, tuple)):
            out = []
            for item in self.loader:
                low = str(item).lower()
                if low == "quilt":
                    for q in ("quilt", "fabric"):
                        if q not in out:
                            out.append(q)
                elif low not in out:
                    out.append(low)
            return tuple(out)
        low = str(self.loader).lower()
        if low == "quilt":
            return ("quilt", "fabric")
        return (low,)

    @property
    def target_subdir(self) -> str:
        if self.content_type == "shader":
            return "shaderpacks"
        if self.content_type == "plugin":
            return "plugins"
        return "mods"


@dataclass(frozen=True)
class Artifact:
    project_id: str
    version_id: str
    filename: str
    url: str
    content_type: str = "mod"


@dataclass(frozen=True)
class InstallResult:
    ok: bool
    message: str
    version_id: str = ""
    filename: str = ""
    already_exists: bool = False
    rolled_back: bool = False
    conflicting_file: str = ""


class TransactionalRollback:
    """
    Atomic directory backup & rollback context manager for modpack updates (see GLOSSARY.md).
    Moves protected subdirectories (`mods`, `config`) to `<name>.old_bak` before installation,
    restores them on exception/cancellation, and purges `.old_bak` on clean commit.
    """
    def __init__(self, profile_dir: str | Path, enabled: bool = True, subdirs: Sequence[str] = ("mods", "config")):
        self.profile_dir = Path(profile_dir)
        self.enabled = enabled
        self.subdirs = tuple(subdirs)
        self.rolled_back = False

    def __enter__(self) -> "TransactionalRollback":
        if not self.enabled or not self.profile_dir.exists():
            return self
        for name in self.subdirs:
            cur = self.profile_dir / name
            bak = self.profile_dir / f"{name}.old_bak"
            shutil.rmtree(bak, ignore_errors=True)
            if cur.exists():
                try:
                    os.replace(cur, bak)
                except Exception:
                    try:
                        shutil.move(str(cur), str(bak))
                    except Exception as err:
                        print(f"[TransactionalRollback] Warning: Could not backup {name}: {err}")
        return self

    def rollback(self) -> None:
        if not self.enabled or not self.profile_dir.exists():
            return
        for name in self.subdirs:
            cur = self.profile_dir / name
            bak = self.profile_dir / f"{name}.old_bak"
            if bak.exists():
                shutil.rmtree(cur, ignore_errors=True)
                try:
                    os.replace(bak, cur)
                except Exception:
                    try:
                        shutil.move(str(bak), str(cur))
                    except Exception as err:
                        print(f"[TransactionalRollback] Warning: Could not restore {name}: {err}")
        self.rolled_back = True

    def commit(self) -> None:
        if not self.enabled or not self.profile_dir.exists():
            return
        for name in self.subdirs:
            bak = self.profile_dir / f"{name}.old_bak"
            shutil.rmtree(bak, ignore_errors=True)

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        return False


class DefaultLoaderInstallerAdapter:
    """Production adapter at the loader installation seam delegating to RuntimeProvisioner."""
    def install(
        self,
        mc_version: str,
        loader_name: str,
        loader_version: str,
        mc_dir: str,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> str:
        from runtime_provisioner import RuntimeProvisioner, RuntimeSpec
        provisioner = RuntimeProvisioner(mc_dir=mc_dir)
        spec = RuntimeSpec(
            mc_version=mc_version,
            loader=loader_name,
            loader_version=loader_version,
        )

        def _prog_bridge(cur: int, tot: int, msg: str):
            if on_progress and msg:
                on_progress(msg)

        return provisioner.install_client_runtime(
            spec,
            mc_dir=mc_dir,
            on_progress=_prog_bridge,
        )


class ModrinthAPI:
    BASE_URL = "https://api.modrinth.com/v2"
    HEADERS = {"User-Agent": "VegaLauncher/2.0.0 (https://github.com/Arcturus003/Vega-Launcher)"}
    _session = None

    @classmethod
    def get_session(cls):
        if cls._session is None:
            cls._session = requests.Session()
            cls._session.headers.update(cls.HEADERS)
        return cls._session

    @classmethod
    def _get(cls, url, **kwargs):
        if hasattr(requests.get, "mock_calls"):
            return requests.get(url, **kwargs)
        return cls.get_session().get(url, **kwargs)

    @staticmethod
    def search_projects(query, project_type="mod", index="relevance", limit=12, version=None, loader=None, category=None):
        url = f"{ModrinthAPI.BASE_URL}/search"
        facets = [[f"project_type:{project_type}"]]
        if version:
            facets.append([f"versions:{version}"])
        if loader:
            if isinstance(loader, (list, tuple)):
                facets.append([f"categories:{l.lower()}" for l in loader])
            elif str(loader).lower() == "quilt":
                facets.append(["categories:quilt", "categories:fabric"])
            else:
                facets.append([f"categories:{str(loader).lower()}"])
        if category:
            facets.append([f"categories:{category.lower()}"])

        params = {
            "query": query,
            "index": index,
            "limit": limit,
            "facets": json.dumps(facets),
        }
        try:
            r = ModrinthAPI._get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("hits", [])
        except Exception as e:
            print(f"Modrinth API Hatası: {e}")
            return None

    @staticmethod
    def get_project_versions(project_id, game_version=None, loader=None):
        url = f"{ModrinthAPI.BASE_URL}/project/{project_id}/version"
        params = {}
        if game_version:
            if isinstance(game_version, (list, tuple)):
                params["game_versions"] = json.dumps(list(game_version))
            else:
                params["game_versions"] = json.dumps([game_version])
        if loader:
            if isinstance(loader, (list, tuple)):
                params["loaders"] = json.dumps([l.lower() for l in loader])
            elif str(loader).lower() == "quilt":
                params["loaders"] = json.dumps(["quilt", "fabric"])
            else:
                params["loaders"] = json.dumps([str(loader).lower()])
        try:
            response = ModrinthAPI._get(url, params=params if params else None, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Modrinth Versions API Hatası: {e}")
            return []

    @staticmethod
    def get_project_details(project_id):
        url = f"{ModrinthAPI.BASE_URL}/project/{project_id}"
        try:
            response = ModrinthAPI._get(url, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Modrinth Project API Hatası: {e}")
            return None

    @staticmethod
    def get_latest_version_file(project_id, game_version=None, loader=None):
        url = f"{ModrinthAPI.BASE_URL}/project/{project_id}/version"
        params = {}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader:
            if isinstance(loader, (list, tuple)):
                params["loaders"] = json.dumps([l.lower() for l in loader])
            elif str(loader).lower() == "quilt":
                params["loaders"] = json.dumps(["quilt", "fabric"])
            else:
                params["loaders"] = json.dumps([str(loader).lower()])

        try:
            response = ModrinthAPI._get(url, params=params if params else None, timeout=15)
            response.raise_for_status()
            versions = response.json()

            if game_version:
                versions = [v for v in versions if game_version in v.get("game_versions", [])]
            if loader:
                if isinstance(loader, (list, tuple)):
                    req_loaders = [l.lower() for l in loader]
                elif str(loader).lower() == "quilt":
                    req_loaders = ["quilt", "fabric"]
                else:
                    req_loaders = [str(loader).lower()]
                versions = [
                    v for v in versions
                    if any(rl in [l.lower() for l in v.get("loaders", [])] for rl in req_loaders)
                ]

            if not versions:
                return None

            latest_version = versions[0]
            files = latest_version.get("files", [])
            if not files:
                return None

            for f in files:
                if f.get("primary"):
                    res = dict(f)
                    res["version_id"] = latest_version.get("id")
                    return res
            res = dict(files[0])
            res["version_id"] = latest_version.get("id")
            return res
        except Exception as e:
            print(f"Modrinth Version API Hatası: {e}")
            return None

    @staticmethod
    def download_file(url, dest_path):
        part_path = f"{dest_path}.part"
        try:
            response = ModrinthAPI._get(url, stream=True, timeout=30)
            response.raise_for_status()
            with open(part_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            if os.path.exists(dest_path):
                os.remove(dest_path)
            os.replace(part_path, dest_path)
            return True
        except Exception as e:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass
            print(f"İndirme Hatası: {e}")
            return False


def find_existing_mod_files(dest_dir: str | Path, filename: str) -> list[str]:
    if not os.path.isdir(str(dest_dir)):
        return []
    base_match = re.match(r"^([a-zA-Z0-9_\-]+?)(?:[-_]v?\d|\.jar|\.zip)", filename, re.IGNORECASE)
    mod_stem = base_match.group(1).lower() if base_match else filename.lower().replace(".jar", "")
    found = []
    try:
        for f in os.listdir(dest_dir):
            if f.lower().endswith((".jar", ".zip")):
                f_match = re.match(r"^([a-zA-Z0-9_\-]+?)(?:[-_]v?\d|\.jar|\.zip)", f, re.IGNORECASE)
                f_stem = f_match.group(1).lower() if f_match else f.lower().replace(".jar", "")
                if f_stem == mod_stem or f.lower() == filename.lower():
                    found.append(f)
    except Exception:
        pass
    return found


class ContentCatalog:
    """
    Deep module encapsulating Modrinth catalog discovery, strict CompatibilityPolicy
    version resolution, atomic single-file Artifact installation, and ModpackArchive
    installation with TransactionalRollback.
    """
    def __init__(self, transport=None, loader_installer=None, mc_dir: Optional[str] = None):
        self.transport = transport or ModrinthAPI
        self.loader_installer = loader_installer or DefaultLoaderInstallerAdapter()
        self.mc_dir = mc_dir or os.path.join(os.getenv("APPDATA", ""), ".minecraft")
        self._active_runners: list[QThread] = []

    def search(
        self,
        query: str,
        policy: CompatibilityPolicy,
        index: str = "relevance",
        limit: int = 12,
        category: Optional[str] = None,
    ):
        ldr = list(policy.effective_loaders) if policy.effective_loaders else None
        if ldr and len(ldr) == 1:
            ldr = ldr[0]
        return self.transport.search_projects(
            query,
            project_type=policy.content_type if policy.content_type != "modpack_update" else "modpack",
            index=index,
            limit=limit,
            version=policy.game_version,
            loader=ldr,
            category=category,
        )

    def fetch_project_view(self, project_id: str, policy: CompatibilityPolicy) -> Optional[dict]:
        details = self.transport.get_project_details(project_id)
        if not details:
            return None
        ldr = list(policy.effective_loaders) if policy.effective_loaders else None
        if ldr and len(ldr) == 1:
            ldr = ldr[0]
        versions = self.transport.get_project_versions(
            project_id, game_version=policy.game_version, loader=ldr
        )
        if not versions and (policy.game_version or ldr):
            versions = self.transport.get_project_versions(project_id)
        if versions:
            details["versions_list"] = versions
        return details

    def resolve_artifact(
        self,
        project_id: str,
        policy: CompatibilityPolicy,
        selected_version_obj: Optional[dict] = None,
    ) -> Optional[Artifact]:
        # 1. Explicit version object picked in UI (e.g. DetailPanel modpack version selector)
        if selected_version_obj and selected_version_obj.get("files"):
            files = selected_version_obj["files"]
            chosen = None
            for f in files:
                if f.get("primary") or f.get("filename", "").endswith(".mrpack"):
                    chosen = f
                    break
            if not chosen:
                chosen = files[0]
            if chosen and chosen.get("url"):
                return Artifact(
                    project_id=project_id,
                    version_id=selected_version_obj.get("id", ""),
                    filename=chosen.get("filename", "pack.mrpack"),
                    url=chosen["url"],
                    content_type=policy.content_type,
                )

        # 2. Strict type-based CompatibilityPolicy resolution
        ctype = policy.content_type
        eff_loaders = list(policy.effective_loaders) if policy.effective_loaders else None
        if eff_loaders and len(eff_loaders) == 1:
            eff_loaders = eff_loaders[0]

        if ctype in ("mod", "plugin"):
            # Strict requirement: never fall back to unfiltered versions if a filter was specified
            if not policy.game_version or not eff_loaders:
                return None
            file_data = self.transport.get_latest_version_file(
                project_id, game_version=policy.game_version, loader=eff_loaders
            )
        elif ctype == "shader":
            if not policy.game_version:
                return None
            file_data = self.transport.get_latest_version_file(
                project_id, game_version=policy.game_version, loader=None
            )
        elif ctype == "modpack_update":
            # Modpack update: must match loader; prefers matching game_version first
            if not eff_loaders:
                return None
            file_data = None
            if policy.game_version:
                file_data = self.transport.get_latest_version_file(
                    project_id, game_version=policy.game_version, loader=eff_loaders
                )
            if not file_data:
                file_data = self.transport.get_latest_version_file(
                    project_id, game_version=None, loader=eff_loaders
                )
        else:
            # Initial modpack install with optional browser filters
            file_data = self.transport.get_latest_version_file(
                project_id, game_version=policy.game_version, loader=eff_loaders
            )

        if not file_data or not file_data.get("url"):
            return None

        return Artifact(
            project_id=project_id,
            version_id=file_data.get("version_id", ""),
            filename=file_data.get("filename", ""),
            url=file_data["url"],
            content_type=ctype,
        )

    def install_artifact(
        self,
        target_root: str | Path,
        policy: CompatibilityPolicy,
        *,
        project_id: Optional[str] = None,
        explicit_url: Optional[str] = None,
        explicit_filename: Optional[str] = None,
        overwrite: bool = False,
        lang: str = "tr",
    ) -> InstallResult:
        en = lang == "en"
        if explicit_url and explicit_filename:
            art = Artifact(
                project_id=project_id or "",
                version_id="",
                filename=explicit_filename,
                url=explicit_url,
                content_type=policy.content_type,
            )
        elif project_id:
            art = self.resolve_artifact(project_id, policy)
            if not art:
                ver_lbl = policy.game_version or ("All" if en else "Tümü")
                ldr_lbl = (
                    ", ".join(policy.effective_loaders)
                    if policy.effective_loaders
                    else ""
                )
                if en:
                    msg = f"No compatible file found for version {ver_lbl}"
                    if ldr_lbl:
                        msg += f" and {ldr_lbl.capitalize()} loader"
                    msg += "."
                else:
                    msg = f"Bu öğenin {ver_lbl} sürümü"
                    if ldr_lbl:
                        msg += f" ve {ldr_lbl.capitalize()} motoru"
                    msg += " için uyumlu bir dosyası bulunamadı."
                return InstallResult(ok=False, message=msg)
        else:
            return InstallResult(
                ok=False,
                message="No project or download URL specified." if en else "İndirilecek proje veya bağlantı belirtilmedi."
            )

        dest_dir = os.path.join(str(target_root), policy.target_subdir)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, art.filename)

        existing_files = find_existing_mod_files(dest_dir, art.filename)

        if not overwrite and (os.path.exists(dest_path) or existing_files):
            existing_name = art.filename if os.path.exists(dest_path) else existing_files[0]
            return InstallResult(
                ok=False,
                message=f"This item is already installed:\n{existing_name}" if en else f"Bu öğe zaten yüklenmiş:\n{existing_name}",
                version_id=art.version_id,
                filename=art.filename,
                already_exists=True,
                conflicting_file=existing_name,
            )

        if overwrite and existing_files:
            for old_name in existing_files:
                old_path = os.path.join(dest_dir, old_name)
                if old_path != dest_path and os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass

        ok = self.transport.download_file(art.url, dest_path)
        if ok:
            return InstallResult(
                ok=True,
                message=f"{art.filename} downloaded successfully!" if en else f"{art.filename} başarıyla indirildi!",
                version_id=art.version_id,
                filename=art.filename,
            )
        return InstallResult(
            ok=False,
            message="Download failed." if en else "İndirme başarısız oldu.",
            version_id=art.version_id,
            filename=art.filename,
        )

    @staticmethod
    def _download_archive_entries(
        files: list[dict],
        is_curseforge: bool,
        base_prof: str,
        _emit_status: Callable[[str], None],
        _emit_val: Callable[[int, int], None],
        _cancelled: Callable[[], bool],
        cancel_item_msg: str,
        en: bool,
    ) -> list[str]:
        total = len(files)
        completed = [0]
        lock = threading.Lock()
        failed_mods: list[str] = []

        def _download_single(file_info: dict) -> tuple[bool, str]:
            if _cancelled():
                return False, cancel_item_msg

            if is_curseforge:
                pid = file_info.get("projectID") or file_info.get("projectId")
                fid = file_info.get("fileID") or file_info.get("fileId")
                if not pid or not fid:
                    return True, ""
                api_dl = CurseForgeAPI.get_file_download_url(pid, fid)
                cf_url = api_dl or f"https://www.curseforge.com/api/v1/mods/{pid}/files/{fid}/download"
                dl_url = cf_url
                file_basename = f"{pid}-{fid}.jar"
                is_cf = True
            else:
                path = file_info.get("path")
                downloads = file_info.get("downloads", [])
                file_basename = os.path.basename(path) if path else ("Unknown File" if en else "Bilinmeyen Dosya")
                if not path or not downloads:
                    return False, file_basename + (" (No download link)" if en else " (İndirme linki yok)")
                dl_url = downloads[0]
                is_cf = False

            for _attempt in range(3):
                if _cancelled():
                    return False, cancel_item_msg
                try:
                    cf_url = dl_url
                    fr = requests.get(cf_url, headers=ModrinthAPI.HEADERS, timeout=20, allow_redirects=is_cf)
                    fr.raise_for_status()

                    if is_cf:
                        parsed_url = urllib.parse.urlparse(fr.url)
                        parsed_name = os.path.basename(parsed_url.path)
                        if parsed_name and parsed_name.endswith(".jar"):
                            file_basename = parsed_name
                        target_path = os.path.realpath(os.path.join(base_prof, "mods", file_basename))
                    else:
                        target_path = os.path.realpath(os.path.join(base_prof, file_info.get("path", "")))

                    if not target_path.startswith(base_prof + os.sep):
                        err_label = f"Project ID: {file_info.get('projectID')}" if is_cf else file_basename
                        return False, f"{err_label} (Invalid file path)" if en else f"{err_label} (Geçersiz dosya yolu)"
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)

                    with open(target_path, "wb") as f_out:
                        f_out.write(fr.content)

                    with lock:
                        completed[0] += 1
                        prefix = "CurseForge: " if is_cf else ""
                        _emit_status(
                            f"Downloading: {prefix}{file_basename} ({completed[0]}/{total})"
                            if en else
                            f"İndiriliyor: {prefix}{file_basename} ({completed[0]}/{total})"
                        )
                        _emit_val(completed[0], total)
                    return True, ""
                except Exception:
                    pass

            fail_id = f"Project ID: {file_info.get('projectID', 'unknown')}" if is_cf else file_basename
            return False, fail_id

        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            results = list(executor.map(_download_single, files))
            for ok, msg in results:
                if not ok:
                    failed_mods.append(msg)

        return failed_mods

    def install_modpack(
        self,
        profile_dir: str | Path,
        pack_source: str,
        *,
        is_local: bool = False,
        is_update: bool = False,
        on_progress: Optional[Callable[[str], None]] = None,
        on_progress_val: Optional[Callable[[int, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        lang: str = "tr",
    ) -> InstallResult:
        en = lang == "en"
        cancel_res_msg = "Modpack installation cancelled." if en else "Modpack kurulumu iptal edildi."
        cancel_item_msg = "Cancelled" if en else "İptal edildi"

        def _emit_status(txt: str):
            if on_progress:
                on_progress(txt)

        def _emit_val(cur: int, tot: int):
            if on_progress_val:
                on_progress_val(cur, tot)

        def _cancelled() -> bool:
            return bool(is_cancelled and is_cancelled())

        rollback_mgr = TransactionalRollback(profile_dir, enabled=is_update)
        rollback_mgr.__enter__()
        try:
            with tempfile.TemporaryDirectory() as tmpdirname:
                if is_local:
                    mrpack_path = pack_source
                else:
                    _emit_status("Downloading modpack archive..." if en else "Modpack arşivi indiriliyor...")
                    _emit_val(0, 0)
                    r = requests.get(pack_source, headers=ModrinthAPI.HEADERS, timeout=30)
                    r.raise_for_status()
                    mrpack_path = os.path.join(tmpdirname, "pack.zip")
                    with open(mrpack_path, "wb") as f:
                        f.write(r.content)

                if _cancelled():
                    rollback_mgr.rollback()
                    return InstallResult(
                        ok=False,
                        message=cancel_res_msg,
                        rolled_back=rollback_mgr.rolled_back,
                    )

                _emit_status("Extracting archive..." if en else "Arşiv açılıyor...")
                _emit_val(0, 0)
                try:
                    ContentCatalog.extract_zip_safely(mrpack_path, tmpdirname)
                except Exception as e:
                    rollback_mgr.rollback()
                    return InstallResult(
                        ok=False,
                        message=f"Archive extraction failed: {e}" if en else f"Arşiv açma başarısız: {e}",
                        rolled_back=rollback_mgr.rolled_back,
                    )

                mr_index_path = None
                cf_index_path = None
                for root, _dirs, files_in_dir in os.walk(tmpdirname):
                    if "modrinth.index.json" in files_in_dir:
                        mr_index_path = os.path.join(root, "modrinth.index.json")
                        break
                    elif "manifest.json" in files_in_dir:
                        cf_index_path = os.path.join(root, "manifest.json")
                        break

                is_curseforge = False
                if cf_index_path:
                    is_curseforge = True
                    with open(cf_index_path, "r", encoding="utf-8") as f:
                        index = json.load(f)
                    tmpdirname = os.path.dirname(cf_index_path)
                elif mr_index_path:
                    with open(mr_index_path, "r", encoding="utf-8") as f:
                        index = json.load(f)
                    tmpdirname = os.path.dirname(mr_index_path)
                else:
                    raise Exception(
                        "No valid Modpack format found! (modrinth.index.json or manifest.json missing)"
                        if en else
                        "Geçerli bir Modpack formatı bulunamadı! (modrinth.index.json veya manifest.json eksik)"
                    )

                new_version_id = ""
                failed_mods = []
                base_prof = os.path.realpath(str(profile_dir))

                if not is_curseforge:
                    deps = index.get("dependencies", {})
                    mc_version = deps.get("minecraft", "1.20.1")
                    forge_version = deps.get("forge")
                    fabric_version = deps.get("fabric-loader")
                    quilt_version = deps.get("quilt-loader")
                    neoforge_version = deps.get("neoforge")

                    if fabric_version:
                        _emit_val(0, 0)
                        new_version_id = self.loader_installer.install(
                            mc_version, "fabric", fabric_version, self.mc_dir, on_progress=_emit_status
                        )
                    elif quilt_version:
                        _emit_val(0, 0)
                        new_version_id = self.loader_installer.install(
                            mc_version, "quilt", quilt_version, self.mc_dir, on_progress=_emit_status
                        )
                    elif neoforge_version:
                        _emit_val(0, 0)
                        new_version_id = self.loader_installer.install(
                            mc_version, "neoforge", neoforge_version, self.mc_dir, on_progress=_emit_status
                        )
                    elif forge_version:
                        _emit_val(0, 0)
                        new_version_id = self.loader_installer.install(
                            mc_version, "forge", forge_version, self.mc_dir, on_progress=_emit_status
                        )
                    else:
                        new_version_id = mc_version

                    _emit_status(
                        f"Reading requirements: MC {mc_version}, Loader: {new_version_id}"
                        if en else
                        f"Gereksinimler okunuyor: MC {mc_version}, Yükleyici: {new_version_id}"
                    )

                    files = index.get("files", [])
                    failed_mods.extend(
                        self._download_archive_entries(
                            files, False, base_prof, _emit_status, _emit_val, _cancelled, cancel_item_msg, en
                        )
                    )
                else:
                    mc_info = index.get("minecraft", {})
                    mc_version = mc_info.get("version", "1.20.1")
                    loaders = mc_info.get("modLoaders", [])

                    new_version_id = mc_version
                    if loaders:
                        loader_id = loaders[0].get("id", "")
                        if loader_id.startswith("forge-"):
                            forge_version = loader_id.split("-")[1]
                            _emit_val(0, 0)
                            new_version_id = self.loader_installer.install(
                                mc_version, "forge", forge_version, self.mc_dir, on_progress=_emit_status
                            )
                        elif loader_id.startswith("fabric-"):
                            fabric_version = loader_id.split("-")[1]
                            _emit_val(0, 0)
                            new_version_id = self.loader_installer.install(
                                mc_version, "fabric", fabric_version, self.mc_dir, on_progress=_emit_status
                            )
                        else:
                            new_version_id = loader_id

                    _emit_status(
                        f"Reading requirements: Loader: {new_version_id}"
                        if en else
                        f"Gereksinimler okunuyor: Yükleyici: {new_version_id}"
                    )

                    files = index.get("files", [])
                    failed_mods.extend(
                        self._download_archive_entries(
                            files, True, base_prof, _emit_status, _emit_val, _cancelled, cancel_item_msg, en
                        )
                    )

                if _cancelled():
                    rollback_mgr.rollback()
                    return InstallResult(
                        ok=False,
                        message=cancel_res_msg,
                        rolled_back=rollback_mgr.rolled_back,
                    )

                _emit_status(
                    "Copying settings, worlds, and config files..."
                    if en else
                    "Ayarlar, Haritalar ve Config dosyaları kopyalanıyor..."
                )
                _emit_val(0, 0)
                for override_folder in ["overrides", "client-overrides"]:
                    overrides_dir = os.path.join(tmpdirname, override_folder)
                    if not os.path.exists(overrides_dir):
                        continue
                    for root, _dirs, files_in_dir in os.walk(overrides_dir):
                        for file in files_in_dir:
                            src_file = os.path.join(root, file)
                            rel_path = os.path.relpath(src_file, overrides_dir)
                            dst_file = os.path.realpath(os.path.join(base_prof, rel_path))
                            if dst_file.startswith(base_prof + os.sep):
                                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                                shutil.copy2(src_file, dst_file)

            if _cancelled():
                rollback_mgr.rollback()
                return InstallResult(
                    ok=False,
                    message=cancel_res_msg,
                    rolled_back=rollback_mgr.rolled_back,
                )

            rollback_mgr.commit()
            if failed_mods:
                if en:
                    msg = (
                        "Modpack installed, but some mods could not be downloaded (they may have been removed from the server):\n"
                        + ", ".join(failed_mods[:5])
                    )
                    if len(failed_mods) > 5:
                        msg += f" ... and {len(failed_mods) - 5} more."
                else:
                    msg = (
                        "Modpack kuruldu, ancak bazı modlar indirilemedi (Sunucudan silinmiş olabilirler):\n"
                        + ", ".join(failed_mods[:5])
                    )
                    if len(failed_mods) > 5:
                        msg += f" ... ve {len(failed_mods) - 5} tane daha."
                return InstallResult(ok=True, message=msg, version_id=new_version_id)
            return InstallResult(
                ok=True,
                message="Modpack installed successfully!" if en else "Modpack başarıyla kuruldu!",
                version_id=new_version_id
            )

        except Exception as e:
            rollback_mgr.rollback()
            return InstallResult(
                ok=False,
                message=f"Modpack installation error: {str(e)}" if en else f"Modpack kurulum hatası: {str(e)}",
                rolled_back=rollback_mgr.rolled_back,
            )

    def check_updates(
        self,
        profiles: dict[str, dict],
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> list[tuple[str, Artifact]]:
        updates: list[tuple[str, Artifact]] = []
        for profile_id, pdata in list(profiles.items()):
            if is_cancelled and is_cancelled():
                break
            project_id = pdata.get("project_id")
            current_version_id = pdata.get("version_id")
            if not (project_id and current_version_id):
                continue

            policy = CompatibilityPolicy.for_profile(pdata, "modpack_update")
            art = self.resolve_artifact(project_id, policy)
            if is_cancelled and is_cancelled():
                break
            if art and art.version_id and art.version_id != current_version_id:
                updates.append((profile_id, art))
        return updates

    @staticmethod
    def extract_zip_safely(
        zip_path: str,
        target_dir: str,
        pattern: Optional[Callable[[str], bool]] = None,
        flatten: bool = False,
    ) -> list[str]:
        """
        Safely extracts entries from a zip archive ensuring no path traversal (Zip Slip).
        Returns a list of extracted file names.
        """
        extracted = []
        real_target = os.path.realpath(target_dir)
        os.makedirs(real_target, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for zip_info in zip_ref.infolist():
                if zip_info.is_dir():
                    continue
                filename = zip_info.filename
                if pattern and not pattern(filename):
                    continue
                if flatten:
                    base_name = os.path.basename(filename)
                    if not base_name or ".." in base_name:
                        continue
                    dest = os.path.realpath(os.path.join(real_target, base_name))
                    if not (dest.startswith(real_target + os.sep) or dest == real_target):
                        continue
                    zip_info.filename = base_name
                    zip_ref.extract(zip_info, real_target)
                    extracted.append(base_name)
                else:
                    dest = os.path.realpath(os.path.join(real_target, filename))
                    if not (dest.startswith(real_target + os.sep) or dest == real_target):
                        continue
                    zip_ref.extract(zip_info, real_target)
                    extracted.append(filename)
        return extracted

    def run_async(
        self,
        task_fn: Callable[[], object],
        on_success: Optional[Callable[[object], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> "CatalogTaskRunner":
        runner = CatalogTaskRunner(task_fn)
        self._active_runners.append(runner)
        def _cleanup(*_):
            if runner in self._active_runners:
                self._active_runners.remove(runner)
        runner.task_finished.connect(_cleanup)
        runner.task_failed.connect(_cleanup)
        if on_success:
            runner.task_finished.connect(lambda res=None: on_success(res))
        if on_error:
            runner.task_failed.connect(lambda err="": on_error(err))
        runner.start()
        return runner


DEFAULT_CATALOG = ContentCatalog()
DEFAULT_CURSEFORGE_CATALOG = ContentCatalog(transport=CurseForgeAPI)


# --- Unified Qt Background Task Adapters ---

class CatalogTaskRunner(QThread):
    """
    Unified asynchronous task runner for ContentCatalog operations.
    Hides background thread boilerplate behind a single seam.
    """
    task_finished = Signal(object)
    task_failed = Signal(str)

    def __init__(self, task_fn: Callable[[], object], parent=None):
        super().__init__(parent)
        self.task_fn = task_fn

    def run(self):
        try:
            res = self.task_fn()
            self.task_finished.emit(res)
        except Exception as e:
            self.task_failed.emit(str(e))

class ModrinthSearchThread(QThread):
    search_finished = Signal(object)

    def __init__(
        self,
        query: str,
        project_type: str = "mod",
        index: str = "relevance",
        limit: int = 20,
        version: Optional[str] = None,
        loader: Optional[str] = None,
        category: Optional[str] = None,
        *,
        game_version: Optional[str] = None,
        catalog: Optional[ContentCatalog] = None,
    ):
        super().__init__()
        self.query = query
        self.project_type = project_type
        self.index = index
        self.limit = limit
        self.version = game_version if game_version is not None else version
        self.loader = loader
        self.category = category
        self.catalog = catalog or DEFAULT_CATALOG

    def run(self):
        try:
            eff_version = None if self.project_type == "plugin" else self.version
            eff_loader = None if self.project_type in ("plugin", "shader") else self.loader
            policy = CompatibilityPolicy(
                content_type=self.project_type,
                game_version=eff_version,
                loader=eff_loader,
            )
            results = self.catalog.search(
                self.query,
                policy,
                index=self.index,
                limit=self.limit,
                category=self.category,
            )
            self.search_finished.emit(results)
        except Exception:
            self.search_finished.emit(None)


class ProjectDetailsThread(QThread):
    task_finished = Signal(dict)

    def __init__(
        self,
        project_id: str,
        version: Optional[str] = None,
        loader: Optional[str] = None,
        *,
        catalog: Optional[ContentCatalog] = None,
    ):
        super().__init__()
        self.project_id = project_id
        self.version = version
        self.loader = loader
        self.catalog = catalog or DEFAULT_CATALOG

    def run(self):
        try:
            policy = CompatibilityPolicy(
                content_type="modpack",
                game_version=self.version,
                loader=self.loader,
            )
            details = self.catalog.fetch_project_view(self.project_id, policy)
            if details:
                self.task_finished.emit(details)
        except Exception:
            pass


class DownloadModThread(QThread):
    task_finished = Signal(bool, str)

    def __init__(
        self,
        url: Optional[str] = None,
        path: Optional[str] = None,
        *,
        project_id: Optional[str] = None,
        target_root: Optional[str] = None,
        policy: Optional[CompatibilityPolicy] = None,
        catalog: Optional[ContentCatalog] = None,
        overwrite: bool = False,
        lang: str = "tr",
    ):
        super().__init__()
        self.url = url
        self.path = path
        self.project_id = project_id
        self.target_root = target_root
        self.policy = policy
        self.catalog = catalog or DEFAULT_CATALOG
        self.overwrite = overwrite
        self.lang = lang
        self.last_result: Optional[InstallResult] = None

    def run(self):
        en = self.lang == "en"
        if self.project_id and self.target_root and self.policy:
            res = self.catalog.install_artifact(
                self.target_root,
                self.policy,
                project_id=self.project_id,
                overwrite=self.overwrite,
                lang=self.lang,
            )
            self.last_result = res
            self.task_finished.emit(res.ok, res.message)
            return

        success = self.catalog.transport.download_file(self.url, self.path)
        if success:
            self.task_finished.emit(True, "Download successful." if en else "İndirme başarılı.")
        else:
            self.task_finished.emit(False, "Download failed." if en else "İndirme başarısız.")


class ModrinthDownloadThread(QThread):
    download_finished = Signal(bool, str)

    def __init__(
        self,
        project_id: str,
        server_dir: str,
        project_type: str,
        game_version: Optional[str] = None,
        loader: Optional[str] = None,
        *,
        catalog: Optional[ContentCatalog] = None,
        lang: str = "tr",
    ):
        super().__init__()
        self.project_id = project_id
        self.server_dir = server_dir
        self.project_type = project_type
        self.game_version = game_version
        self.loader = loader
        self.catalog = catalog or DEFAULT_CATALOG
        self.lang = lang

    def run(self):
        en = self.lang == "en"
        try:
            if self.project_type == "mod":
                policy = CompatibilityPolicy(
                    content_type="mod",
                    game_version=self.game_version,
                    loader=self.loader,
                )
                res = self.catalog.install_artifact(
                    self.server_dir,
                    policy,
                    project_id=self.project_id,
                    overwrite=True,
                    lang=self.lang,
                )
                self.download_finished.emit(res.ok, res.message)
            else:
                # Plugin download for Paper/Purpur/Spigot servers
                latest_file = self.catalog.transport.get_latest_version_file(
                    self.project_id,
                    game_version=self.game_version,
                    loader=None,
                )
                if not latest_file:
                    latest_file = self.catalog.transport.get_latest_version_file(self.project_id)
                if not latest_file or not latest_file.get("url") or not latest_file.get("filename"):
                    self.download_finished.emit(
                        False,
                        "No compatible plugin found for this server!" if en else "Bu sunucu için uyumlu eklenti bulunamadı!"
                    )
                    return
                policy = CompatibilityPolicy(content_type="plugin")
                res = self.catalog.install_artifact(
                    self.server_dir,
                    policy,
                    explicit_url=latest_file["url"],
                    explicit_filename=latest_file["filename"],
                    overwrite=True,
                    lang=self.lang,
                )
                self.download_finished.emit(res.ok, res.message)
        except Exception as e:
            self.download_finished.emit(False, f"Error: {str(e)}" if en else f"Hata: {str(e)}")


class DownloadModpackThread(QThread):
    progress_update = Signal(str)
    progress_val = Signal(int, int)
    task_finished = Signal(bool, str, str)  # success, message, version_id

    def __init__(
        self,
        profile_dir: str,
        pack_url: Optional[str] = None,
        is_local: bool = False,
        *,
        is_update: bool = False,
        project_id: Optional[str] = None,
        policy: Optional[CompatibilityPolicy] = None,
        selected_version_obj: Optional[dict] = None,
        catalog: Optional[ContentCatalog] = None,
        lang: str = "tr",
    ):
        super().__init__()
        self.profile_dir = profile_dir
        self.pack_url = pack_url
        self.is_local = is_local
        self.is_update = is_update
        self.project_id = project_id
        self.policy = policy
        self.selected_version_obj = selected_version_obj
        self.catalog = catalog or DEFAULT_CATALOG
        self.lang = lang
        self.resolved_version_id: Optional[str] = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        en = self.lang == "en"
        source = self.pack_url
        if not self.is_local and self.project_id and self.policy:
            self.progress_update.emit("Verifying compatible modpack version..." if en else "Uyumlu modpack sürümü doğrulanıyor...")
            self.progress_val.emit(0, 0)
            art = self.catalog.resolve_artifact(
                self.project_id,
                self.policy,
                selected_version_obj=self.selected_version_obj,
            )
            if not art:
                all_lbl = "All" if en else "Tümü"
                ldr = ", ".join(self.policy.effective_loaders) if self.policy.effective_loaders else all_lbl
                ver = self.policy.game_version or all_lbl
                self.task_finished.emit(
                    False,
                    (
                        f"No compatible version found for this modpack.\n(Filters: {ver} / {ldr})"
                        if en else
                        f"Bu modpack için uyumlu bir sürüm bulunamadı.\n(Filtreler: {ver} / {ldr})"
                    ),
                    "",
                )
                return
            source = art.url
            self.resolved_version_id = art.version_id

        if not source:
            self.task_finished.emit(
                False,
                "Modpack download link not found." if en else "Modpack indirme bağlantısı bulunamadı.",
                ""
            )
            return

        res = self.catalog.install_modpack(
            self.profile_dir,
            source,
            is_local=self.is_local,
            is_update=self.is_update,
            on_progress=self.progress_update.emit,
            on_progress_val=self.progress_val.emit,
            is_cancelled=lambda: self._cancelled,
            lang=self.lang,
        )
        self.task_finished.emit(res.ok, res.message, res.version_id)


class UpdateCheckerThread(QThread):
    # profile_id, new_version_id, new_file_url
    update_available = Signal(str, str, str)

    def __init__(self, profiles: dict, *, catalog: Optional[ContentCatalog] = None):
        super().__init__()
        self.profiles_snapshot = dict(profiles)
        self.catalog = catalog or DEFAULT_CATALOG
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        try:
            updates = self.catalog.check_updates(
                self.profiles_snapshot,
                is_cancelled=lambda: not self._is_running,
            )
            for profile_id, art in updates:
                if not self._is_running:
                    break
                self.update_available.emit(profile_id, art.version_id, art.url)
        except Exception as e:
            print(f"UpdateCheckerThread Hatası: {e}")

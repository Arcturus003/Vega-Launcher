from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal


@dataclass
class PrismInstanceInfo:
    """Represents a discovered Prism Launcher or MultiMC instance."""
    id: str
    name: str
    version: str
    loader: str
    loader_version: str
    ram: int
    path: str
    game_dir: str
    mod_count: int = 0
    world_count: int = 0
    icon_key: str = "default"


class PrismInstanceImporter:
    """
    Scans for Prism Launcher / MultiMC instances, parses their instance.cfg & mmc-pack.json,
    and performs clean, isolated copies into Vega Launcher's profile directory.
    """

    ALLOWED_DIRS = {
        "mods",
        "saves",
        "config",
        "defaultconfigs",
        "resourcepacks",
        "shaderpacks",
        "schematics",
        "blueprints",
    }
    ALLOWED_FILES = {
        "options.txt",
        "servers.dat",
        "hotbar.nbt",
    }

    @classmethod
    def get_default_search_paths(cls) -> List[str]:
        paths = []
        appdata = os.getenv("APPDATA")
        localappdata = os.getenv("LOCALAPPDATA")
        home = os.path.expanduser("~")

        candidates = [
            os.path.join(appdata, "PrismLauncher", "instances") if appdata else None,
            os.path.join(appdata, "MultiMC", "instances") if appdata else None,
            os.path.join(localappdata, "PrismLauncher", "instances") if localappdata else None,
            os.path.join(home, ".local", "share", "PrismLauncher", "instances"),
            os.path.join(home, ".local", "share", "multimc", "instances"),
        ]

        for p in candidates:
            if p and os.path.isdir(p) and p not in paths:
                paths.append(p)
        return paths

    @classmethod
    def find_game_dir(cls, instance_path: str) -> str:
        for sub in [".minecraft", "minecraft"]:
            candidate = os.path.join(instance_path, sub)
            if os.path.isdir(candidate):
                return candidate
        return instance_path

    @classmethod
    def parse_instance_cfg(cls, cfg_path: str) -> Dict[str, str]:
        props: Dict[str, str] = {}
        if not os.path.isfile(cfg_path):
            return props

        try:
            with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith(("#", "[")) and "=" in line:
                        k, _, v = line.partition("=")
                        props[k.strip()] = v.strip()
        except Exception:
            pass
        return props

    @classmethod
    def parse_mmc_pack(cls, pack_path: str) -> Tuple[str, str, str]:
        """Returns (mc_version, loader, loader_version)."""
        if not os.path.isfile(pack_path):
            return "1.20.1", "vanilla", ""

        mc_version = "1.20.1"
        loader = "vanilla"
        loader_version = ""

        try:
            with open(pack_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                components = data.get("components", [])
                for comp in components:
                    uid = comp.get("uid", "")
                    ver = comp.get("version", "")
                    if uid == "net.minecraft":
                        mc_version = ver or mc_version
                    elif "neoforge" in uid:
                        loader = "neoforge"
                        loader_version = ver
                    elif "fabric-loader" in uid:
                        loader = "fabric"
                        loader_version = ver
                    elif "forge" in uid:
                        loader = "forge"
                        loader_version = ver
                    elif "quilt" in uid:
                        loader = "quilt"
                        loader_version = ver
        except Exception:
            pass

        return mc_version, loader, loader_version

    @classmethod
    def discover_instances(cls, search_paths: Optional[List[str]] = None) -> List[PrismInstanceInfo]:
        paths = search_paths if search_paths is not None else cls.get_default_search_paths()
        discovered: List[PrismInstanceInfo] = []

        for base_path in paths:
            if not os.path.isdir(base_path):
                continue

            for dir_name in os.listdir(base_path):
                inst_dir = os.path.join(base_path, dir_name)
                if not os.path.isdir(inst_dir):
                    continue

                cfg_path = os.path.join(inst_dir, "instance.cfg")
                pack_path = os.path.join(inst_dir, "mmc-pack.json")

                if not os.path.exists(cfg_path) and not os.path.exists(pack_path):
                    continue

                cfg = cls.parse_instance_cfg(cfg_path)
                display_name = cfg.get("name") or dir_name
                icon_key = cfg.get("iconKey", "default")
                ram = 4096
                try:
                    ram = int(cfg.get("MaxMemAlloc", 4096) or 4096)
                except ValueError:
                    ram = 4096

                mc_ver, loader, loader_ver = cls.parse_mmc_pack(pack_path)
                game_dir = cls.find_game_dir(inst_dir)

                # Count mods
                mod_count = 0
                mods_path = os.path.join(game_dir, "mods")
                if os.path.isdir(mods_path):
                    try:
                        mod_count = len([f for f in os.listdir(mods_path) if f.lower().endswith(".jar")])
                    except Exception:
                        mod_count = 0

                # Count worlds
                world_count = 0
                saves_path = os.path.join(game_dir, "saves")
                if os.path.isdir(saves_path):
                    try:
                        world_count = len([d for d in os.listdir(saves_path) if os.path.isdir(os.path.join(saves_path, d))])
                    except Exception:
                        world_count = 0

                discovered.append(
                    PrismInstanceInfo(
                        id=dir_name,
                        name=display_name,
                        version=mc_ver,
                        loader=loader,
                        loader_version=loader_ver,
                        ram=ram,
                        path=inst_dir,
                        game_dir=game_dir,
                        mod_count=mod_count,
                        world_count=world_count,
                        icon_key=icon_key,
                    )
                )

        return discovered

    @classmethod
    def import_instance(
        cls,
        info: PrismInstanceInfo,
        target_profiles_dir: str,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Copies games files selectively from Prism instance into target_profiles_dir
        and returns Vega Launcher profile metadata dictionary.
        """
        # Sanitize folder name (strip trailing dots/spaces for Windows filesystem safety)
        clean_name = re.sub(r'[<>:"/\\|?*]', '_', info.name).strip(". ") or info.id
        dest_dir = os.path.join(target_profiles_dir, clean_name)
        counter = 1
        orig_dest = dest_dir
        while os.path.exists(dest_dir):
            dest_dir = f"{orig_dest}_{counter}"
            counter += 1

        os.makedirs(dest_dir, exist_ok=True)

        source_game_dir = info.game_dir
        items_to_copy: List[str] = []

        # Find items
        if os.path.isdir(source_game_dir):
            for item in os.listdir(source_game_dir):
                item_lower = item.lower()
                full_path = os.path.join(source_game_dir, item)
                if os.path.isdir(full_path) and item_lower in cls.ALLOWED_DIRS:
                    items_to_copy.append(item)
                elif os.path.isfile(full_path) and item_lower in cls.ALLOWED_FILES:
                    items_to_copy.append(item)

        total_items = max(1, len(items_to_copy))
        try:
            for idx, item in enumerate(items_to_copy):
                if is_cancelled and is_cancelled():
                    raise RuntimeError("Import cancelled by user.")

                src = os.path.join(source_game_dir, item)
                dst = os.path.join(dest_dir, item)

                if on_progress:
                    on_progress(idx, total_items, f"Copying {item}...")

                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif os.path.isfile(src):
                    shutil.copy2(src, dst)
        except Exception as err:
            try:
                if os.path.isdir(dest_dir):
                    shutil.rmtree(dest_dir, ignore_errors=True)
            except Exception:
                pass
            raise err

        if on_progress:
            on_progress(total_items, total_items, "Completed!")

        return {
            "name": info.name,
            "version": info.version,
            "loader": info.loader,
            "loader_version": info.loader_version,
            "ram": info.ram,
            "path": dest_dir,
            "icon": "🎮",
            "banner": "",
        }


class InstanceImportWorkerThread(QThread):
    """Background worker for copying large modpacks and worlds without freezing UI."""
    progress = Signal(int, int, str)
    finished_import = Signal(bool, object, str)  # success, profile_dict, error_msg

    def __init__(self, info: PrismInstanceInfo, target_profiles_dir: str, parent=None):
        super().__init__(parent)
        self.info = info
        self.target_profiles_dir = target_profiles_dir
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            profile = PrismInstanceImporter.import_instance(
                self.info,
                self.target_profiles_dir,
                on_progress=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
                is_cancelled=lambda: self._is_cancelled,
            )
            self.finished_import.emit(True, profile, "")
        except Exception as e:
            self.finished_import.emit(False, None, str(e))

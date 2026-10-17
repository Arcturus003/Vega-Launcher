from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from auth_window import needs_rebind_token, protect_token, unprotect_token


DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "tr",
    "window_size": "auto",
    "last_width": 1350,
    "last_height": 755,
    "on_launch": "minimize",
    "default_ram": 4096,
    "java_path": "",
    "jvm_args": "",
    "custom_bg": "",
    "last_server": "",
    "theme": "electric_amethyst",
    "particles_enabled": True,
    "particle_preset": "portal",
    "particle_opacity": 50,
    "sound_enabled": True,
    "sound_volume": 70,
}


class ProfileAndConfigStore:
    """
    Deep module responsible for launcher_config.json persistence, DPAPI token
    protection/migration, profile directory discovery & path-contained deletion,
    and atomic synchronization with standard Minecraft launchers.
    """

    def __init__(
        self,
        data_dir: Optional[str | Path] = None,
        config_file: Optional[str | Path] = None,
        profiles_dir: Optional[str | Path] = None,
        mc_dir: Optional[str | Path] = None,
        protect_fn: Optional[Callable[[str], str]] = None,
        unprotect_fn: Optional[Callable[[str], str]] = None,
    ):
        self.data_dir = str(data_dir) if data_dir else os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), ".vega_launcher")
        self.config_file = str(config_file) if config_file else os.path.join(self.data_dir, "launcher_config.json")
        self.profiles_dir = str(profiles_dir) if profiles_dir else os.path.join(self.data_dir, "profiles")
        self.mc_dir = str(mc_dir) if mc_dir else os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), ".minecraft")
        self.protect_fn = protect_fn or protect_token
        self.unprotect_fn = unprotect_fn or unprotect_token

    def ensure_directories(self, initial_settings: Optional[dict] = None) -> None:
        os.makedirs(self.profiles_dir, exist_ok=True)
        if not os.path.exists(self.config_file):
            os.makedirs(os.path.dirname(os.path.abspath(self.config_file)), exist_ok=True)
            settings_to_write = dict(DEFAULT_SETTINGS)
            if isinstance(initial_settings, dict):
                settings_to_write.update(initial_settings)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"profiles": {}, "ms_login": {}, "settings": settings_to_write},
                    f,
                    indent=4,
                )

    def read_raw_config(self) -> dict[str, Any]:
        if not os.path.exists(self.config_file):
            return {"profiles": {}, "ms_login": {}, "settings": dict(DEFAULT_SETTINGS)}
        try:
            with open(self.config_file, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"profiles": {}, "ms_login": {}, "settings": dict(DEFAULT_SETTINGS)}
            return data
        except Exception:
            return {"profiles": {}, "ms_login": {}, "settings": dict(DEFAULT_SETTINGS)}

    def load(self) -> tuple[dict[str, dict], dict[str, Any], dict[str, Any]]:
        settings = dict(DEFAULT_SETTINGS)
        profiles: dict[str, dict] = {}
        ms_login: dict[str, Any] = {}

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    raw_profiles = data.get("profiles", {})
                    raw_ms_login = data.get("ms_login", {})
                    loaded_settings = data.get("settings", {})
                    if isinstance(loaded_settings, dict):
                        settings.update(loaded_settings)
                    if isinstance(raw_profiles, dict):
                        profiles = raw_profiles
                    if isinstance(raw_ms_login, dict):
                        ms_login = dict(raw_ms_login)
                        migrated_tokens = False
                        raw_acc = ms_login.get("access_token", "")
                        raw_ref = ms_login.get("refresh_token", "")
                        if raw_acc:
                            if needs_rebind_token(str(raw_acc)):
                                migrated_tokens = True
                            dec_acc = self.unprotect_fn(raw_acc)
                            if dec_acc:
                                ms_login["access_token"] = dec_acc
                            else:
                                ms_login.pop("access_token", None)
                                migrated_tokens = True
                        if raw_ref:
                            if needs_rebind_token(str(raw_ref)):
                                migrated_tokens = True
                            dec_ref = self.unprotect_fn(raw_ref)
                            if dec_ref:
                                ms_login["refresh_token"] = dec_ref
                            else:
                                ms_login.pop("refresh_token", None)
                                migrated_tokens = True
                        if migrated_tokens and sys.platform == "win32":
                            self.save(profiles, ms_login, settings)

                    for pid, pdata in profiles.items():
                        if isinstance(pdata, dict):
                            folder_name = pdata.get("name") or pid
                            if pdata.get("path"):
                                folder_name = os.path.basename(pdata["path"])
                            pdata["path"] = os.path.join(self.profiles_dir, folder_name)
            except Exception as e:
                print(e)
                profiles = {}
                ms_login = {}

        # Auto-discover unindexed profile directories on disk
        existing_names = {
            os.path.basename(p.get("path", ""))
            for p in profiles.values()
            if isinstance(p, dict)
        }
        def_ram = int(settings.get("default_ram", 4096) or 4096)
        if os.path.exists(self.profiles_dir):
            for d in os.listdir(self.profiles_dir):
                full_d = os.path.join(self.profiles_dir, d)
                if os.path.isdir(full_d) and d not in existing_names:
                    profiles[str(uuid.uuid4())] = {
                        "name": d,
                        "version": "1.20.1",
                        "ram": def_ram,
                        "path": full_d,
                    }
            self.save(profiles, ms_login, settings)

        return profiles, ms_login, settings

    def save(
        self,
        profiles: dict[str, dict],
        ms_login: dict[str, Any],
        settings: dict[str, Any],
        sync_standard: bool = True,
    ) -> None:
        ms_login_data = dict(ms_login or {})
        if ms_login_data.get("access_token"):
            ms_login_data["access_token"] = self.protect_fn(ms_login_data["access_token"])
        if ms_login_data.get("refresh_token"):
            ms_login_data["refresh_token"] = self.protect_fn(ms_login_data["refresh_token"])

        config_data = {
            "profiles": profiles if isinstance(profiles, dict) else {},
            "ms_login": ms_login_data,
            "settings": settings if isinstance(settings, dict) else {},
        }
        os.makedirs(os.path.dirname(os.path.abspath(self.config_file)), exist_ok=True)
        tmp_file = f"{self.config_file}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        os.replace(tmp_file, self.config_file)

        if sync_standard:
            try:
                self.sync_with_standard_launchers(profiles, self.mc_dir)
            except Exception as e:
                print(f"[Config] sync_with_standard_launchers error: {e}")

    def sync_with_standard_launchers(
        self,
        profiles: dict[str, dict],
        mc_dir: Optional[str | Path] = None,
    ) -> None:
        target_mc_dir = str(mc_dir) if mc_dir else self.mc_dir
        target_files = ["launcher_profiles.json", "tlauncher_profiles.json"]

        for file_name in target_files:
            file_path = os.path.join(target_mc_dir, file_name)
            data: dict[str, Any] = {"profiles": {}}

            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            data = loaded
                        if "profiles" not in data or not isinstance(data.get("profiles"), dict):
                            data["profiles"] = {}
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    continue

            # Remove old vega_ profiles that might have been deleted
            keys_to_remove = [k for k in data.get("profiles", {}) if str(k).startswith("vega_")]
            for k in keys_to_remove:
                del data["profiles"][k]

            for pid, pdata in (profiles or {}).items():
                if not isinstance(pdata, dict):
                    continue
                profile_key = f"vega_{pid}"
                ram_val = pdata.get("ram") or 4096
                data["profiles"][profile_key] = {
                    "name": f"[Vega] {pdata.get('name') or 'Unknown'}",
                    "lastVersionId": pdata.get("version_id") or pdata.get("version") or "",
                    "gameDir": pdata.get("path") or "",
                    "javaArgs": f"-Xmx{ram_val}m -Xms512m",
                    "type": "custom",
                }

            temp_path = file_path + ".tmp"
            try:
                os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)

                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        os.replace(temp_path, file_path)
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            time.sleep(0.1 * (2 ** attempt))
                        else:
                            raise e
            except Exception as e:
                print(f"Error writing to {file_path}: {e}")
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

    def generate_unique_profile_name(
        self,
        base_name: str,
        existing_profiles: Optional[dict[str, dict]] = None,
    ) -> tuple[str, str]:
        profiles_map = existing_profiles if isinstance(existing_profiles, dict) else {}
        pack_name = base_name
        profile_path = os.path.join(self.profiles_dir, pack_name)
        counter = 1
        while os.path.exists(profile_path) or any(
            isinstance(p, dict) and p.get("name") == pack_name for p in profiles_map.values()
        ):
            pack_name = f"{base_name} ({counter})"
            profile_path = os.path.join(self.profiles_dir, pack_name)
            counter += 1
        return pack_name, profile_path

    def is_safe_profile_path(self, profile_path: str | Path) -> bool:
        if not profile_path:
            return False
        real_target = os.path.realpath(str(profile_path))
        real_base = os.path.realpath(self.profiles_dir) + os.sep
        return real_target.startswith(real_base)

    def delete_profile_directory(self, profile_path: str | Path) -> tuple[bool, str]:
        """
        Safely deletes a profile directory inside `profiles_dir`.
        Returns (ok, reason) where reason is "" on success,
        "outside_containment" if path escapes profiles_dir,
        or "locked" if files remain locked on disk.
        """
        if not profile_path or not os.path.exists(str(profile_path)):
            return True, ""

        if not self.is_safe_profile_path(profile_path):
            return False, "outside_containment"

        real_target = os.path.realpath(str(profile_path))
        try:
            shutil.rmtree(real_target, ignore_errors=True)
        except Exception:
            pass

        if os.path.exists(real_target) and os.name == "nt":
            try:
                subprocess.run(
                    ["cmd.exe", "/c", "rd", "/s", "/q", f'"{real_target}"'],
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass

        if os.path.exists(real_target):
            return False, "locked"
        return True, ""

    def get_setting(self, key: str, default: Any = None) -> Any:
        data = self.read_raw_config()
        settings = data.get("settings")
        if isinstance(settings, dict) and key in settings:
            return settings[key]
        return DEFAULT_SETTINGS.get(key, default) if default is None else default

    def update_setting(self, key: str, value: Any) -> None:
        try:
            data = self.read_raw_config()
            if not isinstance(data.get("settings"), dict):
                data["settings"] = {}
            data["settings"][key] = value
            os.makedirs(os.path.dirname(os.path.abspath(self.config_file)), exist_ok=True)
            tmp_file = f"{self.config_file}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_file, self.config_file)
        except Exception:
            pass

    def list_available_client_profiles(self) -> tuple[list[str], dict[str, dict]]:
        """
        Reconciles on-disk profile directories under `profiles_dir` with
        registered profiles in `launcher_config.json`.
        """
        profile_names: list[str] = []
        if os.path.exists(self.profiles_dir):
            profile_names = [
                d
                for d in sorted(os.listdir(self.profiles_dir))
                if os.path.isdir(os.path.join(self.profiles_dir, d)) and not d.startswith(".")
            ]

        data = self.read_raw_config()
        profiles_dict = data.get("profiles", {})
        if not isinstance(profiles_dict, dict):
            profiles_dict = {}

        for p in profiles_dict.values():
            if not isinstance(p, dict):
                continue
            p_name = p.get("name")
            p_path = p.get("path")
            if p_name and p_name not in profile_names:
                is_in_profiles = False
                if os.path.isdir(os.path.join(self.profiles_dir, p_name)):
                    is_in_profiles = True
                elif p_path and os.path.isdir(p_path):
                    try:
                        if os.path.commonpath(
                            [os.path.abspath(self.profiles_dir), os.path.abspath(p_path)]
                        ) == os.path.abspath(self.profiles_dir):
                            is_in_profiles = True
                    except Exception:
                        pass
                if is_in_profiles:
                    profile_names.append(p_name)

        return profile_names, profiles_dict

    def resolve_client_profile_dir(
        self,
        selected_profile: str,
        profiles_dict: Optional[dict[str, dict]] = None,
        fallback_base_dir: Optional[str | Path] = None,
    ) -> tuple[Optional[str], Optional[dict]]:
        """
        Resolves the filesystem directory and profile metadata dict for a client profile name.
        """
        if profiles_dict is None:
            _, profiles_dict = self.list_available_client_profiles()

        matched_pdata: Optional[dict] = None
        for p in profiles_dict.values():
            if isinstance(p, dict) and p.get("name") == selected_profile:
                matched_pdata = p
                break

        client_dir = os.path.join(self.profiles_dir, selected_profile)
        if not os.path.exists(client_dir) and matched_pdata:
            p_path = matched_pdata.get("path")
            if p_path and os.path.exists(p_path):
                client_dir = p_path

        if not os.path.exists(client_dir) and fallback_base_dir:
            alt_dir = os.path.join(str(fallback_base_dir), selected_profile)
            if os.path.exists(alt_dir):
                client_dir = alt_dir

        if not os.path.exists(client_dir):
            return None, matched_pdata

        return client_dir, matched_pdata

    def find_client_profile_for_server(self, server_name: str) -> Optional[dict]:
        """
        If `server_name` matches `<profile_name>_Server`, returns the corresponding
        client profile dictionary when its directory exists on disk.
        """
        data = self.read_raw_config()
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            return None
        for p in profiles.values():
            if not isinstance(p, dict):
                continue
            p_name = p.get("name", "")
            if p_name and server_name == f"{p_name}_Server":
                client_path = p.get("path", "")
                if client_path and os.path.exists(client_path):
                    return p
        return None

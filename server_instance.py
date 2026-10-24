from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_SERVER_PROPERTIES = (
    "#Minecraft server properties\n"
    "allow-flight=false\n"
    "allow-nether=true\n"
    "difficulty=easy\n"
    "enable-command-block=false\n"
    "gamemode=survival\n"
    "level-name=world\n"
    "max-players=20\n"
    "motd=A Minecraft Server\n"
    "online-mode=true\n"
    "pvp=true\n"
    "server-port=25565\n"
    "simulation-distance=10\n"
    "spawn-animals=true\n"
    "spawn-monsters=true\n"
    "spawn-npcs=true\n"
    "view-distance=10\n"
    "max-tick-time=-1\n"
)

CLIENT_MODS_BLACKLIST = (
    "sodium",
    "embeddium",
    "rubidium",
    "iris",
    "oculus",
    "optifine",
    "immediatelyfast",
    "xaero",
    "blur",
    "dynamiclights",
    "badoptimizations",
    "crashassistant",
)


@dataclass
class ServerProperties:
    max_players: int = 20
    view_distance: int = 10
    difficulty: str = "easy"
    level_seed: str = ""
    level_name: str = "world"
    gamemode: str = "survival"
    motd: str = "A Minecraft Server"
    spawn_protection: int = 16
    simulation_distance: int = 10
    online_mode: bool = True
    pvp: bool = True
    server_port: str = "25565"


@dataclass(frozen=True)
class SyncDiff:
    added: int = 0
    removed: int = 0


@dataclass(frozen=True)
class PlayerStatus:
    name: str
    online: bool
    op: bool


class ServerInstance:
    """
    Deep module representing a local Minecraft server directory (`servers/<name>/`).
    Encapsulates eula.txt & server.properties bootstrapping, round-trip ServerProperties
    parsing/saving, client-to-server mod blacklist synchronization, and usercache/ops inspection.
    """

    def __init__(self, server_dir: str | Path):
        self.server_dir = str(server_dir) if server_dir else ""

    @staticmethod
    def is_client_only_mod(filename: str) -> bool:
        for kw in CLIENT_MODS_BLACKLIST:
            if re.search(rf"(^|[-_ \.])({re.escape(kw)})([-_ \.]|$)", filename, re.IGNORECASE):
                return True
        return False

    def initialize_directory(self) -> None:
        if not self.server_dir:
            return
        os.makedirs(self.server_dir, exist_ok=True)
        with open(os.path.join(self.server_dir, "eula.txt"), "w", encoding="utf-8") as f:
            f.write("eula=true\n")
        with open(os.path.join(self.server_dir, "server.properties"), "w", encoding="utf-8") as f:
            f.write(DEFAULT_SERVER_PROPERTIES)

    def has_launch_artifact(self) -> bool:
        if not self.server_dir or not os.path.exists(self.server_dir):
            return False
        jar_path = os.path.join(self.server_dir, "server.jar")
        bat_path = os.path.join(self.server_dir, "run.bat")
        return os.path.exists(jar_path) or os.path.exists(bat_path)

    def ensure_boot_ready(self) -> None:
        if not self.server_dir:
            return
        os.makedirs(self.server_dir, exist_ok=True)
        eula_path = os.path.join(self.server_dir, "eula.txt")
        if not os.path.exists(eula_path):
            with open(eula_path, "w", encoding="utf-8") as f:
                f.write("eula=true\n")
        else:
            try:
                with open(eula_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if re.search(r"eula\s*=\s*(false|0|no|\s*$)", content, flags=re.IGNORECASE | re.MULTILINE):
                    content = re.sub(
                        r"eula\s*=\s*(false|0|no|\s*$)",
                        "eula=true",
                        content,
                        flags=re.IGNORECASE | re.MULTILINE,
                    )
                    with open(eula_path, "w", encoding="utf-8") as f:
                        f.write(content)
                elif not re.search(r"eula\s*=\s*true", content, flags=re.IGNORECASE):
                    with open(eula_path, "a", encoding="utf-8") as f:
                        f.write("\neula=true\n")
            except Exception:
                pass

        props_path = os.path.join(self.server_dir, "server.properties")
        needs_props = False
        if not os.path.exists(props_path) or os.path.getsize(props_path) == 0:
            needs_props = True
        else:
            try:
                with open(props_path, "r", encoding="utf-8") as f:
                    non_comment_lines = [
                        line.strip() for line in f if line.strip() and not line.strip().startswith("#")
                    ]
                if not non_comment_lines:
                    needs_props = True
            except Exception:
                pass
        if needs_props:
            with open(props_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_SERVER_PROPERTIES)

    def import_from_client_profile(self, client_dir: str | Path) -> None:
        c_dir = str(client_dir)
        self.initialize_directory()

        mods_dir = os.path.join(c_dir, "mods")
        target_mods = os.path.join(self.server_dir, "mods")
        if os.path.exists(mods_dir):
            def _ignore_client_mods(_dir_path, filenames):
                return [f for f in filenames if self.is_client_only_mod(f)]

            shutil.copytree(mods_dir, target_mods, dirs_exist_ok=True, ignore=_ignore_client_mods)
        else:
            os.makedirs(target_mods, exist_ok=True)

        config_dir = os.path.join(c_dir, "config")
        target_config = os.path.join(self.server_dir, "config")
        if os.path.exists(config_dir):
            shutil.copytree(config_dir, target_config, dirs_exist_ok=True)
        else:
            os.makedirs(target_config, exist_ok=True)

    def sync_mods_from_client(self, client_dir: str | Path) -> SyncDiff:
        c_mods = os.path.join(str(client_dir), "mods")
        s_mods = os.path.join(self.server_dir, "mods")
        if not os.path.exists(c_mods):
            return SyncDiff(0, 0)

        os.makedirs(s_mods, exist_ok=True)
        client_mods = set(os.listdir(c_mods))
        server_mods = set(os.listdir(s_mods))
        added = 0
        removed = 0

        for f_name in server_mods:
            if self.is_client_only_mod(f_name):
                if "playit" in f_name.lower():
                    continue
                try:
                    s_path = os.path.join(s_mods, f_name)
                    if os.path.isdir(s_path):
                        shutil.rmtree(s_path)
                    else:
                        os.remove(s_path)
                    removed += 1
                except Exception:
                    pass

        for f_name in client_mods:
            if self.is_client_only_mod(f_name):
                continue
            c_path = os.path.join(c_mods, f_name)
            s_path = os.path.join(s_mods, f_name)
            if os.path.isfile(c_path):
                need_copy = not os.path.exists(s_path) or os.path.getsize(c_path) != os.path.getsize(s_path)
                if need_copy:
                    try:
                        shutil.copy2(c_path, s_path)
                        added += 1
                    except Exception:
                        pass
            elif os.path.isdir(c_path) and not os.path.exists(s_path):
                try:
                    shutil.copytree(c_path, s_path)
                    added += 1
                except Exception:
                    pass

        return SyncDiff(added=added, removed=removed)

    def read_properties(self) -> ServerProperties:
        props = ServerProperties()
        if not self.server_dir:
            return props
        props_file = os.path.join(self.server_dir, "server.properties")
        if not os.path.exists(props_file):
            return props

        try:
            with open(props_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return props

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, val = stripped.split("=", 1)
            key = key.strip()
            val = val.strip()
            if key == "max-players":
                try:
                    props.max_players = int(val)
                except Exception:
                    pass
            elif key == "view-distance":
                try:
                    props.view_distance = int(val)
                except Exception:
                    pass
            elif key == "difficulty" and val:
                props.difficulty = val
            elif key == "online-mode":
                props.online_mode = val.lower() != "false"
            elif key == "pvp":
                props.pvp = val.lower() == "true"
            elif key == "level-seed":
                props.level_seed = val
            elif key == "level-name":
                props.level_name = val
            elif key == "gamemode" and val:
                props.gamemode = val
            elif key == "motd":
                props.motd = val
            elif key == "spawn-protection":
                try:
                    props.spawn_protection = int(val)
                except Exception:
                    pass
            elif key == "simulation-distance":
                try:
                    props.simulation_distance = int(val)
                except Exception:
                    pass
            elif key == "server-port" and val:
                props.server_port = val

        return props

    def write_properties(self, props: ServerProperties) -> None:
        if not self.server_dir:
            return
        os.makedirs(self.server_dir, exist_ok=True)
        props_file = os.path.join(self.server_dir, "server.properties")
        if os.path.exists(props_file):
            with open(props_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []

        lvl = (props.level_name or "").strip() or "world"
        seed = (props.level_seed or "").strip()
        online_str = "true" if props.online_mode else "false"
        pvp_str = "true" if props.pvp else "false"

        key_map = {
            "server-port": str(props.server_port),
            "max-players": str(props.max_players),
            "view-distance": str(props.view_distance),
            "difficulty": str(props.difficulty),
            "online-mode": online_str,
            "pvp": pvp_str,
            "level-seed": seed,
            "level-name": lvl,
            "gamemode": str(props.gamemode),
            "motd": str(props.motd),
            "spawn-protection": str(props.spawn_protection),
            "simulation-distance": str(props.simulation_distance),
        }

        updated_lines: list[str] = []
        handled_keys: set[str] = set()

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped or "=" not in stripped:
                updated_lines.append(line)
                continue
            key, _ = stripped.split("=", 1)
            key = key.strip()
            if key in key_map:
                updated_lines.append(f"{key}={key_map[key]}\n")
                handled_keys.add(key)
            else:
                updated_lines.append(line)

        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] += "\n"

        for k, v in key_map.items():
            if k not in handled_keys:
                updated_lines.append(f"{k}={v}\n")

        with open(props_file, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)

    def read_raw_properties(self) -> dict[str, str]:
        """Read all raw key-value pairs from server.properties into a dictionary."""
        props: dict[str, str] = {}
        if not self.server_dir:
            return props
        prop_path = os.path.join(self.server_dir, "server.properties")
        if not os.path.isfile(prop_path):
            return props
        try:
            with open(prop_path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
        except Exception:
            pass
        return props

    def update_raw_properties(self, updates: dict[str, Any]) -> dict[str, str]:
        """Atomically update arbitrary key-value settings in server.properties."""
        if not self.server_dir:
            return {}
        prop_path = os.path.join(self.server_dir, "server.properties")
        lines: list[str] = []
        existing_keys: set[str] = set()
        if os.path.isfile(prop_path):
            with open(prop_path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    stripped = raw_line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        k, _ = stripped.split("=", 1)
                        key = k.strip()
                        if key in updates:
                            lines.append(f"{key}={updates[key]}\n")
                            existing_keys.add(key)
                        else:
                            lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
                    else:
                        lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")

        for k, v in updates.items():
            if k not in existing_keys:
                lines.append(f"{k}={v}\n")

        os.makedirs(os.path.dirname(os.path.abspath(prop_path)), exist_ok=True)
        tmp_path = f"{prop_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(tmp_path, prop_path)
        return self.read_raw_properties()

    def list_known_players(self) -> set[str]:
        known: set[str] = set()
        if not self.server_dir:
            return known
        usercache_path = os.path.join(self.server_dir, "usercache.json")
        if os.path.exists(usercache_path):
            try:
                with open(usercache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                if isinstance(cache, list):
                    for entry in cache:
                        if isinstance(entry, dict):
                            name = entry.get("name")
                            if name:
                                known.add(str(name))
            except Exception:
                pass
        return known

    def is_player_op(self, player_name: str) -> bool:
        if not self.server_dir or not player_name:
            return False
        ops_path = os.path.join(self.server_dir, "ops.json")
        if os.path.exists(ops_path):
            try:
                with open(ops_path, "r", encoding="utf-8") as f:
                    ops = json.load(f)
                if isinstance(ops, list):
                    return any(
                        isinstance(op, dict) and str(op.get("name", "")).lower() == player_name.lower()
                        for op in ops
                    )
            except Exception:
                pass
        return False

    def get_player_statuses(self, online_players: Optional[set[str]] = None) -> list[PlayerStatus]:
        online_set = set(online_players or ())
        known = self.list_known_players()
        all_names = set(online_set) | known

        statuses = []
        for name in sorted(all_names, key=lambda n: (n not in online_set, n.lower())):
            is_online = name in online_set
            is_op = self.is_player_op(name)
            statuses.append(PlayerStatus(name=name, online=is_online, op=is_op))
        return statuses

    def count_content_and_backups(self) -> tuple[int, int]:
        if not self.server_dir or not os.path.exists(self.server_dir):
            return 0, 0
        mod_cnt = 0
        for sub in ("mods", "plugins"):
            mdir = os.path.join(self.server_dir, sub)
            if os.path.exists(mdir):
                try:
                    mod_cnt += sum(1 for f in os.listdir(mdir) if f.lower().endswith(".jar"))
                except Exception:
                    pass
        bkp_cnt = 0
        bdir = os.path.join(self.server_dir, "backups")
        if os.path.exists(bdir):
            try:
                bkp_cnt = sum(1 for f in os.listdir(bdir) if f.lower().endswith(".zip"))
            except Exception:
                pass
        return mod_cnt, bkp_cnt

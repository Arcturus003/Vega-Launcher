from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - fallback for mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore

import vega_mcp_server as _vega_bootstrap  # noqa: F401 - ensures headless Qt stub is installed

from mod_manager import CompatibilityPolicy, ContentCatalog
from profile_store import ProfileAndConfigStore
from runtime_provisioner import RuntimeProvisioner, RuntimeSpec

mcp = MCPServer("legacy_mcp")

# Safe keys in Legacy Launcher's tl.properties that can be read and updated without exposing credentials
SAFE_TL_PROPERTY_KEYS = frozenset({
    "login.version",
    "login.auto",
    "minecraft.xmx",
    "minecraft.gamedir",
    "minecraft.gamedir.separate",
    "minecraft.fullscreen",
    "minecraft.size",
    "minecraft.onlaunch",
    "minecraft.gpu",
    "minecraft.improvedargs",
    "minecraft.improvedargs.type",
    "minecraft.crash",
    "minecraft.jre.type",
    "minecraft.versions.release",
    "minecraft.versions.snapshot",
    "minecraft.versions.modified",
    "locale",
    "gui.logger",
    "gui.size",
})

REDACTED_KEY_SUBSTRINGS = ("account", "token", "password", "secret", "client", "session", "auth")


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


def _format_output(data: dict[str, Any], fmt: ResponseFormat, markdown_builder) -> str:
    if fmt == ResponseFormat.JSON:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return markdown_builder(data)


_JAVA_UNESCAPE_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)")
_JAVA_SIMPLE_ESCAPES = {"t": "\t", "r": "\r", "n": "\n", "f": "\f"}


def _unescape_java_prop(val: str) -> str:
    def _repl(match: re.Match) -> str:
        seq = match.group(1)
        if len(seq) == 5 and seq[0] == "u":
            return chr(int(seq[1:], 16))
        return _JAVA_SIMPLE_ESCAPES.get(seq, seq)

    return _JAVA_UNESCAPE_RE.sub(_repl, val)


def _escape_java_prop(val: str) -> str:
    # Escape backslashes and colons in Windows paths the way Java Properties / Legacy Launcher writes them
    out = str(val).replace("\\", "\\\\").replace(":", r"\:")
    return out


def read_tl_properties(prop_path: str | Path) -> dict[str, str]:
    props: dict[str, str] = {}
    if not os.path.isfile(prop_path):
        return props
    try:
        with open(prop_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = _unescape_java_prop(v.strip())
    except Exception:
        pass
    return props


def write_tl_properties(prop_path: str | Path, updates: dict[str, Any]) -> dict[str, str]:
    lines: list[str] = []
    updated_keys: set[str] = set()
    if os.path.isfile(prop_path):
        with open(prop_path, "r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                stripped = raw.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k, _ = stripped.split("=", 1)
                    key = k.strip()
                    if key in updates:
                        lines.append(f"{key}={_escape_java_prop(str(updates[key]))}\n")
                        updated_keys.add(key)
                    else:
                        lines.append(raw if raw.endswith("\n") else raw + "\n")
                else:
                    lines.append(raw if raw.endswith("\n") else raw + "\n")

    for k, v in updates.items():
        if k not in updated_keys:
            lines.append(f"{k}={_escape_java_prop(str(v))}\n")

    os.makedirs(os.path.dirname(os.path.abspath(str(prop_path))), exist_ok=True)
    tmp_path = f"{prop_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp_path, prop_path)
    return read_tl_properties(prop_path)


def detect_version_dir_spec(version_name: str, version_dir: str) -> RuntimeSpec:
    low = version_name.lower()
    loader = "vanilla"
    for cand in ("neoforge", "fabric", "quilt", "forge"):
        if cand in low:
            loader = cand
            break

    mc_ver = RuntimeProvisioner.extract_base_version(version_name, default=None)
    json_path = os.path.join(version_dir, f"{version_name}.json")
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8", errors="replace") as f:
                manifest = json.load(f)
            if isinstance(manifest, dict):
                inherits = str(manifest.get("inheritsFrom") or "")
                if inherits and not mc_ver:
                    mc_ver = RuntimeProvisioner.extract_base_version(inherits, default=inherits)
                if loader == "vanilla":
                    raw_str = json.dumps(manifest.get("libraries", [])[:15]).lower()
                    for cand in ("neoforge", "fabric", "quilt", "forge"):
                        if cand in raw_str:
                            loader = cand
                            break
        except Exception:
            pass

    return RuntimeSpec(mc_version=mc_ver or version_name, loader=loader, is_server=False)


class LegacyLauncherMCPService:
    """
    Headless facade over Legacy Launcher (.tlauncher/legacy/Minecraft), managing
    tl.properties, installed versions, Modrinth mods/shaders/resourcepacks,
    saves/backups, crash reports, and Vega Launcher synchronization.
    """

    def __init__(
        self,
        legacy_root: Optional[str | Path] = None,
        game_dir: Optional[str | Path] = None,
        catalog: Optional[ContentCatalog] = None,
        provisioner: Optional[RuntimeProvisioner] = None,
        vega_store: Optional[ProfileAndConfigStore] = None,
    ):
        appdata = os.environ.get("APPDATA", "")
        self.legacy_root = (
            str(legacy_root)
            if legacy_root
            else os.path.join(appdata, ".tlauncher", "legacy", "Minecraft")
        )
        self.tl_properties_path = os.path.join(self.legacy_root, "tl.properties")
        props = read_tl_properties(self.tl_properties_path)
        configured_game_dir = props.get("minecraft.gamedir")
        if game_dir:
            self.game_dir = str(game_dir)
        elif configured_game_dir and os.path.isdir(configured_game_dir):
            self.game_dir = configured_game_dir
        else:
            self.game_dir = os.path.join(self.legacy_root, "game")

        os.makedirs(self.game_dir, exist_ok=True)
        for sub in ("versions", "mods", "shaderpacks", "resourcepacks", "saves", "backups", "logs"):
            os.makedirs(os.path.join(self.game_dir, sub), exist_ok=True)

        self.catalog = catalog or ContentCatalog(mc_dir=self.game_dir)
        self.provisioner = provisioner or RuntimeProvisioner(mc_dir=self.game_dir)
        self.vega_store = vega_store or ProfileAndConfigStore()

    def is_safe_game_subpath(self, target_path: str | Path) -> bool:
        if not target_path:
            return False
        real_target = os.path.realpath(str(target_path))
        real_base = os.path.realpath(self.game_dir) + os.sep
        return real_target.startswith(real_base) or real_target == os.path.realpath(self.game_dir)

    def get_safe_properties(self) -> dict[str, str]:
        raw = read_tl_properties(self.tl_properties_path)
        safe: dict[str, str] = {}
        for k, v in sorted(raw.items()):
            low_k = k.lower()
            if any(sub in low_k for sub in REDACTED_KEY_SUBSTRINGS):
                continue
            safe[k] = v
        return safe

    def get_safe_accounts(self) -> list[dict[str, Any]]:
        tp_path = os.path.join(self.game_dir, "tlauncher_profiles.json")
        if not os.path.isfile(tp_path):
            return []
        try:
            with open(tp_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            user_set = data.get("userSet", {}) if isinstance(data, dict) else {}
            selected_name = (user_set.get("selected") or {}).get("username", "")
            accounts = []
            for acc in user_set.get("list") or []:
                if not isinstance(acc, dict):
                    continue
                uname = acc.get("username", "")
                accounts.append({
                    "username": uname,
                    "type": acc.get("type", "plain"),
                    "selected": uname == selected_name,
                })
            return accounts
        except Exception:
            return []

    def list_versions(self) -> list[dict[str, Any]]:
        versions_dir = os.path.join(self.game_dir, "versions")
        if not os.path.isdir(versions_dir):
            return []
        props = read_tl_properties(self.tl_properties_path)
        active_ver = props.get("login.version", "")
        items: list[dict[str, Any]] = []
        for d in sorted(os.listdir(versions_dir)):
            v_dir = os.path.join(versions_dir, d)
            if not os.path.isdir(v_dir) or d.startswith("."):
                continue
            spec = detect_version_dir_spec(d, v_dir)
            has_jar = os.path.isfile(os.path.join(v_dir, f"{d}.jar"))
            has_json = os.path.isfile(os.path.join(v_dir, f"{d}.json"))
            items.append({
                "version_id": d,
                "mc_version": spec.mc_version,
                "loader": spec.loader,
                "is_selected": d == active_ver,
                "has_jar": has_jar,
                "has_json": has_json,
                "path": v_dir,
            })
        return items

    def get_active_runtime_spec(self) -> RuntimeSpec:
        props = read_tl_properties(self.tl_properties_path)
        active_ver = props.get("login.version", "")
        if active_ver:
            v_dir = os.path.join(self.game_dir, "versions", active_ver)
            if os.path.isdir(v_dir):
                return detect_version_dir_spec(active_ver, v_dir)
            return RuntimeSpec(
                mc_version=RuntimeProvisioner.extract_base_version(active_ver, default="1.20.1") or "1.20.1",
                loader= next((c for c in ("neoforge", "fabric", "quilt", "forge") if c in active_ver.lower()), "vanilla"),
            )
        return RuntimeSpec(mc_version="1.20.1", loader="vanilla")


_DEFAULT_LEGACY_SERVICE: Optional[LegacyLauncherMCPService] = None


def get_legacy_service() -> LegacyLauncherMCPService:
    global _DEFAULT_LEGACY_SERVICE
    if _DEFAULT_LEGACY_SERVICE is None:
        _DEFAULT_LEGACY_SERVICE = LegacyLauncherMCPService()
    return _DEFAULT_LEGACY_SERVICE


def set_legacy_service(service: Optional[LegacyLauncherMCPService]) -> None:
    global _DEFAULT_LEGACY_SERVICE
    _DEFAULT_LEGACY_SERVICE = service


# ============================================================================
# Input Models
# ============================================================================

class BaseToolInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )


class GetLegacyStatusInput(BaseToolInput):
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class UpdateLegacySettingsInput(BaseToolInput):
    updates: Dict[str, Any] = Field(
        ...,
        description="Safe tl.properties keys to update (e.g. {'login.version': 'Fabric 1.21.1', 'minecraft.xmx': '6144'}).",
    )


class ListLegacyVersionsInput(BaseToolInput):
    limit: int = Field(default=30, ge=1, le=100, description="Maximum number of versions to return.")
    offset: int = Field(default=0, ge=0, description="Number of versions to skip for pagination.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class SelectLegacyVersionInput(BaseToolInput):
    version_id: str = Field(..., min_length=1, max_length=120, description="Installed version folder name in game/versions/ (e.g. 'Fabric 1.21.1').")
    ram_mb: Optional[int] = Field(default=None, ge=1024, le=65536, description="Optional RAM allocation in MB to set in minecraft.xmx.")


class InstallLegacyRuntimeInput(BaseToolInput):
    mc_version: str = Field(..., min_length=3, max_length=32, description="Minecraft version to install (e.g., '1.20.1', '1.21.1').")
    loader: Literal["vanilla", "fabric", "quilt", "forge", "neoforge"] = Field(
        default="fabric",
        description="Client mod loader to install into Legacy Launcher.",
    )
    loader_version: Optional[str] = Field(default=None, max_length=64, description="Optional specific loader version.")
    set_as_active: bool = Field(default=True, description="Automatically set login.version in tl.properties to the newly installed version.")


class ListLegacyContentInput(BaseToolInput):
    folder: Literal["mods", "shaderpacks", "resourcepacks"] = Field(
        default="mods",
        description="Content subfolder in Legacy Launcher game directory.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class InstallLegacyModrinthInput(BaseToolInput):
    project_id: str = Field(..., min_length=1, max_length=80, description="Modrinth project ID or slug (e.g., 'AANobbMI' or 'sodium').")
    content_type: Literal["mod", "shader", "modpack"] = Field(default="mod", description="Content type to install: 'mod', 'shader', or 'modpack'.")
    game_version: Optional[str] = Field(default=None, max_length=32, description="Optional Minecraft version override (defaults to active login.version).")
    loader: Optional[str] = Field(default=None, max_length=32, description="Optional loader override (defaults to active login.version loader).")
    overwrite: bool = Field(default=False, description="Overwrite if the file already exists.")


class CheckLegacyModUpdatesInput(BaseToolInput):
    game_version: Optional[str] = Field(default=None, max_length=32, description="Optional Minecraft version override.")
    loader: Optional[str] = Field(default=None, max_length=32, description="Optional loader override.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class ManageLegacyContentInput(BaseToolInput):
    folder: Literal["mods", "shaderpacks", "resourcepacks"] = Field(default="mods", description="Target content subfolder.")
    filename: str = Field(..., min_length=1, max_length=200, description="Exact filename inside the subfolder.")
    action: Literal["enable", "disable", "delete"] = Field(..., description="Action: 'enable', 'disable', or 'delete'.")
    confirm: bool = Field(default=False, description="Must be True when action='delete'.")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("filename must be a basename without path separators.")
        return v


class ListLegacyWorldsInput(BaseToolInput):
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class BackupLegacyWorldInput(BaseToolInput):
    world_name: str = Field(..., min_length=1, max_length=120, description="World folder name inside game/saves/.")
    label: Optional[str] = Field(default=None, max_length=40, description="Optional label suffix for the backup zip.")

    @field_validator("world_name")
    @classmethod
    def validate_world_name(cls, v: str) -> str:
        if "/" in v or "\\" in v or v in (".", ".."):
            raise ValueError("world_name must not contain path separators.")
        return v


class RestoreLegacyWorldBackupInput(BaseToolInput):
    backup_filename: str = Field(..., min_length=1, max_length=160, description="Backup .zip filename inside game/backups/.")
    world_name: str = Field(..., min_length=1, max_length=120, description="Target world folder name inside game/saves/.")
    confirm: bool = Field(default=False, description="Must be True to confirm overwriting the world folder.")
    create_safety_backup: bool = Field(default=True, description="Create a pre-restore safety backup before extracting.")


class GetLegacyLogsInput(BaseToolInput):
    log_lines: int = Field(default=40, ge=0, le=200, description="Number of tail lines to read from game/logs/latest.log.")
    include_latest_crash: bool = Field(default=True, description="Include the latest crash report from game/crash-reports/ if present.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class SyncLegacyWithVegaInput(BaseToolInput):
    direction: Literal["vega_to_legacy", "legacy_to_vega"] = Field(
        default="vega_to_legacy",
        description="'vega_to_legacy' exports Vega profiles into Legacy Launcher's launcher_profiles.json; 'legacy_to_vega' imports Legacy versions as Vega profiles.",
    )


# ============================================================================
# MCP Tools
# ============================================================================

@mcp.tool(
    name="legacy_get_status_and_settings",
    annotations={
        "title": "Get Legacy Launcher Status, Active Version, and Safe Settings",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_get_status_and_settings(params: GetLegacyStatusInput) -> str:
    """Inspect Legacy Launcher's installation paths, active version, RAM setting, safe tl.properties, and usernames (tokens redacted)."""
    svc = get_legacy_service()
    safe_props = svc.get_safe_properties()
    spec = svc.get_active_runtime_spec()
    accounts = svc.get_safe_accounts()
    versions = svc.list_versions()
    mods_dir = os.path.join(svc.game_dir, "mods")
    mods_count = (
        len([f for f in os.listdir(mods_dir) if f.lower().endswith((".jar", ".jar.disabled"))])
        if os.path.isdir(mods_dir)
        else 0
    )

    payload = {
        "legacy_root": svc.legacy_root,
        "game_dir": svc.game_dir,
        "active_version": safe_props.get("login.version", ""),
        "detected_mc_version": spec.mc_version,
        "detected_loader": spec.loader,
        "ram_xmx": safe_props.get("minecraft.xmx", "auto"),
        "separate_dirs_mode": safe_props.get("minecraft.gamedir.separate", "none"),
        "installed_versions_count": len(versions),
        "installed_mods_count": mods_count,
        "accounts": accounts,
        "settings": safe_props,
    }

    def _md(d: dict[str, Any]) -> str:
        lines = [
            "# Legacy Launcher Status",
            f"- **Game Directory**: `{d['game_dir']}`",
            f"- **Active Version (`login.version`)**: `{d['active_version']}` (MC `{d['detected_mc_version']}`, Loader `{d['detected_loader']}`)",
            f"- **Allocated RAM (`minecraft.xmx`)**: `{d['ram_xmx']}`",
            f"- **Separate Game Dirs**: `{d['separate_dirs_mode']}`",
            f"- **Installed Versions**: `{d['installed_versions_count']}` | **Installed Mods**: `{d['installed_mods_count']}`",
            f"- **Accounts**: {', '.join(a['username'] + (' [selected]' if a['selected'] else '') for a in d['accounts']) or 'None'}",
        ]
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="legacy_update_settings",
    annotations={
        "title": "Update Safe Legacy Launcher Settings in tl.properties",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_update_settings(params: UpdateLegacySettingsInput) -> str:
    """Update safe Legacy Launcher settings in tl.properties (e.g. login.version, minecraft.xmx, minecraft.fullscreen)."""
    disallowed = [k for k in params.updates.keys() if k not in SAFE_TL_PROPERTY_KEYS]
    if disallowed:
        return (
            f"Error: Disallowed or unknown tl.properties key(s): {', '.join(disallowed)}. "
            f"Allowed keys: {', '.join(sorted(SAFE_TL_PROPERTY_KEYS))}."
        )

    svc = get_legacy_service()
    write_tl_properties(svc.tl_properties_path, params.updates)
    safe_props = svc.get_safe_properties()
    return json.dumps(
        {
            "ok": True,
            "updated_keys": list(params.updates.keys()),
            "active_settings": {k: safe_props.get(k) for k in params.updates.keys()},
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="legacy_list_versions",
    annotations={
        "title": "List Installed Versions in Legacy Launcher",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_list_versions(params: ListLegacyVersionsInput) -> str:
    """List all installed Minecraft versions in Legacy Launcher's game/versions/ directory."""
    svc = get_legacy_service()
    all_items = svc.list_versions()
    total = len(all_items)
    sliced = all_items[params.offset : params.offset + params.limit]
    has_more = total > params.offset + len(sliced)
    payload = {
        "total": total,
        "count": len(sliced),
        "offset": params.offset,
        "has_more": has_more,
        "next_offset": params.offset + len(sliced) if has_more else None,
        "items": sliced,
    }

    def _md(d: dict[str, Any]) -> str:
        if not d["items"]:
            return "No versions found in Legacy Launcher `game/versions/`."
        lines = [f"# Legacy Launcher Installed Versions ({d['count']} of {d['total']})"]
        for v in d["items"]:
            active_badge = " **[ACTIVE]**" if v["is_selected"] else ""
            lines.append(
                f"- **{v['version_id']}**{active_badge} — MC `{v['mc_version']}` | Loader: `{v['loader']}`"
            )
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="legacy_select_version",
    annotations={
        "title": "Select Active Version and RAM in Legacy Launcher",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_select_version(params: SelectLegacyVersionInput) -> str:
    """Select an installed version as the active login.version in Legacy Launcher's tl.properties."""
    svc = get_legacy_service()
    versions = {v["version_id"]: v for v in svc.list_versions()}
    if params.version_id not in versions:
        return (
            f"Error: Version '{params.version_id}' is not installed in game/versions/. "
            f"Available versions: {', '.join(sorted(versions.keys())) or 'None'}."
        )

    updates: dict[str, Any] = {"login.version": params.version_id}
    if params.ram_mb is not None:
        updates["minecraft.xmx"] = str(params.ram_mb)

    write_tl_properties(svc.tl_properties_path, updates)
    return json.dumps(
        {
            "ok": True,
            "selected_version": versions[params.version_id],
            "ram_xmx": str(params.ram_mb) if params.ram_mb is not None else read_tl_properties(svc.tl_properties_path).get("minecraft.xmx", "auto"),
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="legacy_install_runtime",
    annotations={
        "title": "Install Client Engine into Legacy Launcher",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def legacy_install_runtime(params: InstallLegacyRuntimeInput) -> str:
    """Install a Minecraft client runtime (Vanilla, Fabric, Quilt, Forge, NeoForge) into Legacy Launcher's game/ directory."""
    svc = get_legacy_service()
    spec = RuntimeSpec(
        mc_version=params.mc_version,
        loader=params.loader,
        loader_version=params.loader_version,
        is_server=False,
    )
    try:
        installed_id = svc.provisioner.install_client_runtime(spec, mc_dir=svc.game_dir)
    except Exception as e:
        return f"Error: Failed to install runtime into Legacy Launcher: {str(e)}"

    if params.set_as_active:
        write_tl_properties(svc.tl_properties_path, {"login.version": installed_id})

    return json.dumps(
        {
            "ok": True,
            "installed_version_id": installed_id,
            "mc_version": params.mc_version,
            "loader": params.loader,
            "set_as_active": params.set_as_active,
            "game_dir": svc.game_dir,
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="legacy_list_installed_content",
    annotations={
        "title": "List Installed Mods, Shaders, or Resourcepacks in Legacy Launcher",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_list_installed_content(params: ListLegacyContentInput) -> str:
    """List installed files inside Legacy Launcher's game/mods, game/shaderpacks, or game/resourcepacks directory."""
    svc = get_legacy_service()
    target_dir = os.path.join(svc.game_dir, params.folder)
    exts = (".jar", ".jar.disabled") if params.folder == "mods" else (".zip", ".zip.disabled", ".jar", ".jar.disabled")
    items: list[dict[str, Any]] = []
    if os.path.isdir(target_dir):
        for fname in sorted(os.listdir(target_dir)):
            fpath = os.path.join(target_dir, fname)
            if not os.path.isfile(fpath):
                continue
            low = fname.lower()
            if not any(low.endswith(ext) for ext in exts):
                continue
            items.append({
                "filename": fname,
                "enabled": not low.endswith(".disabled"),
                "size_bytes": os.path.getsize(fpath),
            })

    payload = {
        "folder": params.folder,
        "directory": target_dir,
        "count": len(items),
        "enabled_count": sum(1 for i in items if i["enabled"]),
        "items": items,
    }

    def _md(d: dict[str, Any]) -> str:
        if not d["items"]:
            return f"No files found in Legacy Launcher `{d['folder']}`."
        lines = [f"# Legacy Launcher `{d['folder']}` ({d['enabled_count']}/{d['count']} enabled)"]
        for item in d["items"]:
            st = "enabled" if item["enabled"] else "disabled"
            lines.append(f"- `{item['filename']}` ({st}, {item['size_bytes']:,} B)")
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="legacy_install_modrinth_content",
    annotations={
        "title": "Install Modrinth Mod, Shader, or Modpack into Legacy Launcher",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def legacy_install_modrinth_content(params: InstallLegacyModrinthInput) -> str:
    """Resolve and install a Modrinth mod, shader, or modpack directly into Legacy Launcher's game directory."""
    svc = get_legacy_service()
    active_spec = svc.get_active_runtime_spec()
    eff_ver = params.game_version or active_spec.mc_version
    eff_loader = params.loader or (active_spec.loader if active_spec.loader != "vanilla" else None)

    policy = CompatibilityPolicy(
        content_type=params.content_type,
        game_version=eff_ver,
        loader=eff_loader,
    )

    if params.content_type == "modpack":
        art = svc.catalog.resolve_artifact(params.project_id, policy)
        if not art or not art.url:
            return f"Error: No compatible modpack found on Modrinth for '{params.project_id}'."
        res = svc.catalog.install_modpack(
            svc.game_dir,
            art.url,
            is_local=False,
            is_update=True,
        )
        if res.ok and res.version_id:
            write_tl_properties(svc.tl_properties_path, {"login.version": res.version_id})
        return json.dumps(
            {
                "ok": res.ok,
                "message": res.message,
                "project_id": params.project_id,
                "version_id": art.version_id,
                "installed_runtime_version": res.version_id,
                "rolled_back": res.rolled_back,
            },
            indent=2,
            ensure_ascii=False,
        )

    res = svc.catalog.install_artifact(
        svc.game_dir,
        policy,
        project_id=params.project_id,
        overwrite=params.overwrite,
    )
    return json.dumps(
        {
            "ok": res.ok,
            "message": res.message,
            "filename": res.filename,
            "version_id": res.version_id,
            "already_exists": res.already_exists,
            "resolved_mc_version": eff_ver,
            "resolved_loader": eff_loader,
            "target_dir": os.path.join(svc.game_dir, policy.target_subdir),
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="legacy_check_mod_updates",
    annotations={
        "title": "Check Legacy Launcher Mods for Modrinth Updates",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def legacy_check_mod_updates(params: CheckLegacyModUpdatesInput) -> str:
    """Check installed .jar mods in Legacy Launcher's game/mods/ folder against Modrinth SHA-1 hashes."""
    svc = get_legacy_service()
    active_spec = svc.get_active_runtime_spec()
    eff_ver = params.game_version or active_spec.mc_version
    eff_loader = params.loader or (active_spec.loader if active_spec.loader != "vanilla" else "fabric")

    mods_dir = os.path.join(svc.game_dir, "mods")
    if not os.path.isdir(mods_dir):
        return json.dumps({"checked_files": 0, "updates_count": 0, "updates": []}, indent=2)

    hash_to_file: dict[str, str] = {}
    for fname in sorted(os.listdir(mods_dir)):
        if not fname.lower().endswith(".jar"):
            continue
        fpath = os.path.join(mods_dir, fname)
        if not os.path.isfile(fpath):
            continue
        sha1 = hashlib.sha1()
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha1.update(chunk)
        hash_to_file[sha1.hexdigest()] = fname

    loaders = ["quilt", "fabric"] if eff_loader == "quilt" else [eff_loader]
    latest_map = svc.catalog.transport.check_version_updates(
        list(hash_to_file.keys()),
        loaders=loaders,
        game_versions=[eff_ver],
    )
    updates_list = []
    for h, latest_ver in (latest_map or {}).items():
        current_fname = hash_to_file.get(h, "")
        files = latest_ver.get("files") or []
        if not files:
            continue
        primary = next((f for f in files if f.get("primary")), files[0])
        latest_hashes = primary.get("hashes", {})
        if latest_hashes.get("sha1") and latest_hashes.get("sha1") != h:
            updates_list.append({
                "current_filename": current_fname,
                "latest_filename": primary.get("filename", ""),
                "project_id": latest_ver.get("project_id", ""),
                "version_id": latest_ver.get("id", ""),
                "version_number": latest_ver.get("version_number", ""),
                "download_url": primary.get("url", ""),
            })

    payload = {
        "mc_version": eff_ver,
        "loader": eff_loader,
        "checked_files": len(hash_to_file),
        "updates_count": len(updates_list),
        "updates": updates_list,
    }

    def _md(d: dict[str, Any]) -> str:
        lines = [
            f"# Legacy Launcher Mod Updates ({d['checked_files']} mods checked for MC `{d['mc_version']}` / `{d['loader']}`)",
            f"- **Updates Available**: `{d['updates_count']}`",
        ]
        for u in d["updates"]:
            lines.append(f"  - `{u['current_filename']}` -> `{u['latest_filename']}` (`{u['version_number']}`)")
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="legacy_manage_installed_content",
    annotations={
        "title": "Enable, Disable, or Delete Content in Legacy Launcher",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_manage_installed_content(params: ManageLegacyContentInput) -> str:
    """Enable, disable (.disabled suffix), or delete a mod, shaderpack, or resourcepack in Legacy Launcher."""
    if params.action == "delete" and not params.confirm:
        return "Error: Deletion aborted. Pass confirm=True when action='delete'."

    svc = get_legacy_service()
    folder_dir = os.path.realpath(os.path.join(svc.game_dir, params.folder))
    target_path = os.path.realpath(os.path.join(folder_dir, params.filename))
    if not target_path.startswith(folder_dir + os.sep) or not os.path.isfile(target_path):
        return f"Error: File '{params.filename}' not found inside Legacy Launcher '{params.folder}'."

    if params.action == "delete":
        os.remove(target_path)
        return json.dumps({"ok": True, "action": "delete", "filename": params.filename}, indent=2)

    if params.action == "disable":
        if target_path.lower().endswith(".disabled"):
            return json.dumps({"ok": True, "action": "disable", "filename": params.filename, "unchanged": True}, indent=2)
        new_path = target_path + ".disabled"
        os.replace(target_path, new_path)
        return json.dumps({"ok": True, "action": "disable", "new_filename": os.path.basename(new_path)}, indent=2)

    if not target_path.lower().endswith(".disabled"):
        return json.dumps({"ok": True, "action": "enable", "filename": params.filename, "unchanged": True}, indent=2)
    new_path = target_path[: -len(".disabled")]
    os.replace(target_path, new_path)
    return json.dumps({"ok": True, "action": "enable", "new_filename": os.path.basename(new_path)}, indent=2)


def _zip_directory(src_dir: str, zip_path: str) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".lock"):
                    continue
                full = os.path.join(root, file)
                rel = os.path.relpath(full, src_dir)
                try:
                    zf.write(full, rel)
                    count += 1
                except OSError:
                    pass
    return count


@mcp.tool(
    name="legacy_list_worlds_and_backups",
    annotations={
        "title": "List Singleplayer Worlds and Backups in Legacy Launcher",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_list_worlds_and_backups(params: ListLegacyWorldsInput) -> str:
    """List singleplayer world saves in game/saves/ and backup archives in game/backups/."""
    svc = get_legacy_service()
    saves_dir = os.path.join(svc.game_dir, "saves")
    backups_dir = os.path.join(svc.game_dir, "backups")

    worlds = []
    if os.path.isdir(saves_dir):
        for w in sorted(os.listdir(saves_dir)):
            w_path = os.path.join(saves_dir, w)
            if os.path.isdir(w_path) and not w.startswith("."):
                has_level = os.path.isfile(os.path.join(w_path, "level.dat"))
                worlds.append({"world_name": w, "has_level_dat": has_level, "path": w_path})

    backups = (
        sorted(f for f in os.listdir(backups_dir) if f.lower().endswith(".zip"))
        if os.path.isdir(backups_dir)
        else []
    )

    payload = {
        "worlds_count": len(worlds),
        "worlds": worlds,
        "backups_count": len(backups),
        "backups": backups,
    }

    def _md(d: dict[str, Any]) -> str:
        lines = [
            f"# Legacy Launcher Worlds ({d['worlds_count']}) & Backups ({d['backups_count']})",
            "## Worlds (`game/saves/`)",
        ]
        for w in d["worlds"]:
            lines.append(f"- **{w['world_name']}** (`{w['path']}`)")
        if not d["worlds"]:
            lines.append("- _None_")
        lines.append("## Backups (`game/backups/`)")
        for b in d["backups"]:
            lines.append(f"- `{b}`")
        if not d["backups"]:
            lines.append("- _None_")
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="legacy_backup_world",
    annotations={
        "title": "Create a Singleplayer World Backup in Legacy Launcher",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def legacy_backup_world(params: BackupLegacyWorldInput) -> str:
    """Create a timestamped .zip backup of a world in game/saves/<world_name> into game/backups/."""
    svc = get_legacy_service()
    saves_dir = os.path.realpath(os.path.join(svc.game_dir, "saves"))
    world_dir = os.path.realpath(os.path.join(saves_dir, params.world_name))
    if not world_dir.startswith(saves_dir + os.sep) or not os.path.isdir(world_dir):
        return f"Error: World '{params.world_name}' not found in Legacy Launcher saves/."

    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_world = re.sub(r"[^a-zA-Z0-9_-]", "_", params.world_name)
    label_part = ""
    if params.label:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", params.label)
        if cleaned:
            label_part = f"_{cleaned}"
    zip_name = f"world_{safe_world}_{ts}{label_part}.zip"
    zip_path = os.path.join(svc.game_dir, "backups", zip_name)
    archived = _zip_directory(world_dir, zip_path)
    return json.dumps(
        {
            "ok": True,
            "world_name": params.world_name,
            "backup_filename": zip_name,
            "backup_path": zip_path,
            "files_archived": archived,
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="legacy_restore_world_backup",
    annotations={
        "title": "Restore a Singleplayer World Backup in Legacy Launcher",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_restore_world_backup(params: RestoreLegacyWorldBackupInput) -> str:
    """Restore a world backup .zip from game/backups/ into game/saves/<world_name> with zip-slip protection."""
    if not params.confirm:
        return "Error: Restore aborted. Pass confirm=True to overwrite the world folder."

    svc = get_legacy_service()
    backups_dir = os.path.realpath(os.path.join(svc.game_dir, "backups"))
    zip_path = os.path.realpath(os.path.join(backups_dir, params.backup_filename))
    if not zip_path.startswith(backups_dir + os.sep) or not os.path.isfile(zip_path):
        return f"Error: Backup '{params.backup_filename}' not found in game/backups/."

    saves_dir = os.path.realpath(os.path.join(svc.game_dir, "saves"))
    world_dir = os.path.realpath(os.path.join(saves_dir, params.world_name))
    if not world_dir.startswith(saves_dir + os.sep):
        return "Error: Invalid world_name path."

    safety_backup = None
    if params.create_safety_backup and os.path.isdir(world_dir):
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_world = re.sub(r"[^a-zA-Z0-9_-]", "_", params.world_name)
        safety_backup = f"pre_restore_{safe_world}_{ts}.zip"
        _zip_directory(world_dir, os.path.join(backups_dir, safety_backup))

    real_world_dir = os.path.realpath(world_dir)
    os.makedirs(real_world_dir, exist_ok=True)
    base_prefix = real_world_dir + os.sep
    extracted = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = os.path.realpath(os.path.join(real_world_dir, member.filename))
            if not (member_path.startswith(base_prefix) or member_path == real_world_dir):
                continue
            zf.extract(member, real_world_dir)
            extracted += 1

    return json.dumps(
        {
            "ok": True,
            "world_name": params.world_name,
            "restored_from": params.backup_filename,
            "safety_backup_created": safety_backup,
            "extracted_entries": extracted,
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="legacy_get_logs_and_crashes",
    annotations={
        "title": "Read Legacy Launcher Latest Log and Crash Reports",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_get_logs_and_crashes(params: GetLegacyLogsInput) -> str:
    """Read tail lines of game/logs/latest.log and the newest crash report in game/crash-reports/."""
    svc = get_legacy_service()
    log_path = os.path.join(svc.game_dir, "logs", "latest.log")
    log_tail: list[str] = []
    if params.log_lines > 0 and os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip("\r\n") for ln in f.readlines()]
                log_tail = lines[-params.log_lines :]
        except Exception:
            pass

    crash_dir = os.path.join(svc.game_dir, "crash-reports")
    crash_files: list[str] = []
    latest_crash_name = ""
    latest_crash_excerpt: list[str] = []
    if os.path.isdir(crash_dir):
        crash_files = sorted(
            [f for f in os.listdir(crash_dir) if f.endswith(".txt")],
            key=lambda fn: os.path.getmtime(os.path.join(crash_dir, fn)),
            reverse=True,
        )
        if params.include_latest_crash and crash_files:
            latest_crash_name = crash_files[0]
            try:
                with open(os.path.join(crash_dir, latest_crash_name), "r", encoding="utf-8", errors="replace") as cf:
                    latest_crash_excerpt = [ln.rstrip("\r\n") for ln in cf.readlines()[:40]]
            except Exception:
                pass

    payload = {
        "latest_log_path": log_path,
        "latest_log_tail": log_tail,
        "crash_reports_count": len(crash_files),
        "crash_reports": crash_files[:10],
        "latest_crash_name": latest_crash_name,
        "latest_crash_excerpt": latest_crash_excerpt,
    }

    def _md(d: dict[str, Any]) -> str:
        lines = [
            "# Legacy Launcher Logs & Crash Reports",
            f"- **Crash Reports Found**: `{d['crash_reports_count']}`",
        ]
        if d["latest_crash_name"]:
            lines.append(f"\n## Newest Crash Report (`{d['latest_crash_name']}`)")
            lines.append("```text")
            lines.extend(d["latest_crash_excerpt"])
            lines.append("```")
        if d["latest_log_tail"]:
            lines.append("\n## Latest Log Tail (`logs/latest.log`)")
            lines.append("```text")
            lines.extend(d["latest_log_tail"])
            lines.append("```")
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="legacy_sync_with_vega",
    annotations={
        "title": "Synchronize Profiles Between Vega Launcher and Legacy Launcher",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def legacy_sync_with_vega(params: SyncLegacyWithVegaInput) -> str:
    """Bi-directional profile sync between Vega Launcher and Legacy Launcher's game directory."""
    svc = get_legacy_service()
    profiles, ms_login, settings = svc.vega_store.load()

    if params.direction == "vega_to_legacy":
        svc.vega_store.sync_with_standard_launchers(profiles, mc_dir=svc.game_dir)
        return json.dumps(
            {
                "ok": True,
                "direction": "vega_to_legacy",
                "synced_profiles_count": len(profiles),
                "target_game_dir": svc.game_dir,
            },
            indent=2,
            ensure_ascii=False,
        )

    # legacy_to_vega: import Legacy Launcher installed versions as Vega profiles if not already present
    existing_names = {
        str(p.get("name", "")).lower()
        for p in profiles.values()
        if isinstance(p, dict)
    }
    imported: list[str] = []
    for v in svc.list_versions():
        vid = v["version_id"]
        prof_name = f"Legacy - {vid}"
        if prof_name.lower() in existing_names:
            continue
        _, prof_path = svc.vega_store.generate_unique_profile_name(prof_name, profiles)
        os.makedirs(os.path.join(prof_path, "mods"), exist_ok=True)
        import uuid
        profiles[str(uuid.uuid4())] = {
            "name": prof_name,
            "version": vid,
            "game_version": v["mc_version"],
            "loader": v["loader"],
            "ram": int(settings.get("default_ram", 4096) or 4096),
            "path": prof_path,
        }
        imported.append(prof_name)

    if imported:
        svc.vega_store.save(profiles, ms_login, settings)

    return json.dumps(
        {
            "ok": True,
            "direction": "legacy_to_vega",
            "imported_count": len(imported),
            "imported_profiles": imported,
        },
        indent=2,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")

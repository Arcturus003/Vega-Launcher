from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import sys
import uuid
import zipfile
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - fallback for mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore

try:
    import PySide6.QtCore  # noqa: F401
except ImportError:  # pragma: no cover - headless environment without Qt
    import types

    class _HeadlessQtModule(types.ModuleType):
        def __getattr__(self, name: str):
            if name.startswith("__"):
                raise AttributeError(name)
            return type(name, (), {"__init__": lambda self, *a, **kw: None})

    _qt_pkg = _HeadlessQtModule("PySide6")
    _qt_pkg.__path__ = []  # type: ignore
    for _sub in ("QtCore", "QtWidgets", "QtGui", "QtWebEngineWidgets", "QtWebEngineCore", "QtMultimedia"):
        _mod = _HeadlessQtModule(f"PySide6.{_sub}")
        if _sub == "QtCore":
            _mod.Signal = lambda *a, **kw: None  # type: ignore
        setattr(_qt_pkg, _sub, _mod)
        sys.modules.setdefault(f"PySide6.{_sub}", _mod)
    sys.modules.setdefault("PySide6", _qt_pkg)
    try:
        import minecraft_launcher_lib  # noqa: F401
    except ImportError:
        sys.modules.setdefault("minecraft_launcher_lib", _HeadlessQtModule("minecraft_launcher_lib"))

from backup_manager import BackupManager
from mod_manager import CompatibilityPolicy, ContentCatalog, ModrinthAPI
from profile_store import DEFAULT_SETTINGS, ProfileAndConfigStore
from runtime_provisioner import RuntimeProvisioner, RuntimeSpec


mcp = MCPServer("vega_mcp")

SAFE_SETTING_KEYS = frozenset(DEFAULT_SETTINGS.keys())


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


def _format_output(data: dict[str, Any], fmt: ResponseFormat, markdown_builder) -> str:
    if fmt == ResponseFormat.JSON:
        return json.dumps(data, indent=2, ensure_ascii=False)
    return markdown_builder(data)


def _list_content_files(directory: str, extensions: tuple[str, ...] = (".jar", ".jar.disabled", ".zip")) -> list[dict[str, Any]]:
    if not directory or not os.path.isdir(directory):
        return []
    items: list[dict[str, Any]] = []
    for fname in sorted(os.listdir(directory)):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        low = fname.lower()
        if not any(low.endswith(ext) for ext in extensions):
            continue
        enabled = not low.endswith(".disabled")
        try:
            size_bytes = os.path.getsize(fpath)
        except OSError:
            size_bytes = 0
        items.append({
            "filename": fname,
            "enabled": enabled,
            "size_bytes": size_bytes,
        })
    return items


def _read_server_properties(prop_path: str) -> dict[str, str]:
    from server_instance import ServerInstance
    server_dir = os.path.dirname(os.path.abspath(prop_path))
    return ServerInstance(server_dir).read_raw_properties()


def _write_server_properties(prop_path: str, updates: dict[str, Any]) -> dict[str, str]:
    from server_instance import ServerInstance
    server_dir = os.path.dirname(os.path.abspath(prop_path))
    return ServerInstance(server_dir).update_raw_properties(updates)


class VegaMCPService:
    """
    Headless facade over Vega Launcher's deep modules (ProfileAndConfigStore,
    ContentCatalog, RuntimeProvisioner, and local servers/backups).
    """

    def __init__(
        self,
        store: Optional[ProfileAndConfigStore] = None,
        catalog: Optional[ContentCatalog] = None,
        provisioner: Optional[RuntimeProvisioner] = None,
        servers_dir: Optional[str | Path] = None,
    ):
        self.store = store or ProfileAndConfigStore()
        self.store.ensure_directories()
        self.mc_dir = self.store.mc_dir
        self.catalog = catalog or ContentCatalog(mc_dir=self.mc_dir)
        self.provisioner = provisioner or RuntimeProvisioner(mc_dir=self.mc_dir)
        self.servers_dir = str(servers_dir) if servers_dir else os.path.join(self.store.data_dir, "servers")
        os.makedirs(self.servers_dir, exist_ok=True)

    def is_safe_server_path(self, target_path: str | Path) -> bool:
        if not target_path:
            return False
        real_target = os.path.realpath(str(target_path))
        real_base = os.path.realpath(self.servers_dir) + os.sep
        return real_target.startswith(real_base)

    def resolve_server_dir(self, server_name: str, must_exist: bool = True) -> tuple[Optional[str], Optional[str]]:
        clean = (server_name or "").strip()
        if not clean or "/" in clean or "\\" in clean or clean in (".", ".."):
            return None, "Error: Invalid server_name. Use a simple folder name without path separators."
        candidate = os.path.join(self.servers_dir, clean)
        if not self.is_safe_server_path(candidate):
            return None, "Error: Server path escapes containment boundary."
        if must_exist and not os.path.isdir(candidate):
            return None, f"Error: Server '{clean}' not found. Run vega_list_servers to see available servers."
        return candidate, None

    def resolve_profile(self, identifier: str) -> tuple[Optional[str], Optional[dict], dict[str, dict], dict[str, Any], dict[str, Any]]:
        profiles, ms_login, settings = self.store.load()
        target_id = None
        target_data = None
        clean = (identifier or "").strip()
        if clean in profiles and isinstance(profiles[clean], dict):
            target_id = clean
            target_data = profiles[clean]
        else:
            for pid, pdata in profiles.items():
                if isinstance(pdata, dict) and str(pdata.get("name", "")).lower() == clean.lower():
                    target_id = pid
                    target_data = pdata
                    break
        return target_id, target_data, profiles, ms_login, settings

    def summarize_profile(self, profile_id: str, pdata: dict[str, Any]) -> dict[str, Any]:
        spec = RuntimeProvisioner.detect_client_runtime(pdata)
        prof_path = pdata.get("path") or os.path.join(self.store.profiles_dir, pdata.get("name") or profile_id)
        mods = _list_content_files(os.path.join(prof_path, "mods"), (".jar", ".jar.disabled"))
        shaders = _list_content_files(os.path.join(prof_path, "shaderpacks"), (".zip", ".zip.disabled"))
        return {
            "profile_id": profile_id,
            "name": pdata.get("name", profile_id),
            "version": pdata.get("version", spec.mc_version),
            "game_version": spec.mc_version,
            "loader": spec.loader,
            "ram_mb": int(pdata.get("ram", 4096) or 4096),
            "path": prof_path,
            "project_id": pdata.get("project_id", ""),
            "version_id": pdata.get("version_id", ""),
            "mods_count": len(mods),
            "enabled_mods_count": sum(1 for m in mods if m["enabled"]),
            "shaders_count": len(shaders),
        }

    def summarize_server(self, server_name: str) -> dict[str, Any]:
        s_dir = os.path.join(self.servers_dir, server_name)
        spec = RuntimeProvisioner.detect_server_runtime(s_dir)
        props = _read_server_properties(os.path.join(s_dir, "server.properties"))
        mods = _list_content_files(os.path.join(s_dir, "mods"), (".jar", ".jar.disabled"))
        plugins = _list_content_files(os.path.join(s_dir, "plugins"), (".jar", ".jar.disabled"))
        backups_dir = os.path.join(s_dir, "backups")
        backups = (
            [f for f in sorted(os.listdir(backups_dir)) if f.lower().endswith(".zip")]
            if os.path.isdir(backups_dir)
            else []
        )
        return {
            "server_name": server_name,
            "path": s_dir,
            "mc_version": spec.mc_version,
            "loader": spec.loader,
            "port": props.get("server-port", "25565"),
            "motd": props.get("motd", ""),
            "max_players": props.get("max-players", "20"),
            "online_mode": props.get("online-mode", "true"),
            "has_world": os.path.isdir(os.path.join(s_dir, "world")),
            "mods_count": len(mods),
            "plugins_count": len(plugins),
            "backups_count": len(backups),
        }


_DEFAULT_SERVICE: Optional[VegaMCPService] = None


def get_service() -> VegaMCPService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = VegaMCPService()
    return _DEFAULT_SERVICE


def set_service(service: Optional[VegaMCPService]) -> None:
    global _DEFAULT_SERVICE
    _DEFAULT_SERVICE = service


# ============================================================================
# Input Models (Pydantic v2)
# ============================================================================

class BaseToolInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )


class ListProfilesInput(BaseToolInput):
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of profiles to return (1-100).")
    offset: int = Field(default=0, ge=0, description="Number of profiles to skip for pagination.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class GetProfileInput(BaseToolInput):
    profile: str = Field(..., min_length=1, max_length=120, description="Profile name or UUID (e.g., 'Survival 1.20.1').")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class SaveProfileInput(BaseToolInput):
    name: str = Field(..., min_length=1, max_length=80, description="Profile display name (e.g., 'Fabric Tech').")
    game_version: str = Field(default="1.20.1", min_length=3, max_length=32, description="Minecraft base version (e.g., '1.20.1', '1.21.1').")
    loader: Literal["vanilla", "fabric", "quilt", "forge", "neoforge"] = Field(
        default="vanilla",
        description="Mod loader type: 'vanilla', 'fabric', 'quilt', 'forge', or 'neoforge'.",
    )
    version: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional explicit launcher version ID (e.g., 'fabric-loader-0.16.9-1.20.1'). Defaults to game_version.",
    )
    ram_mb: int = Field(default=4096, ge=1024, le=65536, description="Allocated RAM in megabytes (1024-65536).")
    jvm_args: Optional[str] = Field(default=None, max_length=500, description="Optional custom JVM arguments.")
    profile_id: Optional[str] = Field(default=None, max_length=80, description="Optional existing profile ID/name to update in-place.")

    @field_validator("name")
    @classmethod
    def validate_safe_name(cls, v: str) -> str:
        if "/" in v or "\\" in v or v in (".", ".."):
            raise ValueError("Profile name must not contain path separators or relative traversal segments.")
        return v


class DeleteProfileInput(BaseToolInput):
    profile: str = Field(..., min_length=1, max_length=120, description="Profile name or UUID to delete.")
    delete_files: bool = Field(default=True, description="Whether to also delete the profile folder on disk.")
    confirm: bool = Field(default=False, description="Must be set to True to confirm permanent profile deletion.")


class GetSettingsInput(BaseToolInput):
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class UpdateSettingsInput(BaseToolInput):
    updates: Dict[str, Any] = Field(
        ...,
        description="Dictionary of safe launcher setting keys and values to update (e.g. {'default_ram': 8192, 'theme': 'cyber_emerald'}).",
    )


class SearchModrinthInput(BaseToolInput):
    query: str = Field(default="", max_length=120, description="Search keywords (e.g., 'sodium', 'iris', 'worldedit').")
    content_type: Literal["mod", "shader", "plugin", "modpack"] = Field(
        default="mod",
        description="Content type to search: 'mod', 'shader', 'plugin', or 'modpack'.",
    )
    game_version: Optional[str] = Field(default=None, max_length=32, description="Filter by Minecraft version (e.g., '1.20.1').")
    loader: Optional[str] = Field(default=None, max_length=32, description="Filter by loader (e.g., 'fabric', 'forge', 'neoforge', 'quilt', 'purpur').")
    sort_by: Literal["relevance", "downloads", "follows", "newest", "updated"] = Field(
        default="relevance",
        description="Sort order for Modrinth results.",
    )
    category: Optional[str] = Field(default=None, max_length=64, description="Optional Modrinth category filter.")
    limit: int = Field(default=12, ge=1, le=50, description="Maximum number of results to return (1-50).")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class GetModrinthProjectInput(BaseToolInput):
    project_id: str = Field(..., min_length=1, max_length=80, description="Modrinth project ID or slug (e.g., 'AANobbMI' or 'sodium').")
    content_type: Literal["mod", "shader", "plugin", "modpack"] = Field(default="mod", description="Content type for compatibility filtering.")
    game_version: Optional[str] = Field(default=None, max_length=32, description="Optional Minecraft version filter for versions list.")
    loader: Optional[str] = Field(default=None, max_length=32, description="Optional loader filter for versions list.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class InstallModrinthContentInput(BaseToolInput):
    project_id: str = Field(..., min_length=1, max_length=80, description="Modrinth project ID or slug to install.")
    content_type: Literal["mod", "shader", "plugin", "modpack"] = Field(
        default="mod",
        description="Type of content: 'mod', 'shader', 'plugin', or 'modpack'.",
    )
    target_type: Literal["profile", "server"] = Field(
        default="profile",
        description="Install into a client 'profile' or a local 'server'.",
    )
    target_name: str = Field(..., min_length=1, max_length=120, description="Target profile name/ID or server name.")
    game_version: Optional[str] = Field(default=None, max_length=32, description="Override game version if not auto-detected from target.")
    loader: Optional[str] = Field(default=None, max_length=32, description="Override loader if not auto-detected from target.")
    overwrite: bool = Field(default=False, description="Whether to overwrite if the artifact file already exists.")


class CheckModUpdatesInput(BaseToolInput):
    target_type: Literal["profile", "server", "modpacks"] = Field(
        default="profile",
        description="Check updates for a client 'profile', a local 'server', or all tracked 'modpacks'.",
    )
    target_name: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Profile name/ID or server name (required when target_type is 'profile' or 'server').",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class ManageInstalledContentInput(BaseToolInput):
    target_type: Literal["profile", "server"] = Field(..., description="Whether the target is a client 'profile' or local 'server'.")
    target_name: str = Field(..., min_length=1, max_length=120, description="Profile name/ID or server name.")
    folder: Literal["mods", "shaderpacks", "plugins"] = Field(default="mods", description="Subfolder containing the file: 'mods', 'shaderpacks', or 'plugins'.")
    filename: str = Field(..., min_length=1, max_length=200, description="Exact filename inside the subfolder (e.g., 'sodium-fabric.jar').")
    action: Literal["enable", "disable", "delete"] = Field(..., description="Action to perform: 'enable', 'disable', or 'delete'.")
    confirm: bool = Field(default=False, description="Required to be True when action='delete'.")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("filename must be a basename without directory traversal.")
        return v


class DetectRuntimeInput(BaseToolInput):
    target_type: Literal["profile", "server"] = Field(..., description="Inspect a client 'profile' or local 'server'.")
    target_name: str = Field(..., min_length=1, max_length=120, description="Profile name/ID or server folder name.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class InstallClientRuntimeInput(BaseToolInput):
    mc_version: str = Field(..., min_length=3, max_length=32, description="Minecraft version to install (e.g., '1.20.1').")
    loader: Literal["vanilla", "fabric", "quilt", "forge", "neoforge"] = Field(
        default="vanilla",
        description="Client engine loader to install.",
    )
    loader_version: Optional[str] = Field(default=None, max_length=64, description="Optional specific loader version.")
    profile: Optional[str] = Field(default=None, max_length=120, description="Optional profile name/ID to update with the installed version ID.")


class ProvisionServerInput(BaseToolInput):
    server_name: str = Field(..., min_length=1, max_length=80, description="Local server folder name under servers/ (e.g., 'SurvivalServer').")
    software: Literal["purpur", "fabric", "forge", "neoforge"] = Field(
        default="purpur",
        description="Server software engine to provision: 'purpur', 'fabric', 'forge', or 'neoforge'.",
    )
    mc_version: str = Field(default="1.20.1", min_length=3, max_length=32, description="Minecraft version (e.g., '1.20.1', '1.21.1').")
    accept_eula: bool = Field(default=True, description="Automatically write eula=true to eula.txt.")


class ListServersInput(BaseToolInput):
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of servers to return.")
    offset: int = Field(default=0, ge=0, description="Number of servers to skip for pagination.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class GetServerDetailsInput(BaseToolInput):
    server_name: str = Field(..., min_length=1, max_length=80, description="Name of the local server inside servers/.")
    log_lines: int = Field(default=30, ge=0, le=200, description="Number of tail lines to include from logs/latest.log (0-200).")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format: 'markdown' or 'json'.")


class UpdateServerPropertiesInput(BaseToolInput):
    server_name: str = Field(..., min_length=1, max_length=80, description="Name of the local server inside servers/.")
    properties: Dict[str, Any] = Field(
        ...,
        description="Key-value pairs to update in server.properties (e.g. {'motd': 'Vega Server', 'max-players': 32, 'online-mode': 'false'}).",
    )


class CreateServerBackupInput(BaseToolInput):
    server_name: str = Field(..., min_length=1, max_length=80, description="Name of the local server to back up.")
    label: Optional[str] = Field(default=None, max_length=40, description="Optional alphanumeric label suffix for the backup zip filename.")


class RestoreServerBackupInput(BaseToolInput):
    server_name: str = Field(..., min_length=1, max_length=80, description="Name of the local server to restore into.")
    backup_filename: str = Field(..., min_length=1, max_length=160, description="Backup .zip filename inside the server's backups/ directory.")
    confirm: bool = Field(default=False, description="Must be True to confirm overwriting server files from the backup.")
    create_safety_backup: bool = Field(default=True, description="Automatically create a pre-restore safety snapshot before extracting.")


class DeleteServerInput(BaseToolInput):
    server_name: str = Field(..., min_length=1, max_length=80, description="Name of the local server to permanently delete.")
    confirm: bool = Field(default=False, description="Must be True to confirm permanent server deletion.")


# ============================================================================
# Domain 1: Profiles & Launcher Settings Tools
# ============================================================================

@mcp.tool(
    name="vega_list_profiles",
    annotations={
        "title": "List Vega Launcher Client Profiles",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_list_profiles(params: ListProfilesInput) -> str:
    """List all client profiles registered or discovered in Vega Launcher with pagination.

    Returns each profile's ID, name, Minecraft version, detected mod loader, allocated RAM,
    and installed mod/shader counts.
    """
    svc = get_service()
    profiles, _ms_login, _settings = svc.store.load()
    all_items = [
        svc.summarize_profile(pid, pdata)
        for pid, pdata in sorted(
            profiles.items(),
            key=lambda kv: str(kv[1].get("name", kv[0])).lower() if isinstance(kv[1], dict) else "",
        )
        if isinstance(pdata, dict)
    ]
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
            return "No client profiles found."
        lines = [f"# Vega Client Profiles ({d['count']} of {d['total']})"]
        for item in d["items"]:
            lines.append(
                f"- **{item['name']}** (`{item['profile_id']}`) — MC `{item['game_version']}` "
                f"| Loader: `{item['loader']}` | RAM: `{item['ram_mb']} MB` "
                f"| Mods: `{item['enabled_mods_count']}/{item['mods_count']}` | Shaders: `{item['shaders_count']}`"
            )
        if d["has_more"]:
            lines.append(f"\n_More results available (next_offset={d['next_offset']})._")
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="vega_get_profile",
    annotations={
        "title": "Get Vega Client Profile Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_get_profile(params: GetProfileInput) -> str:
    """Inspect a specific client profile, including its runtime specification, mods, and shaderpacks."""
    svc = get_service()
    pid, pdata, _profiles, _ms_login, _settings = svc.resolve_profile(params.profile)
    if not pid or not pdata:
        return f"Error: Profile '{params.profile}' not found. Use vega_list_profiles to view valid profile names and IDs."

    summary = svc.summarize_profile(pid, pdata)
    prof_path = summary["path"]
    summary["jvm_args"] = pdata.get("jvm_args", "")
    summary["java_path"] = pdata.get("java_path", "")
    summary["mods"] = _list_content_files(os.path.join(prof_path, "mods"), (".jar", ".jar.disabled"))
    summary["shaderpacks"] = _list_content_files(os.path.join(prof_path, "shaderpacks"), (".zip", ".zip.disabled"))

    def _md(d: dict[str, Any]) -> str:
        lines = [
            f"# Profile: {d['name']} (`{d['profile_id']}`)",
            f"- **Game Version**: `{d['game_version']}` (Version ID: `{d['version']}`)",
            f"- **Loader**: `{d['loader']}`",
            f"- **RAM**: `{d['ram_mb']} MB`",
            f"- **Directory**: `{d['path']}`",
            f"- **Installed Mods ({len(d['mods'])})**:",
        ]
        for m in d["mods"][:50]:
            state = "enabled" if m["enabled"] else "disabled"
            lines.append(f"  - `{m['filename']}` ({state}, {m['size_bytes']} B)")
        if not d["mods"]:
            lines.append("  - _None_")
        lines.append(f"- **Installed Shaderpacks ({len(d['shaderpacks'])})**:")
        for s in d["shaderpacks"][:50]:
            state = "enabled" if s["enabled"] else "disabled"
            lines.append(f"  - `{s['filename']}` ({state}, {s['size_bytes']} B)")
        if not d["shaderpacks"]:
            lines.append("  - _None_")
        return "\n".join(lines)

    return _format_output(summary, params.response_format, _md)


@mcp.tool(
    name="vega_save_profile",
    annotations={
        "title": "Create or Update a Vega Client Profile",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_save_profile(params: SaveProfileInput) -> str:
    """Create a new client profile or update an existing one, creating its directory structure and syncing launcher_profiles.json."""
    svc = get_service()
    profiles, ms_login, settings = svc.store.load()

    target_id = None
    existing_data: dict[str, Any] = {}
    if params.profile_id:
        pid, pdata, _, _, _ = svc.resolve_profile(params.profile_id)
        if not pid or not pdata:
            return f"Error: Profile '{params.profile_id}' not found for update."
        target_id = pid
        existing_data = dict(pdata)
    else:
        for pid, pdata in profiles.items():
            if isinstance(pdata, dict) and str(pdata.get("name", "")).lower() == params.name.lower():
                target_id = pid
                existing_data = dict(pdata)
                break

    if not target_id:
        target_id = str(uuid.uuid4())

    existing_path = existing_data.get("path")
    if existing_path and svc.store.is_safe_profile_path(existing_path):
        prof_path = existing_path
    else:
        prof_path = os.path.join(svc.store.profiles_dir, params.name)
        if not svc.store.is_safe_profile_path(prof_path):
            return "Error: Profile path failed containment validation."

    os.makedirs(os.path.join(prof_path, "mods"), exist_ok=True)
    os.makedirs(os.path.join(prof_path, "shaderpacks"), exist_ok=True)
    os.makedirs(os.path.join(prof_path, "config"), exist_ok=True)

    updated = {
        **existing_data,
        "name": params.name,
        "game_version": params.game_version,
        "loader": params.loader,
        "version": params.version or existing_data.get("version") or params.game_version,
        "ram": params.ram_mb,
        "path": prof_path,
    }
    if params.jvm_args is not None:
        updated["jvm_args"] = params.jvm_args

    profiles[target_id] = updated
    svc.store.save(profiles, ms_login, settings)
    return json.dumps(
        {
            "ok": True,
            "message": f"Profile '{params.name}' saved.",
            "profile": svc.summarize_profile(target_id, updated),
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="vega_delete_profile",
    annotations={
        "title": "Delete a Vega Client Profile",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_delete_profile(params: DeleteProfileInput) -> str:
    """Delete a client profile from launcher_config.json and optionally remove its folder on disk.

    Requires confirm=True to prevent accidental data loss.
    """
    if not params.confirm:
        return "Error: Deletion aborted. Pass confirm=True to permanently delete this profile."

    svc = get_service()
    pid, pdata, profiles, ms_login, settings = svc.resolve_profile(params.profile)
    if not pid or not pdata:
        return f"Error: Profile '{params.profile}' not found."

    prof_name = pdata.get("name", pid)
    prof_path = pdata.get("path") or os.path.join(svc.store.profiles_dir, prof_name)
    if params.delete_files and prof_path:
        ok, reason = svc.store.delete_profile_directory(prof_path)
        if not ok:
            return f"Error: Could not delete profile directory '{prof_path}' (reason: {reason})."

    del profiles[pid]
    svc.store.save(profiles, ms_login, settings)
    return json.dumps(
        {
            "ok": True,
            "deleted_profile_id": pid,
            "deleted_name": prof_name,
            "deleted_files": params.delete_files,
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="vega_get_settings",
    annotations={
        "title": "Get Safe Vega Launcher Settings",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_get_settings(params: GetSettingsInput) -> str:
    """Read safe Vega Launcher configuration settings.

    Strictly redacts all authentication tokens (ms_login) and only exposes safe preferences.
    """
    svc = get_service()
    _profiles, ms_login, settings = svc.store.load()
    safe_settings = {k: settings.get(k, DEFAULT_SETTINGS.get(k)) for k in sorted(SAFE_SETTING_KEYS)}
    ms_username = (
        str(ms_login.get("name") or ms_login.get("username") or "")
        if isinstance(ms_login, dict)
        else ""
    )
    payload = {
        "settings": safe_settings,
        "has_microsoft_session": bool(ms_username),
        "microsoft_username": ms_username,
    }

    def _md(d: dict[str, Any]) -> str:
        lines = ["# Vega Launcher Settings"]
        for k, v in d["settings"].items():
            lines.append(f"- **{k}**: `{v}`")
        lines.append(f"- **has_microsoft_session**: `{d['has_microsoft_session']}`")
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="vega_update_settings",
    annotations={
        "title": "Update Safe Vega Launcher Settings",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_update_settings(params: UpdateSettingsInput) -> str:
    """Update one or more safe Vega Launcher preferences (e.g., default_ram, theme, language, particles_enabled)."""
    disallowed = [k for k in params.updates.keys() if k not in SAFE_SETTING_KEYS]
    if disallowed:
        return (
            f"Error: Unknown or protected setting key(s): {', '.join(disallowed)}. "
            f"Allowed keys: {', '.join(sorted(SAFE_SETTING_KEYS))}."
        )

    svc = get_service()
    for k, v in params.updates.items():
        svc.store.update_setting(k, v)

    _profiles, _ms_login, settings = svc.store.load()
    safe_settings = {k: settings.get(k, DEFAULT_SETTINGS.get(k)) for k in sorted(SAFE_SETTING_KEYS)}
    return json.dumps({"ok": True, "updated_keys": list(params.updates.keys()), "settings": safe_settings}, indent=2)


# ============================================================================
# Domain 2: Modrinth Content Catalog & Mod Management Tools
# ============================================================================

@mcp.tool(
    name="vega_search_modrinth",
    annotations={
        "title": "Search Modrinth Catalog",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def vega_search_modrinth(params: SearchModrinthInput) -> str:
    """Search Modrinth for mods, shaders, plugins, or modpacks using Vega's CompatibilityPolicy rules."""
    svc = get_service()
    policy = CompatibilityPolicy(
        content_type=params.content_type,
        game_version=params.game_version,
        loader=params.loader,
    )
    hits = svc.catalog.search(
        params.query,
        policy,
        index=params.sort_by,
        limit=params.limit,
        category=params.category,
    )
    items = []
    for h in hits or []:
        items.append({
            "project_id": h.get("project_id") or h.get("slug", ""),
            "slug": h.get("slug", ""),
            "title": h.get("title", ""),
            "author": h.get("author", ""),
            "description": h.get("description", ""),
            "downloads": h.get("downloads", 0),
            "categories": h.get("categories", []),
            "versions": (h.get("versions") or [])[-5:],
        })

    payload = {
        "query": params.query,
        "content_type": params.content_type,
        "game_version": params.game_version,
        "loader": params.loader,
        "count": len(items),
        "items": items,
    }

    def _md(d: dict[str, Any]) -> str:
        if not d["items"]:
            return "No matching Modrinth projects found. Try broadening `game_version` or `loader` filters."
        lines = [f"# Modrinth Search Results ({d['count']} items)"]
        for item in d["items"]:
            lines.append(
                f"- **{item['title']}** (`{item['project_id']}`) by {item['author']} — "
                f"{item['downloads']:,} downloads\n  {item['description']}"
            )
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="vega_get_modrinth_project",
    annotations={
        "title": "Get Modrinth Project Details and Compatible Versions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def vega_get_modrinth_project(params: GetModrinthProjectInput) -> str:
    """Fetch detailed metadata and compatible release versions for a Modrinth project ID or slug."""
    svc = get_service()
    policy = CompatibilityPolicy(
        content_type=params.content_type,
        game_version=params.game_version,
        loader=params.loader,
    )
    details = svc.catalog.fetch_project_view(params.project_id, policy)
    if not details:
        return f"Error: Project '{params.project_id}' could not be found on Modrinth."

    versions_summary = []
    for v in (details.get("versions_list") or [])[:15]:
        files = v.get("files") or []
        primary_file = files[0].get("filename", "") if files else ""
        versions_summary.append({
            "version_id": v.get("id", ""),
            "version_number": v.get("version_number", ""),
            "name": v.get("name", ""),
            "game_versions": v.get("game_versions", []),
            "loaders": v.get("loaders", []),
            "filename": primary_file,
        })

    payload = {
        "project_id": details.get("id") or params.project_id,
        "slug": details.get("slug", ""),
        "title": details.get("title", ""),
        "description": details.get("description", ""),
        "downloads": details.get("downloads", 0),
        "followers": details.get("followers", 0),
        "loaders": details.get("loaders", []),
        "game_versions": (details.get("game_versions") or [])[-10:],
        "compatible_versions": versions_summary,
    }

    def _md(d: dict[str, Any]) -> str:
        lines = [
            f"# {d['title']} (`{d['project_id']}`)",
            f"{d['description']}",
            f"- **Downloads**: `{d['downloads']:,}` | **Followers**: `{d['followers']:,}`",
            f"- **Supported Loaders**: `{', '.join(d['loaders'])}`",
            f"- **Recent Compatible Versions ({len(d['compatible_versions'])})**:",
        ]
        for v in d["compatible_versions"][:10]:
            lines.append(
                f"  - `{v['version_number']}` (`{v['version_id']}`) — "
                f"MC: `{', '.join(v['game_versions'][:4])}` | Loaders: `{', '.join(v['loaders'])}` | File: `{v['filename']}`"
            )
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="vega_install_modrinth_content",
    annotations={
        "title": "Install Modrinth Mod, Shader, Plugin, or Modpack",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def vega_install_modrinth_content(params: InstallModrinthContentInput) -> str:
    """Resolve and install a Modrinth project into a client profile or local server.

    Uses CompatibilityPolicy for strict version/loader matching and TransactionalRollback for modpacks.
    """
    svc = get_service()

    if params.target_type == "profile":
        pid, pdata, profiles, ms_login, settings = svc.resolve_profile(params.target_name)
        if not pid or not pdata:
            return f"Error: Client profile '{params.target_name}' not found."
        target_root = pdata.get("path") or os.path.join(svc.store.profiles_dir, pdata.get("name", pid))
        spec = RuntimeProvisioner.detect_client_runtime(pdata)
        eff_ver = params.game_version or spec.mc_version
        eff_loader = params.loader or (spec.loader if spec.loader != "vanilla" else None)
    else:
        s_dir, err = svc.resolve_server_dir(params.target_name, must_exist=True)
        if err or not s_dir:
            return err or "Error: Invalid server."
        target_root = s_dir
        spec = RuntimeProvisioner.detect_server_runtime(s_dir)
        eff_ver = params.game_version or spec.mc_version
        eff_loader = params.loader or spec.loader

    policy = CompatibilityPolicy(
        content_type=params.content_type,
        game_version=eff_ver,
        loader=eff_loader,
    )

    if params.content_type == "modpack":
        if params.target_type != "profile":
            return "Error: Modpacks (.mrpack) can only be installed into a client profile."
        art = svc.catalog.resolve_artifact(params.project_id, policy)
        if not art or not art.url:
            return f"Error: No compatible modpack version found for '{params.project_id}'."
        res = svc.catalog.install_modpack(
            target_root,
            art.url,
            is_local=False,
            is_update=bool(pdata.get("project_id")),
        )
        if res.ok and pid and pdata:
            pdata["project_id"] = params.project_id
            pdata["version_id"] = art.version_id
            if res.version_id:
                pdata["version"] = res.version_id
            profiles[pid] = pdata
            svc.store.save(profiles, ms_login, settings)
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
        target_root,
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
            "target_dir": os.path.join(target_root, policy.target_subdir),
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="vega_check_mod_updates",
    annotations={
        "title": "Check Installed Mods or Modpacks for Modrinth Updates",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def vega_check_mod_updates(params: CheckModUpdatesInput) -> str:
    """Check installed .jar mods in a profile/server (via SHA-1 batch lookup) or tracked modpacks for updates."""
    svc = get_service()

    if params.target_type == "modpacks":
        profiles, _, _ = svc.store.load()
        updates = svc.catalog.check_updates(profiles)
        items = [
            {
                "profile_id": pid,
                "profile_name": profiles.get(pid, {}).get("name", pid),
                "project_id": art.project_id,
                "new_version_id": art.version_id,
                "filename": art.filename,
                "download_url": art.url,
            }
            for pid, art in updates
        ]
        payload = {"target_type": "modpacks", "updates_count": len(items), "updates": items}

        def _md_mp(d: dict[str, Any]) -> str:
            if not d["updates"]:
                return "All tracked modpack profiles are up to date."
            lines = [f"# Available Modpack Updates ({d['updates_count']})"]
            for u in d["updates"]:
                lines.append(f"- **{u['profile_name']}** (`{u['profile_id']}`) -> `{u['filename']}` (`{u['new_version_id']}`)")
            return "\n".join(lines)

        return _format_output(payload, params.response_format, _md_mp)

    if not params.target_name:
        return "Error: target_name is required when target_type is 'profile' or 'server'."

    if params.target_type == "profile":
        pid, pdata, _, _, _ = svc.resolve_profile(params.target_name)
        if not pid or not pdata:
            return f"Error: Profile '{params.target_name}' not found."
        base_dir = pdata.get("path") or os.path.join(svc.store.profiles_dir, pdata.get("name", pid))
        spec = RuntimeProvisioner.detect_client_runtime(pdata)
        sub_dir = os.path.join(base_dir, "mods")
    else:
        s_dir, err = svc.resolve_server_dir(params.target_name, must_exist=True)
        if err or not s_dir:
            return err or "Error: Server not found."
        spec = RuntimeProvisioner.detect_server_runtime(s_dir)
        sub_dir = os.path.join(s_dir, "plugins" if spec.loader in ("purpur", "paper", "spigot") else "mods")

    if not os.path.isdir(sub_dir):
        return json.dumps({"updates_count": 0, "checked_files": 0, "updates": []}, indent=2)

    hash_to_file: dict[str, str] = {}
    for fname in sorted(os.listdir(sub_dir)):
        if not fname.lower().endswith(".jar"):
            continue
        fpath = os.path.join(sub_dir, fname)
        if not os.path.isfile(fpath):
            continue
        sha1 = hashlib.sha1()
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha1.update(chunk)
        hash_to_file[sha1.hexdigest()] = fname

    ldr = [spec.loader] if spec.loader and spec.loader != "vanilla" else ["fabric"]
    if spec.loader == "quilt":
        ldr = ["quilt", "fabric"]
    elif spec.loader in ("purpur", "paper", "spigot"):
        ldr = ["paper", "purpur", "spigot", "bukkit"]

    latest_map = svc.catalog.transport.check_version_updates(
        list(hash_to_file.keys()),
        loaders=ldr,
        game_versions=[spec.mc_version],
    )
    updates_list = []
    for h, latest_ver in (latest_map or {}).items():
        current_fname = hash_to_file.get(h, "")
        files = latest_ver.get("files") or []
        if not files:
            continue
        primary = next((f for f in files if f.get("primary")), files[0])
        latest_fname = primary.get("filename", "")
        latest_hashes = primary.get("hashes", {})
        if latest_hashes.get("sha1") and latest_hashes.get("sha1") != h:
            updates_list.append({
                "current_filename": current_fname,
                "latest_filename": latest_fname,
                "project_id": latest_ver.get("project_id", ""),
                "version_id": latest_ver.get("id", ""),
                "version_number": latest_ver.get("version_number", ""),
                "download_url": primary.get("url", ""),
            })

    payload = {
        "target_type": params.target_type,
        "target_name": params.target_name,
        "mc_version": spec.mc_version,
        "loader": spec.loader,
        "checked_files": len(hash_to_file),
        "updates_count": len(updates_list),
        "updates": updates_list,
    }

    def _md(d: dict[str, Any]) -> str:
        lines = [
            f"# Update Check for {d['target_name']} ({d['checked_files']} files checked)",
            f"- **Runtime**: MC `{d['mc_version']}` (`{d['loader']}`)",
            f"- **Updates Available**: `{d['updates_count']}`",
        ]
        for u in d["updates"]:
            lines.append(f"  - `{u['current_filename']}` -> `{u['latest_filename']}` (`{u['version_number']}`)")
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="vega_manage_installed_content",
    annotations={
        "title": "Enable, Disable, or Delete an Installed Mod/Shader/Plugin",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_manage_installed_content(params: ManageInstalledContentInput) -> str:
    """Enable, disable (.disabled suffix), or delete an installed mod, shaderpack, or plugin file."""
    if params.action == "delete" and not params.confirm:
        return "Error: Deletion aborted. Pass confirm=True when action='delete'."

    svc = get_service()
    if params.target_type == "profile":
        pid, pdata, _, _, _ = svc.resolve_profile(params.target_name)
        if not pid or not pdata:
            return f"Error: Profile '{params.target_name}' not found."
        base_dir = pdata.get("path") or os.path.join(svc.store.profiles_dir, pdata.get("name", pid))
    else:
        s_dir, err = svc.resolve_server_dir(params.target_name, must_exist=True)
        if err or not s_dir:
            return err or "Error: Server not found."
        base_dir = s_dir

    folder_dir = os.path.realpath(os.path.join(base_dir, params.folder))
    target_path = os.path.realpath(os.path.join(folder_dir, params.filename))
    if not target_path.startswith(folder_dir + os.sep) or not os.path.isfile(target_path):
        return f"Error: File '{params.filename}' not found inside '{params.folder}'."

    if params.action == "delete":
        os.remove(target_path)
        return json.dumps({"ok": True, "action": "delete", "filename": params.filename}, indent=2)

    if params.action == "disable":
        if target_path.lower().endswith(".disabled"):
            return json.dumps({"ok": True, "action": "disable", "filename": params.filename, "unchanged": True}, indent=2)
        new_path = target_path + ".disabled"
        os.replace(target_path, new_path)
        return json.dumps({"ok": True, "action": "disable", "new_filename": os.path.basename(new_path)}, indent=2)

    # action == "enable"
    if not target_path.lower().endswith(".disabled"):
        return json.dumps({"ok": True, "action": "enable", "filename": params.filename, "unchanged": True}, indent=2)
    new_path = target_path[: -len(".disabled")]
    os.replace(target_path, new_path)
    return json.dumps({"ok": True, "action": "enable", "new_filename": os.path.basename(new_path)}, indent=2)


# ============================================================================
# Domain 3: Runtime Detection & Provisioning Tools
# ============================================================================

@mcp.tool(
    name="vega_detect_runtime",
    annotations={
        "title": "Detect Client Profile or Local Server Runtime Spec",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_detect_runtime(params: DetectRuntimeInput) -> str:
    """Detect the effective Minecraft base version and loader for a client profile or local server."""
    svc = get_service()
    if params.target_type == "profile":
        pid, pdata, _, _, _ = svc.resolve_profile(params.target_name)
        if not pid or not pdata:
            return f"Error: Profile '{params.target_name}' not found."
        spec = RuntimeProvisioner.detect_client_runtime(pdata)
    else:
        s_dir, err = svc.resolve_server_dir(params.target_name, must_exist=True)
        if err or not s_dir:
            return err or "Error: Server not found."
        spec = RuntimeProvisioner.detect_server_runtime(s_dir)

    payload = {
        "target_type": params.target_type,
        "target_name": params.target_name,
        "mc_version": spec.mc_version,
        "loader": spec.loader,
        "is_server": spec.is_server,
    }
    return _format_output(
        payload,
        params.response_format,
        lambda d: f"**{d['target_name']}** ({d['target_type']}): MC `{d['mc_version']}`, Loader `{d['loader']}`",
    )


@mcp.tool(
    name="vega_install_client_runtime",
    annotations={
        "title": "Install Client Engine (Vanilla, Fabric, Quilt, Forge, NeoForge)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def vega_install_client_runtime(params: InstallClientRuntimeInput) -> str:
    """Install a Minecraft client runtime into .minecraft and optionally bind it to a Vega profile."""
    svc = get_service()
    spec = RuntimeSpec(
        mc_version=params.mc_version,
        loader=params.loader,
        loader_version=params.loader_version,
        is_server=False,
    )
    try:
        installed_version_id = svc.provisioner.install_client_runtime(spec, mc_dir=svc.mc_dir)
    except Exception as e:
        return f"Error: Client runtime installation failed: {str(e)}"

    updated_profile = None
    if params.profile:
        pid, pdata, profiles, ms_login, settings = svc.resolve_profile(params.profile)
        if pid and pdata:
            pdata["version"] = installed_version_id
            pdata["game_version"] = params.mc_version
            pdata["loader"] = params.loader
            profiles[pid] = pdata
            svc.store.save(profiles, ms_login, settings)
            updated_profile = pdata.get("name", pid)

    return json.dumps(
        {
            "ok": True,
            "installed_version_id": installed_version_id,
            "mc_version": params.mc_version,
            "loader": params.loader,
            "updated_profile": updated_profile,
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="vega_provision_server",
    annotations={
        "title": "Provision a Local Minecraft Server",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def vega_provision_server(params: ProvisionServerInput) -> str:
    """Download and provision a local Minecraft server (Purpur, Fabric, Forge, or NeoForge) inside servers/<server_name>."""
    svc = get_service()
    s_dir, err = svc.resolve_server_dir(params.server_name, must_exist=False)
    if err or not s_dir:
        return err or "Error: Invalid server_name."

    os.makedirs(s_dir, exist_ok=True)
    target_jar = os.path.join(s_dir, "server.jar")
    logs: list[str] = []
    try:
        artifact_path = svc.provisioner.provision_server_runtime(
            software=params.software,
            version=params.mc_version,
            target_path=target_jar,
            on_log=logs.append,
        )
    except Exception as e:
        return f"Error: Server provisioning failed: {str(e)}"

    if params.accept_eula:
        with open(os.path.join(s_dir, "eula.txt"), "w", encoding="utf-8") as f:
            f.write("eula=true\n")

    prop_path = os.path.join(s_dir, "server.properties")
    if not os.path.exists(prop_path):
        _write_server_properties(
            prop_path,
            {
                "server-port": "25565",
                "motd": f"Vega {params.server_name}",
                "max-players": "20",
                "online-mode": "true",
            },
        )

    return json.dumps(
        {
            "ok": True,
            "server_name": params.server_name,
            "software": params.software,
            "mc_version": params.mc_version,
            "artifact_path": str(artifact_path),
            "eula_accepted": params.accept_eula,
            "logs": logs[-10:],
        },
        indent=2,
        ensure_ascii=False,
    )


# ============================================================================
# Domain 4: Local Server Management (Properties, Logs, Backups) Tools
# ============================================================================

@mcp.tool(
    name="vega_list_servers",
    annotations={
        "title": "List Local Vega Minecraft Servers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_list_servers(params: ListServersInput) -> str:
    """List all local Minecraft servers in the servers/ directory with runtime and configuration summaries."""
    svc = get_service()
    names = (
        [
            d
            for d in sorted(os.listdir(svc.servers_dir))
            if os.path.isdir(os.path.join(svc.servers_dir, d)) and not d.startswith(".")
        ]
        if os.path.isdir(svc.servers_dir)
        else []
    )
    all_items = [svc.summarize_server(name) for name in names]
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
            return "No local servers found in `servers/`."
        lines = [f"# Local Minecraft Servers ({d['count']} of {d['total']})"]
        for s in d["items"]:
            lines.append(
                f"- **{s['server_name']}** — MC `{s['mc_version']}` (`{s['loader']}`) "
                f"| Port: `{s['port']}` | Mods: `{s['mods_count']}` | Plugins: `{s['plugins_count']}` "
                f"| Backups: `{s['backups_count']}`"
            )
        return "\n".join(lines)

    return _format_output(payload, params.response_format, _md)


@mcp.tool(
    name="vega_get_server_details",
    annotations={
        "title": "Get Local Server Properties, Plugins/Mods, Backups, and Logs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_get_server_details(params: GetServerDetailsInput) -> str:
    """Inspect a local server's server.properties, installed mods/plugins, backups, and tail of logs/latest.log."""
    svc = get_service()
    s_dir, err = svc.resolve_server_dir(params.server_name, must_exist=True)
    if err or not s_dir:
        return err or "Error: Server not found."

    summary = svc.summarize_server(params.server_name)
    summary["properties"] = _read_server_properties(os.path.join(s_dir, "server.properties"))
    summary["mods"] = _list_content_files(os.path.join(s_dir, "mods"), (".jar", ".jar.disabled"))
    summary["plugins"] = _list_content_files(os.path.join(s_dir, "plugins"), (".jar", ".jar.disabled"))

    backups_dir = os.path.join(s_dir, "backups")
    summary["backups"] = (
        sorted(f for f in os.listdir(backups_dir) if f.lower().endswith(".zip"))
        if os.path.isdir(backups_dir)
        else []
    )

    log_tail: list[str] = []
    log_path = os.path.join(s_dir, "logs", "latest.log")
    if params.log_lines > 0 and os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                all_lines = [ln.rstrip("\r\n") for ln in lf.readlines()]
                log_tail = all_lines[-params.log_lines :]
        except Exception:
            pass
    summary["latest_log_tail"] = log_tail

    def _md(d: dict[str, Any]) -> str:
        lines = [
            f"# Server: {d['server_name']}",
            f"- **Runtime**: MC `{d['mc_version']}` (`{d['loader']}`)",
            f"- **Path**: `{d['path']}`",
            f"- **Port**: `{d['port']}` | **Max Players**: `{d['max_players']}` | **Online Mode**: `{d['online_mode']}`",
            f"- **Mods ({len(d['mods'])})**: {', '.join(m['filename'] for m in d['mods']) or 'None'}",
            f"- **Plugins ({len(d['plugins'])})**: {', '.join(p['filename'] for p in d['plugins']) or 'None'}",
            f"- **Backups ({len(d['backups'])})**: {', '.join(d['backups']) or 'None'}",
        ]
        if d["latest_log_tail"]:
            lines.append("\n## Latest Log Tail")
            lines.append("```text")
            lines.extend(d["latest_log_tail"])
            lines.append("```")
        return "\n".join(lines)

    return _format_output(summary, params.response_format, _md)


@mcp.tool(
    name="vega_update_server_properties",
    annotations={
        "title": "Update Local Server server.properties",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_update_server_properties(params: UpdateServerPropertiesInput) -> str:
    """Update key-value settings in a local server's server.properties file atomically."""
    svc = get_service()
    s_dir, err = svc.resolve_server_dir(params.server_name, must_exist=True)
    if err or not s_dir:
        return err or "Error: Server not found."

    for k, v in params.properties.items():
        if "\n" in str(k) or "\r" in str(k) or "\n" in str(v) or "\r" in str(v):
            return "Error: Property keys and values must not contain newline characters."

    prop_path = os.path.join(s_dir, "server.properties")
    updated_props = _write_server_properties(prop_path, params.properties)
    return json.dumps(
        {
            "ok": True,
            "server_name": params.server_name,
            "updated_keys": list(params.properties.keys()),
            "properties": updated_props,
        },
        indent=2,
        ensure_ascii=False,
    )


def _create_server_zip(server_dir: str, zip_path: str) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    files_to_zip = BackupManager.collect_server_backup_files(server_dir)
    files_archived = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path, arcname in files_to_zip:
            try:
                zipf.write(file_path, arcname)
                files_archived += 1
            except OSError:
                pass
    return files_archived


@mcp.tool(
    name="vega_create_server_backup",
    annotations={
        "title": "Create a Local Server Backup Archive",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def vega_create_server_backup(params: CreateServerBackupInput) -> str:
    """Create a timestamped .zip backup of a local server inside servers/<server_name>/backups/."""
    svc = get_service()
    s_dir, err = svc.resolve_server_dir(params.server_name, must_exist=True)
    if err or not s_dir:
        return err or "Error: Server not found."

    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    safe_label = ""
    if params.label:
        cleaned = "".join(ch for ch in params.label if ch.isalnum() or ch in ("-", "_"))
        if cleaned:
            safe_label = f"_{cleaned}"
    zip_name = f"backup_{ts}{safe_label}.zip"
    zip_path = os.path.join(s_dir, "backups", zip_name)
    count = _create_server_zip(s_dir, zip_path)
    return json.dumps(
        {
            "ok": True,
            "server_name": params.server_name,
            "backup_filename": zip_name,
            "backup_path": zip_path,
            "files_archived": count,
        },
        indent=2,
        ensure_ascii=False,
    )


def _is_server_locked(server_dir: str) -> bool:
    for rel in (os.path.join("world", "session.lock"), "server.jar"):
        fpath = os.path.join(server_dir, rel)
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r+b"):
                    pass
            except PermissionError:
                return True
            except OSError:
                pass
    return False


@mcp.tool(
    name="vega_restore_server_backup",
    annotations={
        "title": "Restore a Local Server Backup Archive",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_restore_server_backup(params: RestoreServerBackupInput) -> str:
    """Restore a backup .zip from servers/<server_name>/backups/ with zip-slip protection and pre-restore snapshot."""
    if not params.confirm:
        return "Error: Restore aborted. Pass confirm=True to overwrite server files from backup."

    svc = get_service()
    s_dir, err = svc.resolve_server_dir(params.server_name, must_exist=True)
    if err or not s_dir:
        return err or "Error: Server not found."
    if _is_server_locked(s_dir):
        return f"Error: Server '{params.server_name}' appears to be running (files locked). Stop the server before restoring."

    backups_dir = os.path.realpath(os.path.join(s_dir, "backups"))
    zip_path = os.path.realpath(os.path.join(backups_dir, params.backup_filename))
    if not zip_path.startswith(backups_dir + os.sep) or not os.path.isfile(zip_path):
        return f"Error: Backup file '{params.backup_filename}' not found in server backups/."

    safety_backup_name = None
    if params.create_safety_backup:
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safety_backup_name = f"pre_restore_{ts}.zip"
        _create_server_zip(s_dir, os.path.join(backups_dir, safety_backup_name))

    with zipfile.ZipFile(zip_path, "r") as zipf:
        base_path = os.path.realpath(s_dir)
        base_prefix = base_path + os.sep
        extracted_count = sum(
            1
            for member in zipf.infolist()
            if os.path.realpath(os.path.join(s_dir, member.filename)).startswith(base_prefix)
            or os.path.realpath(os.path.join(s_dir, member.filename)) == base_path
        )
    BackupManager.restore_archive_safely(zip_path, s_dir)

    return json.dumps(
        {
            "ok": True,
            "server_name": params.server_name,
            "restored_from": params.backup_filename,
            "safety_backup_created": safety_backup_name,
            "extracted_entries": extracted_count,
        },
        indent=2,
        ensure_ascii=False,
    )


@mcp.tool(
    name="vega_delete_server",
    annotations={
        "title": "Delete a Local Server Directory",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def vega_delete_server(params: DeleteServerInput) -> str:
    """Permanently delete a local server directory inside servers/. Requires confirm=True."""
    if not params.confirm:
        return "Error: Deletion aborted. Pass confirm=True to permanently delete this server."

    svc = get_service()
    s_dir, err = svc.resolve_server_dir(params.server_name, must_exist=True)
    if err or not s_dir:
        return err or "Error: Server not found."
    if _is_server_locked(s_dir):
        return f"Error: Server '{params.server_name}' appears to be running (files locked). Stop the server before deleting."

    shutil.rmtree(s_dir)
    return json.dumps(
        {"ok": True, "deleted_server": params.server_name, "deleted_path": s_dir},
        indent=2,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")

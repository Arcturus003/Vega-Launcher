from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class LaunchSession:
    """Represents an active Minecraft client game process supervised by the launcher."""
    process: subprocess.Popen
    pid: str
    version: str
    profile_id: str
    game_directory: str


class DefaultLaunchBackendAdapter:
    """Production adapter delegating to minecraft_launcher_lib."""
    def get_minecraft_command(self, version: str, mc_dir: str, options: dict) -> list[str]:
        import minecraft_launcher_lib
        return minecraft_launcher_lib.command.get_minecraft_command(version, mc_dir, options)


class GameLaunchPipeline:
    """
    Deep module encapsulating JVM arguments generation, options dictionary construction,
    engine/version existence verification, and Minecraft subprocess execution.
    Hides classpath details and minecraft_launcher_lib invocation behind a single entry point.
    """

    def __init__(self, mc_dir: Optional[str] = None, backend=None):
        self.mc_dir = mc_dir or os.path.join(os.getenv("APPDATA", ""), ".minecraft")
        self.backend = backend or DefaultLaunchBackendAdapter()

    def build_jvm_arguments(self, ram_mb: int = 4096, extra_args: str = "") -> list[str]:
        """Build JVM flags including min/max heap allocations and custom arguments."""
        effective_ram = max(512, int(ram_mb or 4096))
        args = [f"-Xmx{effective_ram}m", "-Xms512m"]
        if extra_args:
            args.extend(extra_args.strip().split())
        return args

    def build_launch_options(
        self,
        auth_session: dict,
        game_directory: str,
        ram_mb: int = 4096,
        extra_jvm: str = "",
        java_path: Optional[str] = None,
        launcher_name: str = "Vega Launcher",
        launcher_version: str = "2.0.0",
    ) -> dict:
        """Construct the options dict required by minecraft_launcher_lib."""
        options: dict[str, Any] = {
            "username": auth_session.get("name") or auth_session.get("username", "Player"),
            "uuid": auth_session.get("id") or auth_session.get("uuid", ""),
            "token": auth_session.get("access_token") or auth_session.get("token", ""),
            "jvmArguments": self.build_jvm_arguments(ram_mb, extra_jvm),
            "launcherName": launcher_name,
            "launcherVersion": launcher_version,
            "gameDirectory": game_directory,
        }
        if java_path and os.path.exists(java_path):
            options["executablePath"] = java_path
        return options

    def is_engine_installed(self, version: str) -> bool:
        """Check whether the targeted version engine directory exists in .minecraft/versions."""
        if not version or not self.mc_dir:
            return False
        v_dir = os.path.join(self.mc_dir, "versions", version)
        return os.path.exists(v_dir)

    def is_loader_version(self, version: str) -> bool:
        """Return True if the version string represents a mod loader (Fabric, Forge, NeoForge, Quilt)."""
        vl = (version or "").lower()
        return any(k in vl for k in ("fabric-loader", "forge", "neoforge", "quilt"))

    def detect_loader_type(self, version: str) -> str:
        """Extract the loader type from a version string."""
        vl = (version or "").lower()
        if "neoforge" in vl:
            return "neoforge"
        if "forge" in vl:
            return "forge"
        if "quilt" in vl:
            return "quilt"
        if "fabric" in vl:
            return "fabric"
        return "vanilla"

    def evaluate_readiness(
        self,
        profile_id_or_data: str | dict,
        profile_data: Optional[dict] = None,
        auth_session: Optional[dict] = None,
        settings: Optional[dict] = None,
        custom_java_path: str = "",
        java_provisioner: Any = None,
    ) -> dict[str, Any]:
        """
        Pre-flight launch readiness evaluation.
        Resolves required Java major version and compatible Java executable via JavaProvisioner,
        checks whether the target version/loader is installed in `.minecraft/versions/`,
        and builds launch options when ready.
        """
        if isinstance(profile_id_or_data, dict) and profile_data is None:
            pdata = profile_id_or_data
            profile_id = str(pdata.get("id") or pdata.get("name") or "")
        else:
            profile_id = str(profile_id_or_data or "")
            pdata = dict(profile_data or {})

        settings = dict(settings or {})
        auth_session = dict(auth_session or {})
        version = str(pdata.get("version") or "")
        game_dir = str(pdata.get("path") or "")

        from java_provisioner import DEFAULT_JAVA_PROVISIONER
        from runtime_provisioner import RuntimeProvisioner

        prov = java_provisioner or DEFAULT_JAVA_PROVISIONER
        user_java = (custom_java_path or settings.get("java_path") or "").strip() or None
        req_major, resolved_java = prov.resolve_java_runtime(
            mc_version=version,
            mc_dir=self.mc_dir,
            custom_java=user_java,
        )

        engine_installed = self.is_engine_installed(version) if version else False
        is_loader = self.is_loader_version(version)
        explicit_loader = (pdata.get("loader") or "").strip().lower()
        loader_type = explicit_loader if explicit_loader and explicit_loader != "vanilla" else self.detect_loader_type(version)
        base_version = RuntimeProvisioner.extract_base_version(version, default=version) or version

        def_ram = int(settings.get("default_ram", 4096) or 4096)
        ram_mb = int(pdata.get("ram", def_ram) or def_ram)
        extra_jvm = settings.get("jvm_args", "")

        options = self.build_launch_options(
            auth_session=auth_session,
            game_directory=game_dir,
            ram_mb=ram_mb,
            extra_jvm=extra_jvm,
            java_path=resolved_java,
        )

        if not resolved_java:
            status = "missing_java"
        elif not engine_installed:
            status = "missing_loader" if (is_loader or loader_type != "vanilla") else "missing_vanilla"
        else:
            status = "ready"

        return {
            "ready": status == "ready",
            "status": status,
            "profile_id": profile_id,
            "version": version,
            "base_version": base_version,
            "required_java_major": req_major,
            "resolved_java": resolved_java,
            "custom_java_incompatible": bool(user_java and os.path.isfile(user_java) and resolved_java != user_java),
            "engine_installed": engine_installed,
            "is_loader": is_loader,
            "loader_type": loader_type,
            "options": options,
        }

    def launch(
        self,
        profile_id: str,
        profile_data: dict,
        auth_session: dict,
        settings: Optional[dict] = None,
        creationflags: int = 0,
        options: Optional[dict] = None,
    ) -> LaunchSession:
        """
        Single entry point to assemble launch parameters, generate command line arguments,
        and spawn the Minecraft client process.
        """
        settings = settings or {}
        version = profile_data.get("version")
        if not version:
            raise ValueError(f"Profile '{profile_id}' does not specify a Minecraft version.")

        game_dir = profile_data.get("path")
        if not game_dir:
            raise ValueError(f"Profile '{profile_id}' does not have a valid directory path.")

        os.makedirs(game_dir, exist_ok=True)
        os.makedirs(self.mc_dir, exist_ok=True)

        if options is None:
            def_ram = int(settings.get("default_ram", 4096) or 4096)
            ram_mb = int(profile_data.get("ram", def_ram) or def_ram)
            extra_jvm = settings.get("jvm_args", "")
            java_path = (settings.get("java_path", "") or "").strip() or None

            if not java_path or not os.path.exists(java_path):
                try:
                    from runtime_provisioner import DEFAULT_PROVISIONER
                    java_path = DEFAULT_PROVISIONER.ensure_java_runtime(version, self.mc_dir)
                except Exception:
                    java_path = None

            options = self.build_launch_options(
                auth_session=auth_session,
                game_directory=game_dir,
                ram_mb=ram_mb,
                extra_jvm=extra_jvm,
                java_path=java_path,
            )

        cmd = self.backend.get_minecraft_command(version, self.mc_dir, options)
        if not cmd:
            raise RuntimeError(f"Failed to generate Minecraft launch command for version {version}.")

        # On Windows, pass creationflags to prevent command prompt window from popping up
        proc = subprocess.Popen(
            cmd,
            cwd=game_dir,
            creationflags=creationflags,
        )

        return LaunchSession(
            process=proc,
            pid=str(proc.pid),
            version=version,
            profile_id=profile_id,
            game_directory=game_dir,
        )


DEFAULT_LAUNCH_PIPELINE = GameLaunchPipeline()


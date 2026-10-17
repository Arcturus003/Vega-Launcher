# Domain Glossary — Vega Launcher (`quick-pythagoras`)

This glossary defines the core domain concepts and seams of Vega Launcher so code, tests, and architectural discussions share a single language.

## Core Domain Terms

- **ContentCatalog**: The deep module responsible for discovering, resolving, downloading, and installing external game content (mods, shaders, plugins, and modpacks) from remote registries (Modrinth, CurseForge) or local archives into a target profile or server directory.
- **Artifact**: A single installable content file (`.jar` mod/plugin or `.zip` shaderpack) resolved for a specific Minecraft version and loader, placed into a target subdirectory (`mods/`, `shaderpacks/`, or `plugins/`).
- **ModpackArchive**: A composite package (`.mrpack` Modrinth archive or CurseForge `.zip` manifest archive) containing a dependency index (`modrinth.index.json` or `manifest.json`), remote file descriptors, and `overrides/` / `client-overrides/` directory trees.
- **CompatibilityPolicy**: The strict type-based resolution rules governing which remote version of a project may be selected:
  - **Mod / Plugin**: Requires both matching `game_version` and compatible `loader` (with Quilt accepting `["quilt", "fabric"]`). Never falls back to an unfiltered version.
  - **Shader**: Requires matching `game_version` only (`loader=None`).
  - **Modpack Update**: Requires matching `loader` (and prefers matching `game_version`, falling back to `loader`-only when a modpack upgrades its base Minecraft version).
- **TransactionalRollback**: The atomic update lifecycle for a profile's `mods/` and `config/` directories during a modpack upgrade: existing directories are moved to `mods.old_bak` and `config.old_bak` before installation, restored automatically on failure or cancellation, and purged only upon verified completion.
- **RuntimeSpec**: A typed specification of a Minecraft environment (`mc_version`, `loader`, optional `loader_version`, and whether it is a client profile or server instance).
- **RuntimeProvisioner**: The deep module responsible for detecting, resolving, downloading, and installing Minecraft runtime engines for both client profiles (Vanilla, Fabric, Quilt, Forge, NeoForge via `minecraft_launcher_lib`) and server instances (Purpur, Fabric, Forge, NeoForge server jars and headless installers).
- **ProfileAndConfigStore**: The deep module responsible for `launcher_config.json` persistence, DPAPI token protection and migration, `profiles/` directory reconciliation (orphan discovery, path normalization, unique name generation, and path-contained deletion), and atomic profile synchronization with standard Minecraft launchers (`launcher_profiles.json` and `tlauncher_profiles.json`).
- **ServerInstance**: The deep module representing a local Minecraft server directory (`servers/<name>/`), encapsulating `eula.txt` and `server.properties` bootstrapping, round-trip `ServerProperties` parsing/saving (preserving comments and custom keys), client-to-server mod synchronization (`CLIENT_MODS_BLACKLIST` filtering while preserving tunnel companions), and `usercache.json` / `ops.json` player state inspection.
- **BackupManager**: The deep module responsible for creating and restoring ZIP archives for both server instances (`world*`, `plugins`, `mods`, `config`, `.json`, `.properties`) and single-player world saves, enforcing ZipSlip path containment on extraction, and coordinating optional cloud uploads via a `CloudBackupAdapter`.
- **CloudBackupAdapter**: The port interface for uploading local backup archives to remote storage (implemented by `GoogleDriveBackupAdapter` with DPAPI-protected `token.json` persistence and chunked resumable upload).
- **GameLaunchPipeline**: The deep module (`launch_pipeline.py`) responsible for assembling JVM arguments, building client launch option dictionaries, validating local runtime engine installations, and executing the Minecraft client subprocess cleanly without leaking classpath or process flags into GUI widgets.
- **ServerConsoleParser**: The deep module (`server_console_parser.py`) encapsulating pre-compiled regex classification, HTML ANSI/log formatting, and structured event emission (`ConsoleEvent`: online, stopping, world_saved, player_joined/left, playit_ip, claim_url) from raw server standard output streams.
- **AuthenticationVault**: The deep module (`auth_vault.py`) responsible for credential protection (native Windows DPAPI encryption/decryption with portable base64 fallback), fast non-blocking DNS network connectivity probing, and offline session token derivation.
- **ServerProcessCoordinator**: The deep module (`server_process_coordinator.py`) orchestrating dedicated Minecraft server process lifecycles, state machine transitions (`STOPPED`, `STARTING`, `RUNNING`, `STOPPING`, `CRASHED`), automated shutdown watchdog coordination with chunk flush acceleration, clean process tree termination, and thread-safe live backup quiescence (`quiesce_for_backup`).



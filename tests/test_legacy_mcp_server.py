from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

if not (importlib.util.find_spec("pydantic") and importlib.util.find_spec("mcp")):
    raise unittest.SkipTest("mcp and pydantic are required for Legacy MCP server tests")

import legacy_mcp_server as lms
from legacy_mcp_server import (
    BackupLegacyWorldInput,
    CheckLegacyModUpdatesInput,
    GetLegacyLogsInput,
    GetLegacyStatusInput,
    InstallLegacyModrinthInput,
    InstallLegacyRuntimeInput,
    LegacyLauncherMCPService,
    ListLegacyContentInput,
    ListLegacyVersionsInput,
    ListLegacyWorldsInput,
    ManageLegacyContentInput,
    ResponseFormat,
    RestoreLegacyWorldBackupInput,
    SelectLegacyVersionInput,
    SyncLegacyWithVegaInput,
    UpdateLegacySettingsInput,
    _unescape_java_prop,
    set_legacy_service,
)
from mod_manager import ContentCatalog
from profile_store import ProfileAndConfigStore
from runtime_provisioner import RuntimeProvisioner
from tests.test_vega_mcp_server import FakeClientInstallerBackend, FakeModrinthTransport


class TestLegacyMCPServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.legacy_root = self.base / "legacy" / "Minecraft"
        self.game_dir = self.legacy_root / "game"
        self.vega_dir = self.base / "vega"
        self.legacy_root.mkdir(parents=True)
        self.game_dir.mkdir(parents=True)

        # Seed tl.properties with sensitive & safe keys
        escaped_game = str(self.game_dir).replace("\\", "\\\\").replace(":", r"\:")
        tl_props = (
            f"client=SECRET_CLIENT_UUID_999\n"
            f"login.account=SECRET_ACCOUNT_TOKEN\n"
            f"login.version=Fabric 1.20.1\n"
            f"minecraft.xmx=auto\n"
            f"minecraft.gamedir={escaped_game}\n"
            f"minecraft.gamedir.separate=none\n"
        )
        (self.legacy_root / "tl.properties").write_text(tl_props, encoding="utf-8")

        # Seed tlauncher_profiles.json with account + secret token
        (self.game_dir / "tlauncher_profiles.json").write_text(
            json.dumps(
                {
                    "userSet": {
                        "selected": {"username": "Arcturus", "type": "plain"},
                        "list": [
                            {
                                "username": "Arcturus",
                                "uuid": "72bb08dcbb913dffbd7aaf212a105135",
                                "accessToken": "SUPER_SECRET_TOKEN",
                                "type": "plain",
                            }
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )

        # Seed installed versions
        v_fab = self.game_dir / "versions" / "Fabric 1.20.1"
        v_fab.mkdir(parents=True)
        (v_fab / "Fabric 1.20.1.json").write_text(
            json.dumps({"id": "Fabric 1.20.1", "inheritsFrom": "1.20.1"}),
            encoding="utf-8",
        )
        v_neo = self.game_dir / "versions" / "NeoForge 1.21.1"
        v_neo.mkdir(parents=True)
        (v_neo / "NeoForge 1.21.1.json").write_text(
            json.dumps({"id": "NeoForge 1.21.1", "inheritsFrom": "1.21.1"}),
            encoding="utf-8",
        )

        self.transport = FakeModrinthTransport()
        self.catalog = ContentCatalog(transport=self.transport, mc_dir=str(self.game_dir))
        self.provisioner = RuntimeProvisioner(
            installer_backend=FakeClientInstallerBackend(),
            mc_dir=str(self.game_dir),
        )
        self.vega_store = ProfileAndConfigStore(
            data_dir=self.vega_dir,
            config_file=self.vega_dir / "launcher_config.json",
            profiles_dir=self.vega_dir / "profiles",
            mc_dir=self.game_dir,
            protect_fn=lambda s: f"dpapi:{s}",
            unprotect_fn=lambda s: s[6:] if str(s).startswith("dpapi:") else s,
        )
        self.service = LegacyLauncherMCPService(
            legacy_root=self.legacy_root,
            game_dir=self.game_dir,
            catalog=self.catalog,
            provisioner=self.provisioner,
            vega_store=self.vega_store,
        )
        set_legacy_service(self.service)

    def tearDown(self):
        set_legacy_service(None)
        self.tmp.cleanup()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_status_redacts_secrets_and_updates_tl_properties(self):
        self.assertEqual(
            _unescape_java_prop(r"C\:\\Users\\Bar\u0131\u015f\\game"),
            r"C:\Users\Barış\game",
        )
        raw = self._run(
            lms.legacy_get_status_and_settings(GetLegacyStatusInput(response_format=ResponseFormat.JSON))
        )
        self.assertNotIn("SECRET_CLIENT_UUID_999", raw)
        self.assertNotIn("SECRET_ACCOUNT_TOKEN", raw)
        self.assertNotIn("SUPER_SECRET_TOKEN", raw)
        data = json.loads(raw)
        self.assertEqual(data["active_version"], "Fabric 1.20.1")
        self.assertEqual(data["detected_mc_version"], "1.20.1")
        self.assertEqual(data["detected_loader"], "fabric")
        self.assertEqual(data["accounts"][0]["username"], "Arcturus")

        # Reject disallowed key
        bad = self._run(lms.legacy_update_settings(UpdateLegacySettingsInput(updates={"login.account": "hack"})))
        self.assertIn("Error: Disallowed", bad)

        # Select version and update RAM
        sel = json.loads(
            self._run(
                lms.legacy_select_version(
                    SelectLegacyVersionInput(version_id="NeoForge 1.21.1", ram_mb=8192)
                )
            )
        )
        self.assertTrue(sel["ok"])
        self.assertEqual(sel["ram_xmx"], "8192")
        self.assertEqual(sel["selected_version"]["loader"], "neoforge")

    def test_modrinth_install_update_and_manage_in_legacy(self):
        inst = json.loads(
            self._run(
                lms.legacy_install_modrinth_content(
                    InstallLegacyModrinthInput(project_id="AANobbMI", content_type="mod")
                )
            )
        )
        self.assertTrue(inst["ok"])
        self.assertEqual(inst["filename"], "sodium-fabric-0.5.11.jar")

        listed = json.loads(
            self._run(
                lms.legacy_list_installed_content(
                    ListLegacyContentInput(folder="mods", response_format=ResponseFormat.JSON)
                )
            )
        )
        self.assertEqual(listed["count"], 1)

        upd = json.loads(
            self._run(
                lms.legacy_check_mod_updates(
                    CheckLegacyModUpdatesInput(response_format=ResponseFormat.JSON)
                )
            )
        )
        self.assertEqual(upd["updates_count"], 1)

        dis = json.loads(
            self._run(
                lms.legacy_manage_installed_content(
                    ManageLegacyContentInput(
                        folder="mods",
                        filename="sodium-fabric-0.5.11.jar",
                        action="disable",
                    )
                )
            )
        )
        self.assertEqual(dis["new_filename"], "sodium-fabric-0.5.11.jar.disabled")

        del_ok = json.loads(
            self._run(
                lms.legacy_manage_installed_content(
                    ManageLegacyContentInput(
                        folder="mods",
                        filename="sodium-fabric-0.5.11.jar.disabled",
                        action="delete",
                        confirm=True,
                    )
                )
            )
        )
        self.assertTrue(del_ok["ok"])

    def test_world_backup_restore_logs_and_vega_sync(self):
        world_dir = self.game_dir / "saves" / "MySurvival"
        world_dir.mkdir(parents=True)
        (world_dir / "level.dat").write_bytes(b"nbt-data")

        bak = json.loads(
            self._run(
                lms.legacy_backup_world(
                    BackupLegacyWorldInput(world_name="MySurvival", label="snap1")
                )
            )
        )
        self.assertTrue(bak["ok"])
        bak_file = bak["backup_filename"]

        # Inject zip-slip entry and verify restore blocks it
        with zipfile.ZipFile(self.game_dir / "backups" / bak_file, "a") as zf:
            zf.writestr("../../escaped_world.txt", "bad")

        rest = json.loads(
            self._run(
                lms.legacy_restore_world_backup(
                    RestoreLegacyWorldBackupInput(
                        backup_filename=bak_file,
                        world_name="MySurvival",
                        confirm=True,
                    )
                )
            )
        )
        self.assertTrue(rest["ok"])
        self.assertFalse((self.base / "escaped_world.txt").exists())

        # Logs and crash reports
        crash_dir = self.game_dir / "crash-reports"
        crash_dir.mkdir(parents=True, exist_ok=True)
        (crash_dir / "crash-2026-10-17.txt").write_text("---- Minecraft Crash Report ----\n", encoding="utf-8")
        (self.game_dir / "logs" / "latest.log").write_text("[12:00:00] [Render thread/INFO]: Started\n", encoding="utf-8")

        logs_res = json.loads(
            self._run(
                lms.legacy_get_logs_and_crashes(
                    GetLegacyLogsInput(log_lines=10, response_format=ResponseFormat.JSON)
                )
            )
        )
        self.assertEqual(logs_res["crash_reports_count"], 1)
        self.assertIn("Minecraft Crash Report", logs_res["latest_crash_excerpt"][0])

        # Sync Legacy versions into Vega profiles and back
        sync_in = json.loads(
            self._run(
                lms.legacy_sync_with_vega(SyncLegacyWithVegaInput(direction="legacy_to_vega"))
            )
        )
        self.assertTrue(sync_in["ok"])
        self.assertEqual(sync_in["imported_count"], 2)

        sync_out = json.loads(
            self._run(
                lms.legacy_sync_with_vega(SyncLegacyWithVegaInput(direction="vega_to_legacy"))
            )
        )
        self.assertTrue(sync_out["ok"])
        self.assertEqual(sync_out["synced_profiles_count"], 2)


if __name__ == "__main__":
    unittest.main()

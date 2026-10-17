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
    raise unittest.SkipTest("mcp and pydantic are required for Vega MCP server tests")

import vega_mcp_server as vms
from mod_manager import ContentCatalog
from profile_store import ProfileAndConfigStore
from runtime_provisioner import RuntimeProvisioner
from vega_mcp_server import (
    CheckModUpdatesInput,
    CreateServerBackupInput,
    DeleteProfileInput,
    DeleteServerInput,
    DetectRuntimeInput,
    GetModrinthProjectInput,
    GetProfileInput,
    GetServerDetailsInput,
    GetSettingsInput,
    InstallClientRuntimeInput,
    InstallModrinthContentInput,
    ListProfilesInput,
    ListServersInput,
    ManageInstalledContentInput,
    ProvisionServerInput,
    ResponseFormat,
    RestoreServerBackupInput,
    SaveProfileInput,
    SearchModrinthInput,
    UpdateServerPropertiesInput,
    UpdateSettingsInput,
    VegaMCPService,
    set_service,
)


class FakeModrinthTransport:
    def __init__(self):
        self.downloaded: list[tuple[str, str]] = []

    def search_projects(self, query, project_type="mod", index="relevance", limit=12, version=None, loader=None, category=None):
        return [
            {
                "project_id": "AANobbMI",
                "slug": "sodium",
                "title": "Sodium",
                "author": "jellysquid3",
                "description": "Modern rendering engine for Fabric",
                "downloads": 50000000,
                "categories": ["optimization"],
                "versions": [version or "1.20.1"],
            }
        ]

    def get_project_details(self, project_id):
        if project_id == "missing":
            return None
        return {
            "id": project_id,
            "slug": "sodium",
            "title": "Sodium",
            "description": "Fast rendering engine",
            "downloads": 50000000,
            "followers": 120000,
            "loaders": ["fabric", "quilt", "neoforge"],
            "game_versions": ["1.20.1", "1.21.1"],
        }

    def get_project_versions(self, project_id, game_version=None, loader=None):
        return [
            {
                "id": "ver-sodium-1",
                "version_number": "0.5.11",
                "name": "Sodium 0.5.11",
                "game_versions": [game_version or "1.20.1"],
                "loaders": [loader] if isinstance(loader, str) else (loader or ["fabric"]),
                "files": [{"filename": "sodium-fabric-0.5.11.jar", "url": "https://cdn.modrinth.com/sodium.jar", "primary": True}],
            }
        ]

    def get_latest_version_file(self, project_id, game_version=None, loader=None):
        return {
            "version_id": "ver-sodium-1",
            "filename": "sodium-fabric-0.5.11.jar",
            "url": "https://cdn.modrinth.com/sodium.jar",
        }

    def download_file(self, url, dest_path, progress_callback=None):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"fake-jar-bytes")
        self.downloaded.append((url, dest_path))
        return True

    def check_version_updates(self, file_hashes, loaders=None, game_versions=None):
        if not file_hashes:
            return {}
        return {
            file_hashes[0]: {
                "id": "ver-sodium-2",
                "project_id": "AANobbMI",
                "version_number": "0.5.12",
                "files": [
                    {
                        "filename": "sodium-fabric-0.5.12.jar",
                        "url": "https://cdn.modrinth.com/sodium-0.5.12.jar",
                        "primary": True,
                        "hashes": {"sha1": "different_sha1_hash"},
                    }
                ],
            }
        }


class FakeClientInstallerBackend:
    def install_vanilla(self, version_id, mc_dir, callback=None):
        return None

    def install_fabric(self, mc_version, mc_dir, loader_version=None, callback=None):
        return f"fabric-loader-{loader_version or '0.16.9'}-{mc_version}"

    def install_quilt(self, mc_version, mc_dir, loader_version=None, callback=None):
        return f"quilt-loader-{mc_version}"

    def install_forge(self, mc_version, mc_dir, forge_version=None, callback=None):
        return f"{mc_version}-forge-{forge_version or '47.3.0'}"

    def install_neoforge(self, mc_version, mc_dir, loader_version=None, callback=None):
        return f"neoforge-{loader_version or '21.1.0'}-{mc_version}"


class TestVegaMCPServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.data_dir = self.base / "vega_data"
        self.mc_dir = self.base / "mc"
        self.servers_dir = self.data_dir / "servers"

        self.store = ProfileAndConfigStore(
            data_dir=self.data_dir,
            config_file=self.data_dir / "launcher_config.json",
            profiles_dir=self.data_dir / "profiles",
            mc_dir=self.mc_dir,
            protect_fn=lambda s: f"dpapi:{s}",
            unprotect_fn=lambda s: s[6:] if str(s).startswith("dpapi:") else s,
        )
        self.transport = FakeModrinthTransport()
        self.catalog = ContentCatalog(transport=self.transport, mc_dir=str(self.mc_dir))
        self.provisioner = RuntimeProvisioner(
            installer_backend=FakeClientInstallerBackend(),
            mc_dir=str(self.mc_dir),
        )
        self.service = VegaMCPService(
            store=self.store,
            catalog=self.catalog,
            provisioner=self.provisioner,
            servers_dir=self.servers_dir,
        )
        set_service(self.service)

    def tearDown(self):
        set_service(None)
        self.tmp.cleanup()

    def _run(self, coro):
        return asyncio.run(coro)

    def test_profile_lifecycle_and_confirm_guard(self):
        # 1. Create profile
        save_res = json.loads(
            self._run(
                vms.vega_save_profile(
                    SaveProfileInput(
                        name="FabricTest",
                        game_version="1.20.1",
                        loader="fabric",
                        ram_mb=6144,
                    )
                )
            )
        )
        self.assertTrue(save_res["ok"])
        self.assertEqual(save_res["profile"]["loader"], "fabric")
        self.assertEqual(save_res["profile"]["ram_mb"], 6144)
        created_id = save_res["profile"]["profile_id"]
        original_path = save_res["profile"]["path"]

        # Rename profile by ID -> must preserve original directory path
        rename_res = json.loads(
            self._run(
                vms.vega_save_profile(
                    SaveProfileInput(
                        profile_id=created_id,
                        name="FabricRenamed",
                        game_version="1.20.1",
                        loader="fabric",
                        ram_mb=6144,
                    )
                )
            )
        )
        self.assertEqual(rename_res["profile"]["name"], "FabricRenamed")
        self.assertEqual(rename_res["profile"]["path"], original_path)

        # 2. List profiles (JSON & Markdown)
        list_json = json.loads(
            self._run(vms.vega_list_profiles(ListProfilesInput(response_format=ResponseFormat.JSON)))
        )
        self.assertEqual(list_json["total"], 1)
        self.assertEqual(list_json["items"][0]["name"], "FabricRenamed")

        list_md = self._run(vms.vega_list_profiles(ListProfilesInput(response_format=ResponseFormat.MARKDOWN)))
        self.assertIn("FabricRenamed", list_md)

        # 3. Delete without confirm=True must fail safely
        del_blocked = self._run(vms.vega_delete_profile(DeleteProfileInput(profile="FabricRenamed", confirm=False)))
        self.assertIn("Error: Deletion aborted", del_blocked)

        # 4. Delete with confirm=True succeeds
        del_ok = json.loads(
            self._run(vms.vega_delete_profile(DeleteProfileInput(profile="FabricRenamed", confirm=True)))
        )
        self.assertTrue(del_ok["ok"])
        list_after = json.loads(
            self._run(vms.vega_list_profiles(ListProfilesInput(response_format=ResponseFormat.JSON)))
        )
        self.assertEqual(list_after["total"], 0)

    def test_settings_redacts_ms_login_tokens_and_rejects_unknown_keys(self):
        # Seed sensitive ms_login token in store using standard 'name' key from microsoft_account.complete_login
        profiles, _, settings = self.store.load()
        self.store.save(
            profiles,
            {"name": "VegaPlayer", "access_token": "SECRET_ACCESS_TOKEN_123", "refresh_token": "SECRET_REFRESH_456"},
            settings,
        )

        raw_out = self._run(vms.vega_get_settings(GetSettingsInput(response_format=ResponseFormat.JSON)))
        self.assertNotIn("SECRET_ACCESS_TOKEN_123", raw_out)
        self.assertNotIn("SECRET_REFRESH_456", raw_out)
        parsed = json.loads(raw_out)
        self.assertTrue(parsed["has_microsoft_session"])
        self.assertEqual(parsed["microsoft_username"], "VegaPlayer")

        # Reject disallowed setting key
        bad_upd = self._run(vms.vega_update_settings(UpdateSettingsInput(updates={"ms_login": "hack"})))
        self.assertIn("Error: Unknown or protected setting key", bad_upd)

        # Valid setting update
        good_upd = json.loads(
            self._run(vms.vega_update_settings(UpdateSettingsInput(updates={"default_ram": 8192})))
        )
        self.assertTrue(good_upd["ok"])
        self.assertEqual(good_upd["settings"]["default_ram"], 8192)

    def test_modrinth_search_install_update_and_manage_content(self):
        self._run(
            vms.vega_save_profile(
                SaveProfileInput(name="ModdedProf", game_version="1.20.1", loader="fabric")
            )
        )

        # Search
        search_res = json.loads(
            self._run(
                vms.vega_search_modrinth(
                    SearchModrinthInput(
                        query="sodium",
                        content_type="mod",
                        game_version="1.20.1",
                        loader="fabric",
                        response_format=ResponseFormat.JSON,
                    )
                )
            )
        )
        self.assertEqual(search_res["count"], 1)
        self.assertEqual(search_res["items"][0]["project_id"], "AANobbMI")

        # Project details
        proj_res = json.loads(
            self._run(
                vms.vega_get_modrinth_project(
                    GetModrinthProjectInput(
                        project_id="AANobbMI",
                        game_version="1.20.1",
                        loader="fabric",
                        response_format=ResponseFormat.JSON,
                    )
                )
            )
        )
        self.assertEqual(proj_res["title"], "Sodium")

        # Install mod into profile
        inst_res = json.loads(
            self._run(
                vms.vega_install_modrinth_content(
                    InstallModrinthContentInput(
                        project_id="AANobbMI",
                        content_type="mod",
                        target_type="profile",
                        target_name="ModdedProf",
                    )
                )
            )
        )
        self.assertTrue(inst_res["ok"])
        self.assertEqual(inst_res["filename"], "sodium-fabric-0.5.11.jar")

        # Check mod updates
        upd_res = json.loads(
            self._run(
                vms.vega_check_mod_updates(
                    CheckModUpdatesInput(
                        target_type="profile",
                        target_name="ModdedProf",
                        response_format=ResponseFormat.JSON,
                    )
                )
            )
        )
        self.assertEqual(upd_res["checked_files"], 1)
        self.assertEqual(upd_res["updates_count"], 1)
        self.assertEqual(upd_res["updates"][0]["latest_filename"], "sodium-fabric-0.5.12.jar")

        # Disable, enable, and delete mod
        dis_res = json.loads(
            self._run(
                vms.vega_manage_installed_content(
                    ManageInstalledContentInput(
                        target_type="profile",
                        target_name="ModdedProf",
                        folder="mods",
                        filename="sodium-fabric-0.5.11.jar",
                        action="disable",
                    )
                )
            )
        )
        self.assertEqual(dis_res["new_filename"], "sodium-fabric-0.5.11.jar.disabled")

        en_res = json.loads(
            self._run(
                vms.vega_manage_installed_content(
                    ManageInstalledContentInput(
                        target_type="profile",
                        target_name="ModdedProf",
                        folder="mods",
                        filename="sodium-fabric-0.5.11.jar.disabled",
                        action="enable",
                    )
                )
            )
        )
        self.assertEqual(en_res["new_filename"], "sodium-fabric-0.5.11.jar")

        del_res = json.loads(
            self._run(
                vms.vega_manage_installed_content(
                    ManageInstalledContentInput(
                        target_type="profile",
                        target_name="ModdedProf",
                        folder="mods",
                        filename="sodium-fabric-0.5.11.jar",
                        action="delete",
                        confirm=True,
                    )
                )
            )
        )
        self.assertTrue(del_res["ok"])

    def test_runtime_install_and_server_backup_restore_zip_slip(self):
        self._run(
            vms.vega_save_profile(
                SaveProfileInput(name="ClientProf", game_version="1.20.1", loader="fabric")
            )
        )
        rt_res = json.loads(
            self._run(
                vms.vega_install_client_runtime(
                    InstallClientRuntimeInput(
                        mc_version="1.20.1",
                        loader="fabric",
                        loader_version="0.16.9",
                        profile="ClientProf",
                    )
                )
            )
        )
        self.assertTrue(rt_res["ok"])
        self.assertEqual(rt_res["installed_version_id"], "fabric-loader-0.16.9-1.20.1")

        # Create a local server directory and test properties + backup + zip-slip safe restore
        srv_dir = self.servers_dir / "SurvivalSrv"
        (srv_dir / "logs").mkdir(parents=True)
        (srv_dir / "purpur-1.20.1.jar").write_bytes(b"jar")
        (srv_dir / "logs" / "latest.log").write_text("[12:00:00] [Server thread/INFO]: Done!\n", encoding="utf-8")

        prop_res = json.loads(
            self._run(
                vms.vega_update_server_properties(
                    UpdateServerPropertiesInput(
                        server_name="SurvivalSrv",
                        properties={"motd": "Hello MCP", "max-players": "40"},
                    )
                )
            )
        )
        self.assertTrue(prop_res["ok"])
        self.assertEqual(prop_res["properties"]["motd"], "Hello MCP")

        det_res = json.loads(
            self._run(
                vms.vega_get_server_details(
                    GetServerDetailsInput(
                        server_name="SurvivalSrv",
                        log_lines=10,
                        response_format=ResponseFormat.JSON,
                    )
                )
            )
        )
        self.assertEqual(det_res["loader"], "purpur")
        self.assertEqual(det_res["mc_version"], "1.20.1")
        self.assertIn("Done!", det_res["latest_log_tail"][0])

        # Create backup
        bak_res = json.loads(
            self._run(
                vms.vega_create_server_backup(
                    CreateServerBackupInput(server_name="SurvivalSrv", label="before_test")
                )
            )
        )
        self.assertTrue(bak_res["ok"])
        bak_name = bak_res["backup_filename"]

        # Append a malicious zip-slip entry into the backup zip and verify restore ignores it
        zip_full = srv_dir / "backups" / bak_name
        with zipfile.ZipFile(zip_full, "a") as zf:
            zf.writestr("../../escaped.txt", "malicious")

        restore_res = json.loads(
            self._run(
                vms.vega_restore_server_backup(
                    RestoreServerBackupInput(
                        server_name="SurvivalSrv",
                        backup_filename=bak_name,
                        confirm=True,
                        create_safety_backup=True,
                    )
                )
            )
        )
        self.assertTrue(restore_res["ok"])
        self.assertIsNotNone(restore_res["safety_backup_created"])
        self.assertFalse((self.base / "escaped.txt").exists())

        # Delete server requires confirm=True
        del_srv = json.loads(
            self._run(vms.vega_delete_server(DeleteServerInput(server_name="SurvivalSrv", confirm=True)))
        )
        self.assertTrue(del_srv["ok"])
        self.assertFalse(srv_dir.exists())


if __name__ == "__main__":
    unittest.main()

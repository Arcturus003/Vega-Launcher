import json
import os
import tempfile
import unittest

from profile_store import DEFAULT_SETTINGS, ProfileAndConfigStore


class TestProfileAndConfigStore(unittest.TestCase):
    def _make_store(self, tmp_dir):
        data_dir = os.path.join(tmp_dir, ".vega_launcher")
        mc_dir = os.path.join(tmp_dir, ".minecraft")
        store = ProfileAndConfigStore(
            data_dir=data_dir,
            mc_dir=mc_dir,
            protect_fn=lambda t: t if str(t).startswith("dpapi:") else f"dpapi:enc:{t}",
            unprotect_fn=lambda t: str(t).replace("dpapi:enc:", "", 1) if str(t).startswith("dpapi:enc:") else str(t),
        )
        return store

    def test_ensure_directories_and_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._make_store(tmp_dir)
            store.ensure_directories({"language": "en"})
            self.assertTrue(os.path.isdir(store.profiles_dir))
            self.assertTrue(os.path.isfile(store.config_file))

            raw = store.read_raw_config()
            self.assertEqual(raw["settings"]["language"], "en")
            self.assertEqual(raw["settings"]["default_ram"], DEFAULT_SETTINGS["default_ram"])

    def test_save_and_load_token_protection_and_migration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._make_store(tmp_dir)
            store.ensure_directories()

            # Write plaintext tokens directly to disk to test automatic migration on load
            with open(store.config_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profiles": {},
                        "ms_login": {"access_token": "plain_acc", "refresh_token": "plain_ref", "name": "Steve"},
                        "settings": {"language": "tr"},
                    },
                    f,
                )

            profiles, ms_login, settings = store.load()
            self.assertEqual(ms_login["access_token"], "plain_acc")
            self.assertEqual(ms_login["refresh_token"], "plain_ref")

            # Verify on-disk file now stores encrypted dpapi: tokens
            raw_on_disk = store.read_raw_config()
            self.assertEqual(raw_on_disk["ms_login"]["access_token"], "dpapi:enc:plain_acc")
            self.assertEqual(raw_on_disk["ms_login"]["refresh_token"], "dpapi:enc:plain_ref")

    def test_orphan_discovery_and_path_normalization(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._make_store(tmp_dir)
            store.ensure_directories()

            # Create an orphan directory on disk
            orphan_dir = os.path.join(store.profiles_dir, "OrphanPack")
            os.makedirs(orphan_dir, exist_ok=True)

            # Write a profile with a stale relocated path
            with open(store.config_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profiles": {
                            "p1": {
                                "name": "RelocatedPack",
                                "version": "1.20.4",
                                "ram": 6144,
                                "path": "D:/old_user/profiles/RelocatedPack",
                            }
                        },
                        "ms_login": {},
                        "settings": {"default_ram": 8192},
                    },
                    f,
                )

            profiles, _, _ = store.load()
            # RelocatedPack path normalized into current profiles_dir
            self.assertEqual(profiles["p1"]["path"], os.path.join(store.profiles_dir, "RelocatedPack"))

            # OrphanPack auto-registered with default_ram from settings
            orphan_entries = [p for p in profiles.values() if p.get("name") == "OrphanPack"]
            self.assertEqual(len(orphan_entries), 1)
            self.assertEqual(orphan_entries[0]["ram"], 8192)
            self.assertEqual(orphan_entries[0]["path"], orphan_dir)

    def test_sync_with_standard_launchers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._make_store(tmp_dir)
            store.ensure_directories()
            os.makedirs(store.mc_dir, exist_ok=True)

            lp_file = os.path.join(store.mc_dir, "launcher_profiles.json")
            with open(lp_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profiles": {
                            "vanilla_ official": {"name": "Latest Release", "lastVersionId": "1.21"},
                            "vega_stale": {"name": "[Vega] Deleted", "lastVersionId": "1.19"},
                        }
                    },
                    f,
                )

            active_profiles = {
                "active1": {
                    "name": "AetherPack",
                    "version": "fabric-loader-0.15.7-1.20.1",
                    "ram": 6144,
                    "path": os.path.join(store.profiles_dir, "AetherPack"),
                }
            }
            store.save(active_profiles, {}, {"language": "tr"}, sync_standard=True)

            for fname in ("launcher_profiles.json", "tlauncher_profiles.json"):
                fpath = os.path.join(store.mc_dir, fname)
                self.assertTrue(os.path.isfile(fpath))
                with open(fpath, "r", encoding="utf-8") as f:
                    synced = json.load(f)["profiles"]
                self.assertNotIn("vega_stale", synced)
                self.assertIn("vega_active1", synced)
                self.assertEqual(synced["vega_active1"]["name"], "[Vega] AetherPack")
                self.assertEqual(synced["vega_active1"]["javaArgs"], "-Xmx6144m -Xms512m")
                if fname == "launcher_profiles.json":
                    self.assertIn("vanilla_ official", synced)

    def test_generate_unique_profile_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._make_store(tmp_dir)
            store.ensure_directories()

            # Create folder for "Modpack"
            os.makedirs(os.path.join(store.profiles_dir, "Modpack"), exist_ok=True)
            # Register "Modpack (1)" in memory
            existing = {"id1": {"name": "Modpack (1)"}}

            name, path = store.generate_unique_profile_name("Modpack", existing)
            self.assertEqual(name, "Modpack (2)")
            self.assertEqual(path, os.path.join(store.profiles_dir, "Modpack (2)"))

    def test_delete_profile_directory_containment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._make_store(tmp_dir)
            store.ensure_directories()

            # Outside directory (sibling)
            outside_dir = os.path.join(tmp_dir, "outside_secret")
            os.makedirs(outside_dir, exist_ok=True)
            ok_out, reason_out = store.delete_profile_directory(outside_dir)
            self.assertFalse(ok_out)
            self.assertEqual(reason_out, "outside_containment")
            self.assertTrue(os.path.exists(outside_dir))

            # Profiles root directory itself must be rejected
            ok_root, reason_root = store.delete_profile_directory(store.profiles_dir)
            self.assertFalse(ok_root)
            self.assertEqual(reason_root, "outside_containment")
            self.assertTrue(os.path.exists(store.profiles_dir))

            # Valid child profile directory
            valid_dir = os.path.join(store.profiles_dir, "SafeToDelete")
            os.makedirs(valid_dir, exist_ok=True)
            with open(os.path.join(valid_dir, "dummy.txt"), "w") as f:
                f.write("hello")

            ok_valid, reason_valid = store.delete_profile_directory(valid_dir)
            self.assertTrue(ok_valid)
            self.assertEqual(reason_valid, "")
            self.assertFalse(os.path.exists(valid_dir))

    def test_get_and_update_setting_and_server_profile_matching(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = self._make_store(tmp_dir)
            store.ensure_directories()

            pack_dir = os.path.join(store.profiles_dir, "RPGPack")
            os.makedirs(pack_dir, exist_ok=True)

            store.save(
                {"p1": {"name": "RPGPack", "version": "1.20.1", "loader": "fabric", "path": pack_dir}},
                {"access_token": "tok"},
                {"language": "tr", "java_path": "C:/Java/bin/java.exe"},
                sync_standard=False,
            )

            store.update_setting("last_server", "RPGPack_Server")
            self.assertEqual(store.get_setting("last_server"), "RPGPack_Server")
            self.assertEqual(store.get_setting("java_path"), "C:/Java/bin/java.exe")

            names, pdict = store.list_available_client_profiles()
            self.assertIn("RPGPack", names)

            resolved_dir, matched = store.resolve_client_profile_dir("RPGPack", profiles_dict=pdict)
            self.assertEqual(resolved_dir, pack_dir)
            self.assertEqual(matched["loader"], "fabric")

            server_match = store.find_client_profile_for_server("RPGPack_Server")
            self.assertIsNotNone(server_match)
            self.assertEqual(server_match["name"], "RPGPack")
            self.assertIsNone(store.find_client_profile_for_server("Other_Server"))

    def test_cross_machine_dpapi_fallback_and_rebind(self):
        from auth_window import _dpapi_decrypt_raw, needs_rebind_token, protect_token, unprotect_token

        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = os.path.join(tmp_dir, ".vega_launcher")
            mc_dir = os.path.join(tmp_dir, ".minecraft")
            store = ProfileAndConfigStore(data_dir=data_dir, mc_dir=mc_dir)
            store.ensure_directories()

            # 1. Valid local DPAPI token with a legacy `.portable_part` suffix is upgraded to pure DPAPI
            local_dpapi = protect_token("strict_dpapi_access_token")
            self.assertFalse("." in local_dpapi[6:])
            self.assertFalse(needs_rebind_token(local_dpapi))

            legacy_dual_token = f"{local_dpapi}.LEGACY_PORTABLE_PART"
            self.assertTrue(needs_rebind_token(legacy_dual_token))

            with open(store.config_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profiles": {},
                        "ms_login": {
                            "access_token": legacy_dual_token,
                            "name": "Alex",
                        },
                        "settings": {"language": "tr"},
                    },
                    f,
                )

            _, ms_login, _ = store.load()
            self.assertEqual(ms_login["access_token"], "strict_dpapi_access_token")
            rebound_raw = store.read_raw_config()["ms_login"]["access_token"]
            self.assertFalse(needs_rebind_token(rebound_raw))
            self.assertEqual(_dpapi_decrypt_raw(rebound_raw[6:]), "strict_dpapi_access_token")

            # 2. Foreign machine DPAPI blob cannot be decrypted even if a portable suffix is attached
            foreign_blob = "dpapi:FOREIGN_USER_DPAPI_BLOB.ATTACKER_PORTABLE_SUFFIX"
            self.assertEqual(unprotect_token(foreign_blob), "")
            with open(store.config_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profiles": {},
                        "ms_login": {"access_token": foreign_blob, "name": "Alex"},
                        "settings": {"language": "tr"},
                    },
                    f,
                )
            _, cleaned_login, _ = store.load()
            self.assertNotIn("access_token", cleaned_login)
            self.assertEqual(cleaned_login.get("name"), "Alex")


if __name__ == "__main__":
    unittest.main()

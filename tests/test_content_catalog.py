import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from mod_manager import (
    CompatibilityPolicy,
    ContentCatalog,
    TransactionalRollback,
)


class FakeTransportAdapter:
    """In-memory test adapter satisfying the ContentCatalog transport seam."""
    def __init__(self, versions_by_query=None):
        self.versions_by_query = versions_by_query or {}
        self.calls = []
        self.downloaded = []

    def search_projects(self, query, project_type="mod", index="relevance", limit=12, version=None, loader=None, category=None):
        self.calls.append(("search", query, project_type, version, loader, category))
        return [{"project_id": "p1", "title": "Sodium"}]

    def get_project_details(self, project_id):
        self.calls.append(("details", project_id))
        return {"id": project_id, "title": "Test Project"}

    def get_project_versions(self, project_id, game_version=None, loader=None):
        self.calls.append(("versions", project_id, game_version, loader))
        return self.versions_by_query.get((project_id, game_version, str(loader)), [])

    def get_latest_version_file(self, project_id, game_version=None, loader=None):
        key_loader = tuple(loader) if isinstance(loader, list) else loader
        self.calls.append(("latest_file", project_id, game_version, key_loader))
        return self.versions_by_query.get((project_id, game_version, key_loader))

    def download_file(self, url, dest_path):
        self.downloaded.append((url, dest_path))
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"fake-binary-content")
        return True


class FakeLoaderInstallerAdapter:
    """In-memory test adapter at the loader installation seam."""
    def __init__(self):
        self.installed = []

    def install(self, mc_version, loader_name, loader_version, mc_dir, on_progress=None):
        self.installed.append((mc_version, loader_name, loader_version))
        return f"{loader_name}-loader-{loader_version}-{mc_version}"


class TestContentCatalogDeepModule(unittest.TestCase):
    def test_compatibility_policy_strict_mod_requires_both_version_and_loader(self):
        transport = FakeTransportAdapter({
            ("sodium", "1.20.1", "fabric"): {
                "version_id": "v1",
                "filename": "sodium-fabric-1.20.1.jar",
                "url": "https://cdn.modrinth.com/sodium.jar",
            }
        })
        catalog = ContentCatalog(transport=transport, loader_installer=FakeLoaderInstallerAdapter())

        # Missing loader -> strict rejection without network call
        missing_loader_policy = CompatibilityPolicy(content_type="mod", game_version="1.20.1", loader=None)
        self.assertIsNone(catalog.resolve_artifact("sodium", missing_loader_policy))
        self.assertEqual(len(transport.calls), 0)

        # Both present -> resolves
        valid_policy = CompatibilityPolicy(content_type="mod", game_version="1.20.1", loader="fabric")
        art = catalog.resolve_artifact("sodium", valid_policy)
        self.assertIsNotNone(art)
        self.assertEqual(art.filename, "sodium-fabric-1.20.1.jar")

    def test_compatibility_policy_quilt_expands_to_quilt_and_fabric(self):
        transport = FakeTransportAdapter({
            ("mod-x", "1.20.4", ("quilt", "fabric")): {
                "version_id": "vq",
                "filename": "mod-x-quilt.jar",
                "url": "https://cdn.modrinth.com/mod-x.jar",
            }
        })
        catalog = ContentCatalog(transport=transport, loader_installer=FakeLoaderInstallerAdapter())
        policy = CompatibilityPolicy.for_profile(
            {"version": "quilt-loader-0.25.0-1.20.4"}, "mod"
        )
        self.assertEqual(policy.effective_loaders, ("quilt", "fabric"))
        art = catalog.resolve_artifact("mod-x", policy)
        self.assertIsNotNone(art)
        self.assertEqual(art.version_id, "vq")

    def test_compatibility_policy_shader_ignores_loader(self):
        transport = FakeTransportAdapter({
            ("comp-shaders", "1.20.1", None): {
                "version_id": "vs1",
                "filename": "Complementary.zip",
                "url": "https://cdn.modrinth.com/comp.zip",
            }
        })
        catalog = ContentCatalog(transport=transport, loader_installer=FakeLoaderInstallerAdapter())
        policy = CompatibilityPolicy.for_profile(
            {"version": "fabric-loader-0.15.7-1.20.1", "loader": "fabric"}, "shader"
        )
        self.assertEqual(policy.effective_loaders, ())
        with tempfile.TemporaryDirectory() as tmpdir:
            res = catalog.install_artifact(tmpdir, policy, project_id="comp-shaders")
            self.assertTrue(res.ok)
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "shaderpacks", "Complementary.zip")))

            # Second install without overwrite detects existing file
            res_dup = catalog.install_artifact(tmpdir, policy, project_id="comp-shaders", overwrite=False)
            self.assertFalse(res_dup.ok)
            self.assertTrue(res_dup.already_exists)

    def test_modpack_update_policy_falls_back_to_loader_only(self):
        transport = FakeTransportAdapter({
            # No match for (1.20.1, fabric), but match for (None, fabric) when modpack upgrades MC version
            ("fabulously-optimized", None, "fabric"): {
                "version_id": "v_new_mc",
                "filename": "FO-1.20.4.mrpack",
                "url": "https://cdn.modrinth.com/fo.mrpack",
            }
        })
        catalog = ContentCatalog(transport=transport, loader_installer=FakeLoaderInstallerAdapter())
        profiles = {
            "prof1": {
                "project_id": "fabulously-optimized",
                "version_id": "v_old",
                "version": "fabric-loader-0.15.0-1.20.1",
                "loader": "fabric",
            }
        }
        updates = catalog.check_updates(profiles)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][0], "prof1")
        self.assertEqual(updates[0][1].version_id, "v_new_mc")

    def test_transactional_rollback_restores_on_modpack_failure_and_commits_on_success(self):
        loader_adapter = FakeLoaderInstallerAdapter()
        catalog = ContentCatalog(
            transport=FakeTransportAdapter(),
            loader_installer=loader_adapter,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_dir = Path(tmpdir) / "profile"
            mods_dir = profile_dir / "mods"
            config_dir = profile_dir / "config"
            mods_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (mods_dir / "old_mod.jar").write_text("old-mod", encoding="utf-8")
            (config_dir / "old_cfg.toml").write_text("old-cfg", encoding="utf-8")

            # 1. Corrupt archive update -> must roll back mods/ and config/ automatically
            corrupt_zip = Path(tmpdir) / "corrupt.mrpack"
            with zipfile.ZipFile(corrupt_zip, "w") as zf:
                zf.writestr("dummy.txt", "no index json here")

            fail_res = catalog.install_modpack(
                profile_dir, str(corrupt_zip), is_local=True, is_update=True
            )
            self.assertFalse(fail_res.ok)
            self.assertTrue(fail_res.rolled_back)
            self.assertTrue((mods_dir / "old_mod.jar").exists())
            self.assertTrue((config_dir / "old_cfg.toml").exists())
            self.assertFalse((profile_dir / "mods.old_bak").exists())

            # 2. Valid .mrpack update -> installs new overrides, invokes loader adapter, purges .old_bak
            valid_zip = Path(tmpdir) / "valid.mrpack"
            index_data = {
                "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.11"},
                "files": [],
            }
            with zipfile.ZipFile(valid_zip, "w") as zf:
                zf.writestr("modrinth.index.json", json.dumps(index_data))
                zf.writestr("overrides/config/new_cfg.toml", "new-cfg")

            ok_res = catalog.install_modpack(
                profile_dir, str(valid_zip), is_local=True, is_update=True
            )
            self.assertTrue(ok_res.ok)
            self.assertEqual(ok_res.version_id, "fabric-loader-0.15.11-1.20.1")
            self.assertEqual(loader_adapter.installed, [("1.20.1", "fabric", "0.15.11")])
            self.assertTrue((profile_dir / "config" / "new_cfg.toml").exists())
            self.assertFalse((profile_dir / "mods.old_bak").exists())
            self.assertFalse((profile_dir / "config.old_bak").exists())

    def test_catalog_task_runner_async(self):
        import sys
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        results = []
        catalog = ContentCatalog(transport=FakeTransportAdapter())
        runner = catalog.run_async(lambda: "computed_val", on_success=lambda r: results.append(r))
        self.assertIn(runner, catalog._active_runners)
        runner.wait(2000)
        app.processEvents()
        self.assertEqual(results, ["computed_val"])
        self.assertNotIn(runner, catalog._active_runners)

    def test_extract_zip_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "test.zip")
            out_dir = os.path.join(tmpdir, "out")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("normal.pak", b"pak-content")
                zf.writestr("sub/nested.pak", b"nested-pak")
                zf.writestr("other.txt", b"text-content")
                zf.writestr("../evil.txt", b"evil-content")

            # Test flatten with .pak filter
            extracted = ContentCatalog.extract_zip_safely(
                zip_path,
                out_dir,
                pattern=lambda fn: fn.lower().endswith(".pak"),
                flatten=True,
            )
            self.assertIn("normal.pak", extracted)
            self.assertIn("nested.pak", extracted)
            self.assertNotIn("other.txt", extracted)
            self.assertNotIn("../evil.txt", extracted)
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "normal.pak")))
            self.assertTrue(os.path.isfile(os.path.join(out_dir, "nested.pak")))
            self.assertFalse(os.path.isfile(os.path.join(tmpdir, "evil.txt")))


if __name__ == "__main__":
    unittest.main()

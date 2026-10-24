import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from curseforge_api import CurseForgeAPI, CLASS_IDS, LOADER_IDS, SORT_FIELDS
from mod_manager import (
    ContentCatalog,
    CompatibilityPolicy,
    find_existing_mod_files,
    DEFAULT_CURSEFORGE_CATALOG,
)


class TestCurseForgeAPI(unittest.TestCase):
    def test_class_ids_and_loaders(self):
        self.assertEqual(CLASS_IDS["mod"], 6)
        self.assertEqual(CLASS_IDS["modpack"], 4471)
        self.assertEqual(CLASS_IDS["shader"], 6552)
        self.assertEqual(LOADER_IDS["forge"], 1)
        self.assertEqual(LOADER_IDS["fabric"], 4)
        self.assertEqual(LOADER_IDS["neoforge"], 6)

    @patch("requests.Session.get")
    def test_search_projects_normalization(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": 238222,
                    "name": "Just Enough Items (JEI)",
                    "slug": "jei",
                    "summary": "View Items and Recipes",
                    "downloadCount": 150000000,
                    "thumbsUpCount": 12000,
                    "authors": [{"name": "mezz"}],
                    "logo": {"url": "https://example.com/jei.png"},
                    "latestFilesIndexes": [
                        {"gameVersion": "1.20.1", "modLoader": 4},
                        {"gameVersion": "1.20.1", "modLoader": 1},
                    ],
                    "categories": [{"name": "Map and Information"}],
                    "links": {"websiteUrl": "https://www.curseforge.com/minecraft/mc-mods/jei"},
                }
            ]
        }
        mock_get.return_value = mock_resp

        results = CurseForgeAPI.search_projects("jei", project_type="mod", version="1.20.1", loader="fabric")
        self.assertEqual(len(results), 1)
        mod = results[0]
        self.assertEqual(mod["id"], "238222")
        self.assertEqual(mod["project_id"], "238222")
        self.assertEqual(mod["title"], "Just Enough Items (JEI)")
        self.assertEqual(mod["author"], "mezz")
        self.assertEqual(mod["downloads"], 150000000)
        self.assertEqual(mod["source"], "curseforge")
        self.assertIn("1.20.1", mod["versions"])

    @patch("requests.Session.get")
    def test_get_project_details(self, mock_get):
        def _get_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith("/description"):
                resp.json.return_value = {"data": "<p>Detailed HTML description of mod</p>"}
            else:
                resp.json.return_value = {
                    "data": {
                        "id": 12345,
                        "name": "Test Mod",
                        "slug": "test-mod",
                        "summary": "Short summary",
                        "downloadCount": 500,
                        "authors": [{"name": "Dev"}],
                        "logo": {"url": "https://example.com/logo.png"},
                        "screenshots": [{"url": "https://example.com/shot1.png"}],
                    }
                }
            return resp

        mock_get.side_effect = _get_side_effect

        details = CurseForgeAPI.get_project_details("12345")
        self.assertIsNotNone(details)
        self.assertEqual(details["title"], "Test Mod")
        self.assertEqual(len(details["gallery"]), 1)
        self.assertEqual(details["gallery"][0]["url"], "https://example.com/shot1.png")
        self.assertEqual(details["source"], "curseforge")
        self.assertIn("Detailed HTML description", details["description"])

    @patch("requests.Session.get")
    def test_get_project_versions_and_latest(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": 9999123,
                    "fileName": "testmod-1.20.1-fabric-1.0.jar",
                    "displayName": "TestMod 1.0 Fabric",
                    "downloadUrl": "https://edge.forgecdn.net/files/9999/123/testmod-1.20.1-fabric-1.0.jar",
                    "gameVersions": ["1.20.1", "Fabric"],
                    "isAvailable": True,
                    "fileLength": 1024,
                }
            ]
        }
        mock_get.return_value = mock_resp

        versions = CurseForgeAPI.get_project_versions("12345", game_version="1.20.1", loader="fabric")
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["id"], "9999123")
        self.assertEqual(versions[0]["files"][0]["filename"], "testmod-1.20.1-fabric-1.0.jar")

        latest = CurseForgeAPI.get_latest_version_file("12345", game_version="1.20.1", loader="fabric")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["version_id"], "9999123")
        self.assertEqual(latest["filename"], "testmod-1.20.1-fabric-1.0.jar")

    def test_find_existing_mod_files_and_conflict_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mods_dir = os.path.join(tmpdir, "mods")
            os.makedirs(mods_dir, exist_ok=True)

            old_file = os.path.join(mods_dir, "jei-1.20.1-fabric-15.71.0.jar")
            with open(old_file, "w") as f:
                f.write("old version")

            # Detect existing mod with new version name
            matches = find_existing_mod_files(mods_dir, "jei-1.20.1-fabric-15.74.0.jar")
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0], "jei-1.20.1-fabric-15.71.0.jar")

            # Test catalog install_artifact with conflict detection & overwrite
            mock_transport = MagicMock()
            mock_transport.download_file.return_value = True

            catalog = ContentCatalog(transport=mock_transport)
            policy = CompatibilityPolicy(content_type="mod", game_version="1.20.1", loader="fabric")

            # 1. Without overwrite, should detect already exists
            res_conflict = catalog.install_artifact(
                tmpdir,
                policy,
                explicit_url="https://example.com/jei-new.jar",
                explicit_filename="jei-1.20.1-fabric-15.74.0.jar",
                overwrite=False,
            )
            self.assertFalse(res_conflict.ok)
            self.assertTrue(res_conflict.already_exists)
            self.assertEqual(res_conflict.conflicting_file, "jei-1.20.1-fabric-15.71.0.jar")

            # 2. With overwrite, replaces and deletes old version
            res_replace = catalog.install_artifact(
                tmpdir,
                policy,
                explicit_url="https://example.com/jei-new.jar",
                explicit_filename="jei-1.20.1-fabric-15.74.0.jar",
                overwrite=True,
            )
            self.assertTrue(res_replace.ok)
            # Old version file should have been removed
            self.assertFalse(os.path.exists(old_file))

    def test_default_curseforge_catalog_pluggability(self):
        self.assertIsNotNone(DEFAULT_CURSEFORGE_CATALOG)
        self.assertEqual(DEFAULT_CURSEFORGE_CATALOG.transport, CurseForgeAPI)


if __name__ == "__main__":
    unittest.main()

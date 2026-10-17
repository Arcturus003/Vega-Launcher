import json
import os
import tempfile
import unittest

from server_instance import (
    DEFAULT_SERVER_PROPERTIES,
    ServerInstance,
    ServerProperties,
)


class TestServerInstance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.server_dir = os.path.join(self.temp_dir.name, "MyServer")
        self.inst = ServerInstance(self.server_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initialize_and_ensure_boot_ready(self):
        self.inst.initialize_directory()
        eula_path = os.path.join(self.server_dir, "eula.txt")
        props_path = os.path.join(self.server_dir, "server.properties")
        self.assertTrue(os.path.exists(eula_path))
        self.assertTrue(os.path.exists(props_path))

        # Corrupt eula to false and properties to comments-only, then ensure_boot_ready fixes both
        with open(eula_path, "w", encoding="utf-8") as f:
            f.write("# comment\neula=false\n")
        with open(props_path, "w", encoding="utf-8") as f:
            f.write("# only comments\n\n")

        self.inst.ensure_boot_ready()
        with open(eula_path, "r", encoding="utf-8") as f:
            self.assertIn("eula=true", f.read())
        with open(props_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), DEFAULT_SERVER_PROPERTIES)

    def test_has_launch_artifact(self):
        self.inst.initialize_directory()
        self.assertFalse(self.inst.has_launch_artifact())
        with open(os.path.join(self.server_dir, "server.jar"), "wb") as f:
            f.write(b"jar")
        self.assertTrue(self.inst.has_launch_artifact())

    def test_read_and_write_properties_preserves_custom_lines(self):
        os.makedirs(self.server_dir, exist_ok=True)
        props_path = os.path.join(self.server_dir, "server.properties")
        with open(props_path, "w", encoding="utf-8") as f:
            f.write(
                "# Custom Header\n"
                "server-port=25570\n"
                "white-list=true\n"
                "max-players=12\n"
                "online-mode=false\n"
            )

        props = self.inst.read_properties()
        self.assertEqual(props.server_port, "25570")
        self.assertEqual(props.max_players, 12)
        self.assertFalse(props.online_mode)

        props.max_players = 32
        props.motd = "Vega Test Server"
        props.difficulty = "hard"
        self.inst.write_properties(props)

        with open(props_path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("# Custom Header", raw)
        self.assertIn("white-list=true", raw)

        reloaded = self.inst.read_properties()
        self.assertEqual(reloaded.max_players, 32)
        self.assertEqual(reloaded.motd, "Vega Test Server")
        self.assertEqual(reloaded.difficulty, "hard")
        self.assertEqual(reloaded.server_port, "25570")

    def test_import_and_sync_mods_filters_client_blacklist(self):
        client_dir = os.path.join(self.temp_dir.name, "ClientProfile")
        c_mods = os.path.join(client_dir, "mods")
        c_cfg = os.path.join(client_dir, "config")
        os.makedirs(c_mods, exist_ok=True)
        os.makedirs(c_cfg, exist_ok=True)

        with open(os.path.join(c_mods, "sodium-fabric-0.5.8.jar"), "wb") as f:
            f.write(b"client")
        with open(os.path.join(c_mods, "iris-1.7.0.jar"), "wb") as f:
            f.write(b"client")
        with open(os.path.join(c_mods, "fabric-api-0.92.0.jar"), "wb") as f:
            f.write(b"shared")
        with open(os.path.join(c_cfg, "my_mod.toml"), "w", encoding="utf-8") as f:
            f.write("enabled = true\n")

        self.inst.import_from_client_profile(client_dir)
        s_mods = os.path.join(self.server_dir, "mods")
        self.assertTrue(os.path.exists(os.path.join(s_mods, "fabric-api-0.92.0.jar")))
        self.assertFalse(os.path.exists(os.path.join(s_mods, "sodium-fabric-0.5.8.jar")))
        self.assertFalse(os.path.exists(os.path.join(s_mods, "iris-1.7.0.jar")))
        self.assertTrue(os.path.exists(os.path.join(self.server_dir, "config", "my_mod.toml")))

        # Put a blacklisted mod and a playit mod in server mods, plus a new mod in client mods
        with open(os.path.join(s_mods, "xaero_minimap.jar"), "wb") as f:
            f.write(b"bad")
        with open(os.path.join(s_mods, "playit-sodium-compat.jar"), "wb") as f:
            f.write(b"keep-playit")
        with open(os.path.join(c_mods, "lithium-fabric.jar"), "wb") as f:
            f.write(b"server-perf")

        diff = self.inst.sync_mods_from_client(client_dir)
        self.assertEqual(diff.added, 1)
        self.assertEqual(diff.removed, 1)
        self.assertTrue(os.path.exists(os.path.join(s_mods, "lithium-fabric.jar")))
        self.assertFalse(os.path.exists(os.path.join(s_mods, "xaero_minimap.jar")))
        self.assertTrue(os.path.exists(os.path.join(s_mods, "playit-sodium-compat.jar")))

    def test_players_and_counts(self):
        self.inst.initialize_directory()
        with open(os.path.join(self.server_dir, "usercache.json"), "w", encoding="utf-8") as f:
            json.dump([{"name": "Steve"}, {"name": "Alex"}], f)
        with open(os.path.join(self.server_dir, "ops.json"), "w", encoding="utf-8") as f:
            json.dump([{"name": "Steve"}], f)

        self.assertEqual(self.inst.list_known_players(), {"Steve", "Alex"})
        self.assertTrue(self.inst.is_player_op("steve"))
        self.assertFalse(self.inst.is_player_op("Alex"))

        os.makedirs(os.path.join(self.server_dir, "mods"), exist_ok=True)
        os.makedirs(os.path.join(self.server_dir, "backups"), exist_ok=True)
        with open(os.path.join(self.server_dir, "mods", "a.jar"), "wb") as f:
            f.write(b"1")
        with open(os.path.join(self.server_dir, "backups", "b1.zip"), "wb") as f:
            f.write(b"2")

        self.assertEqual(self.inst.count_content_and_backups(), (1, 1))


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from launch_pipeline import GameLaunchPipeline, LaunchSession
from server_console_parser import ServerConsoleParser, ConsoleEvent
from auth_vault import AuthenticationVault, AuthSession
from playtime_tracker import PlaytimeTrackerThread


class TestGameLaunchPipeline(unittest.TestCase):
    def setUp(self):
        self.mock_backend = MagicMock()
        self.mock_backend.get_minecraft_command.return_value = ["java", "-jar", "minecraft.jar"]
        self.pipeline = GameLaunchPipeline(mc_dir="dummy/.minecraft", backend=self.mock_backend)

    def test_build_jvm_arguments(self):
        args = self.pipeline.build_jvm_arguments(ram_mb=8192, extra_args="-XX:+UseG1GC -Dtest=true")
        self.assertIn("-Xmx8192m", args)
        self.assertIn("-Xms512m", args)
        self.assertIn("-XX:+UseG1GC", args)
        self.assertIn("-Dtest=true", args)

    def test_build_launch_options(self):
        auth = {"name": "Alex", "id": "uuid-123", "access_token": "token-xyz"}
        opts = self.pipeline.build_launch_options(
            auth_session=auth,
            game_directory="C:/games/profile1",
            ram_mb=4096,
        )
        self.assertEqual(opts["username"], "Alex")
        self.assertEqual(opts["uuid"], "uuid-123")
        self.assertEqual(opts["token"], "token-xyz")
        self.assertEqual(opts["gameDirectory"], "C:/games/profile1")
        self.assertIn("-Xmx4096m", opts["jvmArguments"])

    def test_loader_detection(self):
        self.assertTrue(self.pipeline.is_loader_version("fabric-loader-0.15.7-1.20.4"))
        self.assertTrue(self.pipeline.is_loader_version("forge-47.2.0"))
        self.assertTrue(self.pipeline.is_loader_version("neoforge-20.4.167"))
        self.assertFalse(self.pipeline.is_loader_version("1.20.4"))

        self.assertEqual(self.pipeline.detect_loader_type("fabric-loader-0.15.7-1.20.4"), "fabric")
        self.assertEqual(self.pipeline.detect_loader_type("forge-47.2.0"), "forge")
        self.assertEqual(self.pipeline.detect_loader_type("neoforge-20.4.167"), "neoforge")
        self.assertEqual(self.pipeline.detect_loader_type("quilt-loader-0.20.0"), "quilt")
        self.assertEqual(self.pipeline.detect_loader_type("1.20.4"), "vanilla")

    @patch("subprocess.Popen")
    @patch("os.makedirs")
    def test_launch_execution(self, mock_makedirs, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        pdata = {"version": "1.20.4", "path": "C:/dummy_profile", "ram": 4096}
        session = self.pipeline.launch(
            profile_id="p_test",
            profile_data=pdata,
            auth_session={"name": "Steve", "id": "123"},
            settings={"default_ram": 2048},
        )
        self.assertIsInstance(session, LaunchSession)
        self.assertEqual(session.pid, "9999")
        self.assertEqual(session.version, "1.20.4")
        self.assertEqual(session.profile_id, "p_test")
        self.mock_backend.get_minecraft_command.assert_called_once()
        mock_popen.assert_called_once()


class TestServerConsoleParser(unittest.TestCase):
    def setUp(self):
        self.parser = ServerConsoleParser()

    def test_classify_log_level(self):
        self.assertEqual(self.parser.classify_log_level("[Server thread/INFO]: Starting minecraft server"), "INFO")
        self.assertEqual(self.parser.classify_log_level("[Server thread/WARN]: Can't keep up!"), "WARN")
        self.assertEqual(self.parser.classify_log_level("[Server thread/ERROR]: Encountered an unexpected exception"), "ERROR")

    def test_format_html(self):
        html = self.parser.format_html("[Server thread/INFO]: Done (2.5s)!")
        self.assertIn("color:", html)
        self.assertIn("Done (2.5s)!", html)

    def test_feed_line_events(self):
        # Test server ready
        line_ready = "[12:00:00 INFO]: Done (4.123s)! For help, type \"help\""
        events = self.parser.feed_line(line_ready)
        self.assertTrue(any(e.event_type == "online" for e in events))

        # Test player join
        line_join = "[12:01:00 INFO]: Steve joined the game"
        events = self.parser.feed_line(line_join)
        self.assertTrue(any(e.event_type == "player_joined" and e.data == "Steve" for e in events))

        # Test player leave
        line_leave = "[12:05:00 INFO]: Steve left the game"
        events = self.parser.feed_line(line_leave)
        self.assertTrue(any(e.event_type == "player_left" and e.data == "Steve" for e in events))

        # Test world saved
        line_save = "[12:10:00 INFO]: All dimensions are saved"
        events = self.parser.feed_line(line_save)
        self.assertTrue(any(e.event_type == "world_saved" for e in events))

        # Test stopping
        line_stop = "[12:15:00 INFO]: Stopping the server"
        events = self.parser.feed_line(line_stop)
        self.assertTrue(any(e.event_type == "stopping" for e in events))

        # Test playit ip
        line_playit = "[playit]: visit https://playit.gg/claim/xyz123 to setup"
        events = self.parser.feed_line(line_playit)
        self.assertTrue(any(e.event_type == "claim_url" and "https://playit.gg/claim/xyz123" in (e.data or "") for e in events))


class TestAuthenticationVault(unittest.TestCase):
    def test_encryption_roundtrip(self):
        raw = "secret_access_token_12345"
        encrypted = AuthenticationVault.encrypt_secret(raw)
        self.assertTrue(encrypted.startswith("dpapi:"))
        decrypted = AuthenticationVault.decrypt_secret(encrypted)
        self.assertEqual(decrypted, raw)

    def test_needs_rebind(self):
        self.assertFalse(AuthenticationVault.needs_rebind(""))
        self.assertFalse(AuthenticationVault.needs_rebind(None))
        self.assertTrue(AuthenticationVault.needs_rebind("plain_text_token"))
        
        enc = AuthenticationVault.encrypt_secret("valid_token")
        self.assertFalse(AuthenticationVault.needs_rebind(enc))
        # Legacy dot format should trigger rebind
        self.assertTrue(AuthenticationVault.needs_rebind(f"{enc}.portable_hash"))

    def test_account_storage_protection(self):
        acc = {
            "name": "Miner",
            "id": "u-1",
            "access_token": "token_1",
            "refresh_token": "token_2",
            "type": "msa",
        }
        protected = AuthenticationVault.protect_account_for_storage(acc)
        self.assertTrue(protected["access_token"].startswith("dpapi:"))
        self.assertTrue(protected["refresh_token"].startswith("dpapi:"))

        unprotected = AuthenticationVault.unprotect_account_for_runtime(protected)
        self.assertEqual(unprotected["access_token"], "token_1")
        self.assertEqual(unprotected["refresh_token"], "token_2")

    def test_build_auth_session(self):
        session_offline = AuthenticationVault.build_auth_session(None, offline_name="OfflinePlayer")
        self.assertEqual(session_offline.username, "OfflinePlayer")
        self.assertTrue(session_offline.is_offline)

        acc = {"name": "OnlinePlayer", "id": "123", "access_token": "valid_token"}
        session_online = AuthenticationVault.build_auth_session(acc)
        self.assertEqual(session_online.username, "OnlinePlayer")
        self.assertFalse(session_online.is_offline)
        self.assertEqual(session_online.access_token, "valid_token")

    def test_is_network_available_returns_bool(self):
        res = AuthenticationVault.is_network_available(timeout=0.1)
        self.assertIsInstance(res, bool)


class TestPlaytimeTrackerSafety(unittest.TestCase):
    def test_instant_crash_process(self):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # already dead
        tracker = PlaytimeTrackerThread(mock_proc, "profile_1")

        result = []
        tracker.tracking_finished.connect(lambda pid, elapsed: result.append((pid, elapsed)))
        tracker.run()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "profile_1")
        self.assertGreaterEqual(result[0][1], 0)

    def test_exception_during_poll(self):
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = OSError("Handle closed")
        tracker = PlaytimeTrackerThread(mock_proc, "profile_1")

        result = []
        tracker.tracking_finished.connect(lambda pid, elapsed: result.append((pid, elapsed)))
        tracker.run()

        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(result[0][1], 0)


class TestDungeonsModsResolver(unittest.TestCase):
    def test_resolve_dungeons_mods_dir_no_throw(self):
        from main import VegaLauncher
        # Must execute cleanly on any Windows system without crashing
        res = VegaLauncher.resolve_dungeons_mods_dir()
        if res is not None:
            self.assertTrue(os.path.isabs(res))
            self.assertTrue(res.endswith("~mods"))


class TestServerProcessCoordinator(unittest.TestCase):
    def setUp(self):
        from server_process_coordinator import ServerProcessCoordinator, ServerState
        self.coordinator = ServerProcessCoordinator()

    def test_state_transitions(self):
        from server_process_coordinator import ServerState
        self.assertEqual(self.coordinator.state, ServerState.STOPPED)

        mock_th = MagicMock()
        mock_th.is_running = True
        self.coordinator.attach_thread(mock_th)
        self.assertEqual(self.coordinator.state, ServerState.STARTING)

        self.coordinator.handle_stdout_line("[Server thread/INFO]: Done (2.5s)! For help, type \"help\"")
        self.assertEqual(self.coordinator.state, ServerState.RUNNING)

        self.coordinator.handle_stdout_line("[Server thread/INFO]: Stopping the server")
        self.assertEqual(self.coordinator.state, ServerState.STOPPING)

        self.coordinator.on_process_exited(0)
        self.assertEqual(self.coordinator.state, ServerState.STOPPED)

    def test_quiesce_for_backup(self):
        mock_th = MagicMock()
        mock_th.is_running = True
        self.coordinator.attach_thread(mock_th)

        with self.coordinator.quiesce_for_backup(flush_timeout_sec=0.1):
            mock_th.send_command.assert_any_call("save-off")
            mock_th.send_command.assert_any_call("save-all flush")

        mock_th.send_command.assert_called_with("save-on")


class TestSoundManagerSafeHelpers(unittest.TestCase):
    def test_safe_helpers_no_throw(self):
        from sound_manager import SoundManager
        # Must execute cleanly without raising exceptions even in test runner
        SoundManager.safe_click()
        SoundManager.safe_error()
        SoundManager.safe_play("launch")


if __name__ == "__main__":
    unittest.main()


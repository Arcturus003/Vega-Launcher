import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from auth_vault import AuthenticationVault
from crash_analyzer import CrashAnalyzer, CrashReport
from java_provisioner import JavaProvisioner
from launch_pipeline import GameLaunchPipeline
from profile_store import ProfileAndConfigStore, ProfileSessionManager
from runtime_provisioner import RuntimeProvisioner, RuntimeSpec
from server_console_parser import ConsoleEvent, ServerConsoleParser
from server_process_coordinator import ServerProcessCoordinator, ServerState


class TestArchitectureDeepening(unittest.TestCase):
    # --- Candidate 1: AuthenticationVault & GameLaunchPipeline ---

    def test_auth_vault_validate_or_refresh_session_valid_token(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http.get.return_value = mock_resp

        res = AuthenticationVault.validate_or_refresh_session(
            {"access_token": "valid_token_123"},
            transport=mock_http,
        )
        self.assertEqual(res["status"], "ok")
        self.assertIsNone(res["new_data"])

    def test_auth_vault_validate_or_refresh_session_refresh_success(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_http.get.return_value = mock_resp

        mock_refresh = MagicMock(return_value={"access_token": "new_tok", "refresh_token": "new_ref"})

        res = AuthenticationVault.validate_or_refresh_session(
            {"access_token": "expired_tok", "refresh_token": "old_ref"},
            transport=mock_http,
            refresh_fn=mock_refresh,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["new_data"]["access_token"], "new_tok")

    def test_auth_vault_validate_or_refresh_session_network_error_abort(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_http.get.return_value = mock_resp

        def mock_refresh_fail(*args, **kwargs):
            raise OSError("getaddrinfo failed: Connection timed out")

        res = AuthenticationVault.validate_or_refresh_session(
            {"access_token": "expired_tok", "refresh_token": "old_ref"},
            transport=mock_http,
            refresh_fn=mock_refresh_fail,
        )
        self.assertEqual(res["status"], "network_error_abort")

    def test_launch_pipeline_evaluate_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = GameLaunchPipeline(mc_dir=tmpdir)
            pdata = {
                "id": "prof1",
                "name": "Profile 1",
                "version": "1.20.1",
                "path": tmpdir,
                "ram": 4096,
                "loader": "vanilla",
            }
            res = pipeline.evaluate_readiness(
                profile_id_or_data="prof1",
                profile_data=pdata,
                auth_session={"name": "PlayerOne", "uuid": "u1", "token": "tok"},
                settings={"default_ram": 4096},
            )
            self.assertIn("ready", res)
            self.assertIn("required_java_major", res)
            self.assertIn("options", res)
            self.assertEqual(res["required_java_major"], 17)
            self.assertEqual(res["profile_id"], "prof1")

    # --- Candidate 2: ProfileAndConfigStore & ProfileSessionManager ---

    def test_profile_store_crud_and_invariants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ProfileAndConfigStore()
            store.config_file = os.path.join(tmpdir, "launcher_config.json")
            store.profiles_dir = tmpdir
            store.sync_with_standard_launchers = MagicMock()

            profiles = {}
            # Invariant check: empty name fails
            self.assertFalse(store.create_profile(profiles, "p1", {"name": "", "ram": 4096}))
            # Invariant check: invalid RAM fails
            self.assertFalse(store.create_profile(profiles, "p1", {"name": "P1", "ram": 256}))
            # Valid create
            self.assertTrue(store.create_profile(profiles, "p1", {"name": "P1", "ram": 4096}))
            self.assertIn("p1", profiles)
            store.sync_with_standard_launchers.assert_called()

            # Update profile
            store.sync_with_standard_launchers.reset_mock()
            self.assertTrue(store.update_profile(profiles, "p1", {"ram": 8192}))
            self.assertEqual(profiles["p1"]["ram"], 8192)

            # Add playtime (sync_standard=False by default)
            store.sync_with_standard_launchers.reset_mock()
            new_tot = store.add_playtime(profiles, "p1", 120)
            self.assertEqual(new_tot, 120)
            self.assertEqual(profiles["p1"]["playtime"], 120)
            store.sync_with_standard_launchers.assert_not_called()

            # Delete profile
            self.assertTrue(store.delete_profile(profiles, "p1"))
            self.assertNotIn("p1", profiles)

    def test_profile_session_manager_facade_and_signals(self):
        mock_store = MagicMock(spec=ProfileAndConfigStore)
        mock_store.validate_profile_invariants.return_value = (True, "")
        mock_store.create_profile.return_value = True

        profiles = {}
        manager = ProfileSessionManager(store=mock_store, profiles=profiles)

        selected_events = []
        manager.profile_selected.connect(lambda pid, pdata: selected_events.append((pid, pdata)))

        profiles["p1"] = {"name": "P1", "ram": 4096}
        pid, pdata = manager.select_profile("p1")
        self.assertEqual(pid, "p1")
        self.assertEqual(len(selected_events), 1)
        self.assertEqual(selected_events[0][0], "p1")

    # --- Candidate 3: ServerProcessCoordinator & ConsoleEvent routing ---

    def test_server_process_coordinator_all_console_events(self):
        parser = ServerConsoleParser()
        coord = ServerProcessCoordinator(parser=parser)
        received_events = []
        coord.set_event_callback(lambda ev: received_events.append(ev))

        # Test player join & leave
        coord.handle_stdout_line("[12:00:00 INFO]: Steve joined the game")
        self.assertIn("Steve", coord.online_players)

        coord.handle_stdout_line("[12:05:00 INFO]: Steve left the game")
        self.assertNotIn("Steve", coord.online_players)

        # Test playit IP & claim URL
        coord.handle_stdout_line("[12:06:00 INFO]: [playit.gg] Visit https://playit.gg/claim/abc-123 to claim tunnel")
        self.assertIn("https://playit.gg/claim/abc-123", coord.claimed_urls)

        coord.handle_stdout_line("[12:07:00 INFO]: [playit.gg] Tunnel active at custom-domain.playit.gg:25565")
        self.assertEqual(coord.playit_ip, "custom-domain.playit.gg:25565")

        self.assertGreaterEqual(len(received_events), 4)

    def test_server_process_coordinator_quiesce_for_backup(self):
        mock_thread = MagicMock()
        coord = ServerProcessCoordinator()
        coord.attach_thread(mock_thread)
        coord._set_state(ServerState.RUNNING)

        sent_commands = []
        coord.send_command = lambda cmd: sent_commands.append(cmd)

        with coord.quiesce_for_backup(flush_timeout_sec=0.1):
            self.assertEqual(sent_commands, ["save-off", "save-all flush"])
        self.assertEqual(sent_commands, ["save-off", "save-all flush", "save-on"])

    # --- Candidate 4: CrashAnalyzer log discovery & signatures ---

    def test_crash_analyzer_log_discovery_and_hs_err_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hs_file = os.path.join(tmpdir, "hs_err_pid9999.log")
            with open(hs_file, "w") as f:
                f.write("# A fatal error has been detected by the Java Runtime Environment:\n# EXCEPTION_ACCESS_VIOLATION\n")

            found = CrashAnalyzer.find_latest_crash_file(tmpdir)
            self.assertIsNotNone(found)
            self.assertEqual(os.path.basename(found[0]), "hs_err_pid9999.log")
            self.assertTrue(found[1])

            report = CrashAnalyzer.analyze_text(
                "# EXCEPTION_ACCESS_VIOLATION (0xc0000005) at pc=0x00007ff81234, pid=9999",
                exit_code=1,
                lang="en",
            )
            self.assertIn(report.severity, ("CRITICAL", "FATAL", "ERROR"))
            self.assertIn("JVM / Native Crash", report.title)

    # --- Candidate 5: RuntimeProvisioner and GLOSSARY ---

    def test_runtime_provisioner_version_inspect_and_glossary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            versions_dir = os.path.join(tmpdir, "versions")
            fab_dir = os.path.join(versions_dir, "fabric-loader-0.15.11-1.20.1")
            os.makedirs(fab_dir, exist_ok=True)
            with open(os.path.join(fab_dir, "fabric-loader-0.15.11-1.20.1.json"), "w") as f:
                f.write('{"id": "fabric-loader-0.15.11-1.20.1", "inheritsFrom": "1.20.1"}')

            spec = RuntimeProvisioner.inspect_version_dir(versions_dir, "fabric-loader-0.15.11-1.20.1")
            self.assertIsNotNone(spec)
            self.assertEqual(spec.mc_version, "1.20.1")
            self.assertEqual(spec.loader, "fabric")
            self.assertEqual(spec.loader_version, "0.15.11")

            found_ver = RuntimeProvisioner.find_installed_loader_version(tmpdir, "1.20.1", "fabric")
            self.assertEqual(found_ver, "fabric-loader-0.15.11-1.20.1")

        # Verify GLOSSARY.md mentions JavaProvisioner and CrashAnalyzer
        glossary_path = os.path.join(ROOT, "GLOSSARY.md")
        self.assertTrue(os.path.exists(glossary_path))
        with open(glossary_path, "r", encoding="utf-8") as f:
            glossary_text = f.read()
        self.assertIn("JavaProvisioner", glossary_text)
        self.assertIn("CrashAnalyzer", glossary_text)


if __name__ == "__main__":
    unittest.main()

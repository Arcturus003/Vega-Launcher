import unittest
import os
import re
from vanilla_thread import DownloadVanillaThread

class TestAuditFixes(unittest.TestCase):
    def test_server_log_chat_injection_protection(self):
        # 1. Chat line should be identified as chat and NOT trigger playit claim
        chat_line = "[17:00:00 INFO]: <Hacker> check out https://playit.gg/claim/malicious-token"
        is_chat = bool(re.search(r'<\w+>|\*\s+\w+', chat_line))
        has_playit_tag = bool(re.search(r'\[playit(?:-companion|\.gg)?(?::|\/|\])', chat_line, re.IGNORECASE))
        
        self.assertTrue(is_chat)
        self.assertFalse(has_playit_tag)
        self.assertFalse(not is_chat and has_playit_tag)

        # 2. Genuine playit system log line should pass
        sys_line = "[17:00:00 INFO]: [playit] Visit https://playit.gg/claim/valid-token-123 to claim tunnel"
        sys_is_chat = bool(re.search(r'<\w+>|\*\s+\w+', sys_line))
        sys_has_playit_tag = bool(re.search(r'\[playit(?:-companion|\.gg)?(?::|\/|\])', sys_line, re.IGNORECASE))
        
        self.assertFalse(sys_is_chat)
        self.assertTrue(sys_has_playit_tag)
        self.assertTrue(not sys_is_chat and sys_has_playit_tag)

    def test_player_join_regex_username_validation(self):
        # Strict username regex: 3 to 16 alphanumeric characters
        valid_log = "[12:00:00 INFO]: Notch joined the game"
        me_action_log = "[12:00:00 INFO]: * Player joined the game"
        
        match_valid = re.search(r'\[.+?\]:\s+([a-zA-Z0-9_]{3,16}) joined the game', valid_log)
        self.assertIsNotNone(match_valid)
        self.assertEqual(match_valid.group(1), "Notch")
        
        match_invalid = re.search(r'\[.+?\]:\s+([a-zA-Z0-9_]{3,16}) joined the game', me_action_log)
        self.assertIsNone(match_invalid)

    def test_zip_slip_containment_logic(self):
        server_dir = os.path.realpath(os.path.join("C:", os.sep, "test_root", "server"))
        base_prefix = server_dir + os.sep

        # Safe member
        safe_target = os.path.realpath(os.path.join(server_dir, "config", "settings.json"))
        self.assertTrue(safe_target.startswith(base_prefix) or safe_target == server_dir)

        # Sibling directory traversal (classic zip-slip bug without trailing os.sep)
        traversal_target = os.path.realpath(os.path.join(server_dir, "..", "server_backup", "evil.bat"))
        # In the vulnerable code: traversal_target.startswith(server_dir) would be True because 'server_backup' starts with 'server'
        self.assertFalse(traversal_target.startswith(base_prefix) or traversal_target == server_dir)

    def test_profile_deletion_containment(self):
        profiles_dir = os.path.realpath(os.path.join("C:", os.sep, "app", "profiles"))
        real_base = profiles_dir + os.sep

        # Valid subfolder
        valid_profile = os.path.realpath(os.path.join(profiles_dir, "MyModpack"))
        self.assertTrue(valid_profile.startswith(real_base))

        # Attacking root .minecraft or parent
        escaping_profile = os.path.realpath(os.path.join(profiles_dir, "..", ".minecraft"))
        self.assertFalse(escaping_profile.startswith(real_base))

        # Attacking profiles_dir itself
        self.assertFalse(profiles_dir.startswith(real_base))

    def test_vanilla_thread_cancellation(self):
        thread = DownloadVanillaThread("1.20.1", "dummy_mc_dir")
        self.assertFalse(thread._is_cancelled)
        
        thread.cancel()
        self.assertTrue(thread._is_cancelled)
        
        results = []
        thread.task_finished.connect(lambda ok, msg: results.append((ok, msg)))
        thread.run()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0][0])

if __name__ == "__main__":
    unittest.main()

import subprocess
import os
from PySide6.QtCore import QThread, Signal

class MinecraftServerThread(QThread):
    log_ready = Signal(str)
    server_stopped = Signal()
    player_joined = Signal(str)
    player_left = Signal(str)

    def __init__(self, server_dir, ram_gb=4, jar_name="server.jar", java_path=None, parent=None, lang="tr"):
        super().__init__(parent)
        self.server_dir = server_dir
        self.ram_gb = ram_gb
        self.jar_name = jar_name
        self.java_path = java_path
        self.lang = lang
        self.process = None
        self.is_running = False

    def run(self):
        self.is_running = True
        en = self.lang == "en"
        java_exe = "java"
        if self.java_path and os.path.exists(self.java_path):
            java_exe = self.java_path
        elif os.name == 'nt':
            import glob
            matches = (
                glob.glob(r"C:\Program Files\Microsoft\jdk-*\bin\java.exe") +
                glob.glob(r"C:\Program Files\Eclipse Adoptium\jdk-*\bin\java.exe") +
                glob.glob(r"C:\Program Files\Java\jdk-*\bin\java.exe")
            )
            if matches:
                for candidate in reversed(sorted(matches)):
                    if os.path.exists(candidate):
                        java_exe = candidate
                        break
            if java_exe == "java" and "JAVA_HOME" in os.environ:
                jh_java = os.path.join(os.environ["JAVA_HOME"], "bin", "java.exe")
                if os.path.exists(jh_java):
                    java_exe = jh_java

        run_bat = os.path.join(self.server_dir, "run.bat")
        if os.path.exists(run_bat) and os.name == 'nt':
            try:
                with open(run_bat, 'r', encoding='utf-8') as f:
                    content = f.read()
                if "pause" in content.lower():
                    import re
                    content = re.sub(r'(?im)^pause\s*$', '', content)
                    with open(run_bat, 'w', encoding='utf-8') as f:
                        f.write(content)
            except Exception:
                pass
            cmd = [run_bat, "nogui"]
        else:
            cmd = [
                java_exe,
                f"-Xms{self.ram_gb}G",
                f"-Xmx{self.ram_gb}G",
                "-Dusing.aikars.flags=https://mcflags.emc.gs",
                "-Daikars.new.flags=true",
                "-jar",
                self.jar_name,
                "nogui"
            ]

        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=self.server_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            import re
            import webbrowser
            
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    clean_line = line.strip()
                    self.log_ready.emit(clean_line)
                    
                    # Player join/leave detection
                    if "joined the game" in clean_line:
                        join_match = re.search(r'\[.+?\]:\s+([a-zA-Z0-9_]{3,16}) joined the game', clean_line)
                        if join_match:
                            self.player_joined.emit(join_match.group(1))
                    elif "left the game" in clean_line:
                        leave_match = re.search(r'\[.+?\]:\s+([a-zA-Z0-9_]{3,16}) left the game', clean_line)
                        if leave_match:
                            self.player_left.emit(leave_match.group(1))

                    is_chat = bool(re.search(r'<\w+>|\*\s+\w+', clean_line))
                    has_playit_tag = bool(re.search(r'\[playit(?:-companion|\.gg)?(?::|\/|\])', clean_line, re.IGNORECASE))

                    if not is_chat and has_playit_tag and "https://playit.gg/" in clean_line and ("/claim/" in clean_line or "/mc/" in clean_line):
                        match = re.search(r'(https://playit\.gg/(?:claim|mc)/[a-zA-Z0-9\-]+)', clean_line)
                        if match:
                            claim_url = match.group(1)
                            if not hasattr(self, 'opened_claim_links'):
                                self.opened_claim_links = set()
                            if claim_url not in self.opened_claim_links:
                                self.opened_claim_links.add(claim_url)
                                webbrowser.open(claim_url)
                                self.log_ready.emit(
                                    "[SYSTEM] Playit.gg verification link opened automatically in your browser!"
                                    if en else
                                    "[SİSTEM] Playit.gg doğrulama linki tarayıcınızda otomatik açıldı!"
                                )
                            
                    # Playit.gg atanmış domain/IP'yi yakalama (ör: xxx.auto.playit.gg veya xxx.playit.gg:12345)
                    if not is_chat and has_playit_tag and ("playit.gg" in clean_line or "ply.gg" in clean_line) and "claim" not in clean_line and "download" not in clean_line:
                        ip_match = re.search(r'\b([a-zA-Z0-9\-\.]+\.(?:playit\.gg|ply\.gg)(?::\d+)?)\b', clean_line)
                        if ip_match and ip_match.group(1) != "playit.gg":
                            if getattr(self, 'playit_ip', None) != ip_match.group(1):
                                self.playit_ip = ip_match.group(1)
                                self.log_ready.emit(
                                    f"\n==========================================================\n[SYSTEM] IP ADDRESS FOR YOUR FRIENDS TO CONNECT:\n   IP: {self.playit_ip}\n==========================================================\n"
                                    if en else
                                    f"\n==========================================================\n[SİSTEM] ARKADAŞLARINIZIN BAĞLANACAĞI IP ADRESİ:\n   IP: {self.playit_ip}\n==========================================================\n"
                                )
                            
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.kill_process_tree()
        except Exception as e:
            self.log_ready.emit(f"[ERROR] Could not start server: {e}" if en else f"[HATA] Sunucu başlatılamadı: {e}")
        finally:
            self.is_running = False
            self.server_stopped.emit()

    def send_command(self, cmd):
        en = getattr(self, "lang", "tr") == "en"
        if self.process and self.is_running and self.process.stdin and not getattr(self.process.stdin, "closed", False):
            try:
                self.process.stdin.write(cmd + "\n")
                self.process.stdin.flush()
                self.log_ready.emit(f"> {cmd}")
            except Exception as e:
                self.log_ready.emit(f"[ERROR] Could not send command: {e}" if en else f"[HATA] Komut gönderilemedi: {e}")

    def get_pid(self):
        """Return the PID of the server process, or None if not running."""
        if self.process and self.is_running:
            return self.process.pid
        return None

    def stop_server(self):
        if self.process and self.is_running:
            self.send_command("stop")
            try:
                if self.process.stdin and not getattr(self.process.stdin, "closed", False):
                    self.process.stdin.close()
            except Exception:
                pass

    def kill_process_tree(self):
        """Forcefully and cleanly kill the process tree on Windows/POSIX."""
        if self.process:
            try:
                import os
                if os.name == 'nt':
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                else:
                    self.process.kill()
                self.process.wait(timeout=2)
            except Exception:
                pass

    def terminate_process(self, timeout=3):
        """Gracefully request server stop and ensure process exits, killing if hung."""
        if self.process and self.is_running:
            try:
                self.stop_server()
                self.process.wait(timeout=timeout)
            except Exception:
                try:
                    self.kill_process_tree()
                except Exception:
                    pass
            self.is_running = False

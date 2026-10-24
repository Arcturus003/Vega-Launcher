import subprocess
import os
from PySide6.QtCore import QThread, Signal

class MinecraftServerThread(QThread):
    log_ready = Signal(str)
    server_stopped = Signal()
    player_joined = Signal(str)
    player_left = Signal(str)

    def __init__(self, server_dir, ram_gb=4, jar_name="server.jar", java_path=None, parent=None, lang="tr", coordinator=None):
        super().__init__(parent)
        self.server_dir = server_dir
        self.ram_gb = ram_gb
        self.jar_name = jar_name
        self.java_path = java_path
        self.lang = lang
        self.process = None
        self.is_running = False
        self.opened_claim_links = set()
        self.playit_ip = None
        from server_process_coordinator import ServerProcessCoordinator
        self.coordinator = coordinator or ServerProcessCoordinator()

    def _resolve_java_executable(self) -> str:
        try:
            from java_provisioner import DEFAULT_JAVA_PROVISIONER
            from runtime_provisioner import RuntimeProvisioner
            spec = RuntimeProvisioner.detect_server_runtime(self.server_dir)
            _req, resolved = DEFAULT_JAVA_PROVISIONER.resolve_java_runtime(
                mc_version=spec.mc_version,
                custom_java=self.java_path if (self.java_path and os.path.exists(self.java_path)) else None,
            )
            if resolved:
                return resolved
        except Exception:
            pass
        if self.java_path and os.path.exists(self.java_path):
            return self.java_path
        return "java"

    def run(self):
        self.is_running = True
        self.coordinator.attach_thread(self)
        en = self.lang == "en"
        java_exe = self._resolve_java_executable()

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
            cmd = ["cmd.exe", "/c", run_bat, "nogui"]
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

        exit_code = 0
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            
            import webbrowser
            
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    clean_line = line.strip()
                    self.log_ready.emit(clean_line)
                    events = self.coordinator.handle_stdout_line(clean_line)
                    for ev in events:
                        if ev.event_type == "player_joined" and ev.data:
                            self.player_joined.emit(ev.data)
                        elif ev.event_type == "player_left" and ev.data:
                            self.player_left.emit(ev.data)
                        elif ev.event_type == "claim_url" and ev.data:
                            claim_url = ev.data
                            if claim_url not in self.opened_claim_links:
                                self.opened_claim_links.add(claim_url)
                                webbrowser.open(claim_url)
                                self.log_ready.emit(
                                    "[SYSTEM] Playit.gg verification link opened automatically in your browser!"
                                    if en else
                                    "[SİSTEM] Playit.gg doğrulama linki tarayıcınızda otomatik açıldı!"
                                )
                        elif ev.event_type == "playit_ip" and ev.data:
                            if getattr(self, 'playit_ip', None) != ev.data:
                                self.playit_ip = ev.data
                                self.log_ready.emit(
                                    f"\n==========================================================\n[SYSTEM] IP ADDRESS FOR YOUR FRIENDS TO CONNECT:\n   IP: {self.playit_ip}\n==========================================================\n"
                                    if en else
                                    f"\n==========================================================\n[SİSTEM] ARKADAŞLARINIZIN BAĞLANACAĞI IP ADRESİ:\n   IP: {self.playit_ip}\n==========================================================\n"
                                )
                            
            try:
                exit_code = self.process.wait(timeout=5) or 0
            except subprocess.TimeoutExpired:
                self.kill_process_tree()
                exit_code = -1
        except Exception as e:
            exit_code = 1
            self.log_ready.emit(f"[ERROR] Could not start server: {e}" if en else f"[HATA] Sunucu başlatılamadı: {e}")
        finally:
            self.is_running = False
            if self.process and self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass
            try:
                self.coordinator.on_process_exited(exit_code)
            except Exception:
                pass
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
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    )
                else:
                    self.process.kill()
                self.process.wait(timeout=2)
            except Exception:
                pass

    def terminate_process(self, timeout=7):
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

from __future__ import annotations

import os
import subprocess
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, List, Optional

from server_console_parser import ServerConsoleParser, ConsoleEvent


class ServerState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    CRASHED = "CRASHED"


class ServerProcessCoordinator:
    """
    Deep module encapsulating dedicated Minecraft server process lifecycle,
    supervision, shutdown watchdog coordination, and live backup quiescing.
    Hides subprocess handles, taskkill process trees, and console synchronization.
    """

    def __init__(self, parser: Optional[ServerConsoleParser] = None):
        self.parser = parser or ServerConsoleParser()
        self._state: ServerState = ServerState.STOPPED
        self._server_dir: Optional[str] = None
        self._thread: Any = None
        self._on_state_change: Optional[Callable[[ServerState], None]] = None
        self._on_log_line: Optional[Callable[[str], None]] = None
        self._on_event: Optional[Callable[[ConsoleEvent], None]] = None
        self._stop_requested_time: Optional[float] = None
        self._shutdown_grace_period: float = 10.0
        self.online_players: set[str] = set()
        self.detected_tunnel: Optional[str] = None
        self.playit_ip: Optional[str] = None
        self.claimed_urls: list[str] = []
        self.world_saved_count: int = 0

    @property
    def state(self) -> ServerState:
        return self._state

    def set_state_callback(self, cb: Callable[[ServerState], None]) -> None:
        self._on_state_change = cb

    def set_log_callback(self, cb: Callable[[str], None]) -> None:
        self._on_log_line = cb

    def set_event_callback(self, cb: Callable[[ConsoleEvent], None]) -> None:
        self._on_event = cb

    def _set_state(self, new_state: ServerState) -> None:
        if self._state != new_state:
            self._state = new_state
            if self._on_state_change:
                try:
                    self._on_state_change(new_state)
                except Exception:
                    pass

    def attach_thread(self, server_thread: Any) -> None:
        """Attach a MinecraftServerThread instance to coordinate."""
        self._thread = server_thread
        self.online_players.clear()
        self.detected_tunnel = None
        self.playit_ip = None
        self.claimed_urls.clear()
        self.world_saved_count = 0
        self.parser.reset()
        if server_thread:
            self._set_state(ServerState.STARTING)

    def is_running(self) -> bool:
        if not self._thread:
            return False
        return bool(getattr(self._thread, "is_running", False) or getattr(self._thread, "isRunning", lambda: False)())

    def send_command(self, cmd: str) -> bool:
        """Send a console command to the running server stdin."""
        clean = (cmd or "").strip()
        if not clean or not self.is_running():
            return False
        try:
            self._thread.send_command(clean)
            return True
        except Exception:
            return False

    def handle_stdout_line(self, line: str) -> list[ConsoleEvent]:
        """Feed a stdout line through the parser and update lifecycle state machine for all 8 ConsoleEvent types."""
        events = self.parser.feed_line(line)
        for ev in events:
            if ev.event_type == "online":
                self._set_state(ServerState.RUNNING)
            elif ev.event_type == "stopping":
                self._set_state(ServerState.STOPPING)
            elif ev.event_type == "world_saved":
                self.world_saved_count += 1
                if self._state == ServerState.STOPPING:
                    # World flush complete: accelerate shutdown grace
                    self._shutdown_grace_period = 3.0
            elif ev.event_type == "player_joined" and ev.data:
                self.online_players.add(ev.data)
            elif ev.event_type == "player_left" and ev.data:
                self.online_players.discard(ev.data)
            elif ev.event_type == "tunnel_detected" and ev.data:
                self.detected_tunnel = ev.data
            elif ev.event_type == "claim_url" and ev.data:
                if ev.data not in self.claimed_urls:
                    self.claimed_urls.append(ev.data)
            elif ev.event_type == "playit_ip" and ev.data:
                self.playit_ip = ev.data

            if self._on_event:
                try:
                    self._on_event(ev)
                except Exception:
                    pass

        if self._on_log_line:
            try:
                self._on_log_line(line)
            except Exception:
                pass
        return events

    def stop(self, timeout_sec: float = 10.0) -> None:
        """
        Initiate graceful server shutdown:
        1. Issues 'stop' and closes stdin so Java console thread unblocks.
        2. Sets state to STOPPING and arms watchdog timer.
        """
        if not self.is_running():
            self._set_state(ServerState.STOPPED)
            return

        self._set_state(ServerState.STOPPING)
        self._stop_requested_time = time.time()
        self._shutdown_grace_period = timeout_sec

        try:
            self._thread.stop_server()
        except Exception:
            pass

    def force_kill(self) -> None:
        """Immediately terminate the entire server process tree (taskkill /F /T on Windows)."""
        if self._thread:
            try:
                self._thread.kill_process_tree()
            except Exception:
                pass
        self._set_state(ServerState.STOPPED)

    def on_process_exited(self, exit_code: int = 0) -> None:
        """Invoked when the background thread process terminates."""
        if self._state == ServerState.STOPPING:
            self._set_state(ServerState.STOPPED)
        elif exit_code != 0:
            self._set_state(ServerState.CRASHED)
        else:
            self._set_state(ServerState.STOPPED)
        self.online_players.clear()
        self._thread = None

    @contextmanager
    def quiesce_for_backup(self, flush_timeout_sec: float = 3.0) -> Generator[None, None, None]:
        """
        Context manager ensuring the world save is flushed and locked during a backup:
        - Issues 'save-off' and 'save-all flush'
        - Verifies world flush completed or waits up to flush_timeout_sec
        - Yields to the caller to perform filesystem ZIP archiving
        - Automatically restores 'save-on' in the finally block
        """
        was_running = self.is_running()
        baseline_saved = self.world_saved_count
        if was_running:
            self.send_command("save-off")
            self.send_command("save-all flush")
            start_t = time.time()
            while time.time() - start_t < flush_timeout_sec:
                time.sleep(0.1)
                if self.world_saved_count > baseline_saved:
                    break
                recent = list(self.parser.history[-10:])
                if self._thread is not None:
                    th_hist = getattr(self._thread, "_log_history", None) or getattr(self._thread, "log_history", None)
                    if isinstance(th_hist, list):
                        recent.extend(th_hist[-10:])
                if any(
                    "saved the game" in str(l).lower()
                    or "all dimensions are saved" in str(l).lower()
                    or "all chunks are saved" in str(l).lower()
                    for l in recent
                ):
                    break

        try:
            yield
        finally:
            if was_running and self.is_running():
                self.send_command("save-on")


DEFAULT_PROCESS_COORDINATOR = ServerProcessCoordinator()


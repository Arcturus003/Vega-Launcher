from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ConsoleEvent:
    event_type: str  # "online", "stopping", "world_saved", "player_joined", "player_left", "tunnel_detected", "claim_url", "playit_ip"
    data: Optional[str] = None
    raw: str = ""


class ServerConsoleParser:
    """
    Deep in-process stream parser for Minecraft dedicated server stdout logs.
    Decouples regex scanning, game lifecycle events, tunnel discoveries,
    and HTML coloring from Qt UI widgets.
    """

    RE_TUNNEL = re.compile(r'([a-zA-Z0-9.-]+\.(?:gl\.joinmc\.link|ply\.gg)(?::\d+)?)')
    RE_PLAYER_JOIN = re.compile(r'\[.+?\]:\s+([a-zA-Z0-9_]{3,16}) joined the game')
    RE_PLAYER_LEAVE = re.compile(r'\[.+?\]:\s+([a-zA-Z0-9_]{3,16}) left the game')
    RE_PLAYIT_CLAIM = re.compile(r'(https://playit\.gg/(?:claim|mc)/[a-zA-Z0-9\-]+)')
    RE_PLAYIT_IP = re.compile(r'\b([a-zA-Z0-9\-\.]+\.(?:playit\.gg|ply\.gg)(?::\d+)?)\b')
    RE_CHAT = re.compile(r'<\w+>|\*\s+\w+')
    RE_PLAYIT_TAG = re.compile(r'\[playit(?:-companion|\.gg)?(?::|\/|\])', re.IGNORECASE)

    def __init__(self, max_history: int = 2000):
        self.max_history = max_history
        self._history: list[str] = []
        self._opened_claim_links: set[str] = set()
        self._last_detected_ip: Optional[str] = None

    @property
    def history(self) -> list[str]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()

    def reset(self) -> None:
        """Reset parser history and state."""
        self.clear_history()
        self._opened_claim_links.clear()
        self._last_detected_ip = None

    @staticmethod
    def classify_log_level(text: str) -> str:
        """Classify message level for filtering: ERROR, WARN, INFO, or NORMAL."""
        upper = text.upper()
        if "ERROR" in upper or "[HATA]" in upper or "FATAL" in upper or "EXCEPTION" in upper or "CRITICAL" in upper:
            return "ERROR"
        if "WARN" in upper or "[UYARI]" in upper:
            return "WARN"
        if "INFO" in upper or "[BİLGİ]" in upper or "[BILGI]" in upper:
            return "INFO"
        return "NORMAL"

    @staticmethod
    def format_html(text: str) -> str:
        """Render raw console line as colored HTML for Qt text widgets."""
        escaped_text = html.escape(text)
        lvl = ServerConsoleParser.classify_log_level(text)
        if lvl == "ERROR":
            color = "#EF4444"  # bright red
        elif lvl == "WARN":
            color = "#F59E0B"  # amber
        elif lvl == "INFO":
            color = "#D4D4D8"  # light zinc
        else:
            color = "#F4F4F5"  # white zinc
        return f'<span style="color: {color}; white-space: pre-wrap;">{escaped_text}</span>'

    def feed_line(self, line: str) -> list[ConsoleEvent]:
        """
        Process a single stdout line, record history, and return any detected domain events.
        """
        clean = line.strip()
        if not clean:
            return []

        self._history.append(clean)
        if len(self._history) > self.max_history:
            self._history = self._history[-self.max_history:]

        events: list[ConsoleEvent] = []

        # 1. Server Online detection
        if "Done (" in clean or 'For help, type "help"' in clean:
            events.append(ConsoleEvent(event_type="online", raw=clean))

        # 2. Server Shutdown detection
        if "Stopping the server" in clean or "Stopping server" in clean:
            events.append(ConsoleEvent(event_type="stopping", raw=clean))

        # 3. World / Chunk save completion (safe to kill hung background mod threads)
        if "All chunks are saved" in clean or "All dimensions are saved" in clean:
            events.append(ConsoleEvent(event_type="world_saved", raw=clean))

        # 4. Player Join / Leave detection
        join_m = self.RE_PLAYER_JOIN.search(clean)
        if join_m:
            events.append(ConsoleEvent(event_type="player_joined", data=join_m.group(1), raw=clean))
        else:
            leave_m = self.RE_PLAYER_LEAVE.search(clean)
            if leave_m:
                events.append(ConsoleEvent(event_type="player_left", data=leave_m.group(1), raw=clean))

        # 5. Tunnel address detection (joinmc.link, ply.gg, etc.)
        m_tunnel = self.RE_TUNNEL.search(clean)
        if m_tunnel:
            events.append(ConsoleEvent(event_type="tunnel_detected", data=m_tunnel.group(1), raw=clean))

        # 6. Playit.gg companion link & IP detection
        is_chat = bool(self.RE_CHAT.search(clean))
        has_playit_tag = bool(self.RE_PLAYIT_TAG.search(clean))

        if not is_chat and has_playit_tag:
            if "https://playit.gg/" in clean and ("/claim/" in clean or "/mc/" in clean):
                claim_m = self.RE_PLAYIT_CLAIM.search(clean)
                if claim_m:
                    claim_url = claim_m.group(1)
                    if claim_url not in self._opened_claim_links:
                        self._opened_claim_links.add(claim_url)
                        events.append(ConsoleEvent(event_type="claim_url", data=claim_url, raw=clean))

            if ("playit.gg" in clean or "ply.gg" in clean) and "claim" not in clean and "download" not in clean:
                ip_m = self.RE_PLAYIT_IP.search(clean)
                if ip_m and ip_m.group(1) != "playit.gg":
                    candidate_ip = ip_m.group(1)
                    if candidate_ip != self._last_detected_ip:
                        self._last_detected_ip = candidate_ip
                        events.append(ConsoleEvent(event_type="playit_ip", data=candidate_ip, raw=clean))

        return events

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from PySide6.QtCore import QThread, Signal

# Default Prism Meta URL for Minecraft package index
MINECRAFT_INDEX_URL = "https://meta.prismlauncher.org/v1/net.minecraft/index.json"

# Built-in fallback releases when offline and no local cache exists
FALLBACK_VERSIONS: List[Dict[str, str]] = [
    {"version": "1.21.4", "type": "release"},
    {"version": "1.21.3", "type": "release"},
    {"version": "1.21.1", "type": "release"},
    {"version": "1.21", "type": "release"},
    {"version": "1.20.6", "type": "release"},
    {"version": "1.20.4", "type": "release"},
    {"version": "1.20.2", "type": "release"},
    {"version": "1.20.1", "type": "release"},
    {"version": "1.19.4", "type": "release"},
    {"version": "1.19.2", "type": "release"},
    {"version": "1.18.2", "type": "release"},
    {"version": "1.17.1", "type": "release"},
    {"version": "1.16.5", "type": "release"},
    {"version": "1.12.2", "type": "release"},
    {"version": "1.8.9", "type": "release"},
    {"version": "1.7.10", "type": "release"},
    {"version": "b1.7.3", "type": "old_beta"},
    {"version": "a1.2.6", "type": "old_alpha"},
]


class PrismMetaProvider:
    """
    Service that fetches, caches, and filters Minecraft versions and mod loader
    compatibilities using Prism Launcher's official Meta API (meta.prismlauncher.org).
    """

    def __init__(self, cache_dir: Optional[str] = None):
        base_dir = cache_dir or os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~"), ".vega_launcher"
        )
        self.cache_file = os.path.join(base_dir, "meta_cache.json")
        self._memory_cache: Optional[List[Dict[str, str]]] = None

    def load_cached_versions(self) -> List[Dict[str, str]]:
        """Load versions from memory, local JSON disk cache, or fallback list."""
        if self._memory_cache:
            return self._memory_cache

        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        self._memory_cache = data
                        return self._memory_cache
            except Exception:
                pass

        self._memory_cache = list(FALLBACK_VERSIONS)
        return self._memory_cache

    def save_cached_versions(self, versions: List[Dict[str, str]]) -> None:
        """Persist fetched versions list to local JSON disk cache."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.cache_file)), exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(versions, f, indent=2)
            self._memory_cache = versions
        except Exception as e:
            print(f"[PrismMeta] Cache save error: {e}")

    def fetch_live_versions(self, timeout: float = 6.0) -> List[Dict[str, str]]:
        """Fetch fresh versions index from Prism Meta API and update cache."""
        headers = {"User-Agent": "VegaLauncher/2.0"}
        resp = requests.get(MINECRAFT_INDEX_URL, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Prism Meta API error HTTP {resp.status_code}")

        data = resp.json()
        raw_versions = data.get("versions", [])
        clean_list: List[Dict[str, str]] = []

        for item in raw_versions:
            ver = item.get("version")
            v_type = item.get("type", "release")
            if ver:
                clean_list.append({"version": str(ver), "type": str(v_type)})

        if clean_list:
            self.save_cached_versions(clean_list)
            return clean_list

        return self.load_cached_versions()

    def filter_versions(
        self,
        show_snapshots: bool = False,
        show_old: bool = False,
        local_versions: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Filters Minecraft versions based on user checkboxes:
        - Releases are always included.
        - show_snapshots includes 'snapshot' and 'old_snapshot'.
        - show_old includes 'old_beta' and 'old_alpha'.
        - Merges any local installed versions from disk.
        """
        all_meta = self.load_cached_versions()
        filtered: List[str] = []

        allowed_types = {"release"}
        if show_snapshots:
            allowed_types.update({"snapshot", "old_snapshot", "experiment"})
        if show_old:
            allowed_types.update({"old_beta", "old_alpha"})

        for item in all_meta:
            v_type = item.get("type", "release")
            v_name = item.get("version")
            if v_name and v_type in allowed_types:
                if v_name not in filtered:
                    filtered.append(v_name)

        if local_versions:
            for lv in local_versions:
                if lv not in filtered:
                    filtered.insert(0, lv)

        return filtered

    @staticmethod
    def get_compatible_loaders(mc_version: str, lang: str = "tr") -> List[Tuple[str, str]]:
        """
        Determines which mod loaders are compatible with the specified Minecraft version.
        Returns a list of (display_label, loader_key) tuples.
        """
        en = (lang == "en")
        loaders: List[Tuple[str, str]] = []

        # Parse version
        clean_v = (mc_version or "").strip().lower()

        # Nostalgic Alpha / Beta
        if clean_v.startswith(("a", "b")) and any(c.isdigit() for c in clean_v):
            return [("Vanilla (Saf Minecraft)" if not en else "Vanilla (Pure Minecraft)", "vanilla")]

        match = re.search(r"^(\d+)\.(\d+)(?:\.(\d+))?", clean_v)
        major = int(match.group(1)) if match else 1
        minor = int(match.group(2)) if match else 20
        patch = int(match.group(3)) if (match and match.group(3)) else 0

        # Fabric (Minecraft 1.14+)
        if (major == 1 and minor >= 14) or major > 1:
            loaders.append(("Fabric (Önerilen)" if not en else "Fabric (Recommended)", "fabric"))

        # NeoForge (Minecraft 1.20+)
        if (major == 1 and minor >= 20) or major > 1:
            loaders.append(("NeoForge (1.20.2+)", "neoforge"))

        # Forge (Minecraft 1.1+)
        if major == 1:
            loaders.append(("Forge", "forge"))

        # Quilt (Minecraft 1.14+)
        if (major == 1 and minor >= 14) or major > 1:
            loaders.append(("Quilt", "quilt"))

        # Vanilla is always available
        loaders.append(("Vanilla (Saf Minecraft)" if not en else "Vanilla (Pure Minecraft)", "vanilla"))

        return loaders


class MetaFetchWorker(QThread):
    """Background QThread that queries Prism Meta without freezing the UI."""
    versions_ready = Signal(list)
    fetch_failed = Signal(str)

    def __init__(self, provider: PrismMetaProvider, parent=None):
        super().__init__(parent)
        self.provider = provider

    def run(self):
        try:
            versions = self.provider.fetch_live_versions(timeout=6.0)
            self.versions_ready.emit(versions)
        except Exception as e:
            self.fetch_failed.emit(str(e))


DEFAULT_META_PROVIDER = PrismMetaProvider()

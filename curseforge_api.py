from __future__ import annotations

import base64
import os
import re
import html
from typing import Optional, Sequence
import requests

_DEFAULT_CF_KEY = base64.b64decode("JDJhJDEwJHd1QUp1Tlp1dGVkM05PUlZtcGdVQy5tOHNJLnB2MXRPUEtaeUJnTEZHanhGcC9icjBsWkND").decode("ascii")
API_KEY = os.environ.get("CURSEFORGE_API_KEY", _DEFAULT_CF_KEY)
BASE_URL = "https://api.curseforge.com/v1"
GAME_ID = 432  # Minecraft

CLASS_IDS = {
    "mod": 6,
    "modpack": 4471,
    "shader": 6552,
    "resourcepack": 12,
}

LOADER_IDS = {
    "forge": 1,
    "fabric": 4,
    "quilt": 5,
    "neoforge": 6,
}

SORT_FIELDS = {
    "relevance": 2,      # Popularity (CurseForge standard sort)
    "popularity": 2,     # Popularity
    "downloads": 6,      # TotalDownloads (Fixed: was 5 which is Author)
    "updated": 3,        # LastUpdated
    "newest": 11,        # ReleasedDate (Fixed: was 2 which is Popularity)
    "name": 4,           # Name
    "author": 5,         # Author
}

CATEGORY_MAPS = {
    "modpack": {
        "optimization": 4481,  # Small / Light
        "adventure": 4475,     # Adventure and RPG
        "technology": 4472,    # Tech
        "lightweight": 5128,   # Vanilla+
    },
    "mod": {
        "optimization": 6814,  # Performance
        "adventure": 422,      # Adventure and RPG
        "technology": 412,     # Technology
        "lightweight": 5191,   # Utility & QoL
    },
}


class CurseForgeAPI:
    """
    CurseForge Core / Eternal API client duck-typed to match ModrinthAPI interface
    for seamless pluggability into ContentCatalog and UI browser widgets.
    """
    _session: Optional[requests.Session] = None

    @classmethod
    def get_session(cls) -> requests.Session:
        if cls._session is None:
            cls._session = requests.Session()
            cls._session.headers.update({
                "x-api-key": API_KEY,
                "User-Agent": "VegaLauncher/2.0.0",
                "Accept": "application/json",
            })
        return cls._session

    @classmethod
    def _get(cls, url: str, **kwargs) -> requests.Response:
        sess = cls.get_session()
        return sess.get(url, **kwargs)

    @classmethod
    def search_projects(
        cls,
        query: str = "",
        project_type: str = "mod",
        index: str = "relevance",
        limit: int = 24,
        version: Optional[str] = None,
        loader: Optional[str | Sequence[str]] = None,
        category: Optional[str] = None,
    ) -> list[dict]:
        url = f"{BASE_URL}/mods/search"
        class_id = CLASS_IDS.get(project_type, 6)
        sort_field = SORT_FIELDS.get(index, 1)

        params: dict = {
            "gameId": GAME_ID,
            "classId": class_id,
            "pageSize": min(limit, 50),
            "sortField": sort_field,
            "sortOrder": "desc",
        }

        if query and query.strip():
            params["searchFilter"] = query.strip()

        if version and version not in ("all", "detect"):
            params["gameVersion"] = version

        if loader and project_type != "shader":
            eff_loader = loader[0] if isinstance(loader, (list, tuple)) else str(loader)
            ldr_key = str(eff_loader).lower()
            if ldr_key in LOADER_IDS:
                params["modLoaderType"] = LOADER_IDS[ldr_key]

        cat_map = CATEGORY_MAPS.get(project_type, CATEGORY_MAPS["modpack"])
        if category and category in cat_map:
            params["categoryId"] = cat_map[category]

        try:
            r = cls._get(url, params=params, timeout=12)
            r.raise_for_status()
            data = r.json().get("data", [])
        except Exception as e:
            print(f"[CurseForgeAPI] search_projects error: {e}")
            return []

        results = []
        for m in data:
            mid = str(m["id"])
            authors = m.get("authors") or []
            author_name = authors[0].get("name", "") if authors else ""
            logo = m.get("logo") or {}
            icon_url = logo.get("url") or logo.get("thumbnailUrl") or ""

            # Extract distinct game versions from latestFilesIndexes and sort semantically
            versions = []
            for fi in m.get("latestFilesIndexes", []):
                gv = fi.get("gameVersion")
                if gv and gv not in versions:
                    versions.append(gv)

            def _parse_v(v_str: str):
                nums = re.findall(r'\d+', str(v_str))
                return [int(x) for x in nums[:3]] if nums else [0]

            versions.sort(key=_parse_v)

            categories = [c.get("name") for c in m.get("categories", []) if c.get("name")]
            slug = m.get("slug") or str(mid)

            results.append({
                "id": mid,
                "project_id": mid,
                "slug": slug,
                "title": m.get("name") or "Untitled",
                "author": author_name,
                "description": m.get("summary") or "",
                "downloads": m.get("downloadCount") or 0,
                "follows": m.get("thumbsUpCount") or 0,
                "icon_url": icon_url,
                "versions": versions,
                "categories": categories,
                "project_type": project_type,
                "source": "curseforge",
                "website_url": (m.get("links") or {}).get("websiteUrl") or f"https://www.curseforge.com/minecraft/{'mc-mods' if project_type == 'mod' else 'modpacks'}/{slug}",
                "client_side": "optional",
            })
        return results

    @classmethod
    def get_project_details(cls, project_id: str) -> Optional[dict]:
        url = f"{BASE_URL}/mods/{project_id}"
        try:
            r = cls._get(url, timeout=12)
            r.raise_for_status()
            m = r.json().get("data", {})
            if not m:
                return None
        except Exception as e:
            print(f"[CurseForgeAPI] get_project_details error: {e}")
            return None

        mid = str(m["id"])
        authors = m.get("authors") or []
        author_name = authors[0].get("name", "") if authors else ""
        logo = m.get("logo") or {}
        icon_url = logo.get("url") or logo.get("thumbnailUrl") or ""
        slug = m.get("slug") or str(mid)

        gallery = []
        for s in m.get("screenshots", []):
            u = s.get("url") or s.get("thumbnailUrl")
            if u:
                gallery.append({"url": u, "title": s.get("title", "")})

        # Fetch full description if summary is short
        desc = m.get("summary") or ""
        try:
            desc_r = cls._get(f"{BASE_URL}/mods/{project_id}/description", timeout=8)
            if desc_r.status_code == 200:
                raw_html = desc_r.json().get("data", "")
                if raw_html:
                    clean_text = re.sub(r'<[^>]+>', ' ', raw_html)
                    clean_text = html.unescape(clean_text)
                    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                    if clean_text:
                        desc = clean_text[:600]
        except Exception:
            pass

        return {
            "id": mid,
            "project_id": mid,
            "slug": slug,
            "title": m.get("name") or "Untitled",
            "author": author_name,
            "description": desc,
            "downloads": m.get("downloadCount") or 0,
            "follows": m.get("thumbsUpCount") or 0,
            "icon_url": icon_url,
            "gallery": gallery,
            "website_url": (m.get("links") or {}).get("websiteUrl") or f"https://www.curseforge.com/minecraft/mc-mods/{slug}",
            "source": "curseforge",
        }

    @classmethod
    def get_project_versions(
        cls,
        project_id: str,
        game_version: Optional[str] = None,
        loader: Optional[str | Sequence[str]] = None,
    ) -> list[dict]:
        url = f"{BASE_URL}/mods/{project_id}/files"
        params: dict = {"pageSize": 35}

        if game_version and game_version not in ("all", "detect"):
            params["gameVersion"] = game_version

        if loader:
            eff_loader = loader[0] if isinstance(loader, (list, tuple)) else str(loader)
            ldr_key = str(eff_loader).lower()
            if ldr_key in LOADER_IDS:
                params["modLoaderType"] = LOADER_IDS[ldr_key]

        try:
            r = cls._get(url, params=params, timeout=12)
            r.raise_for_status()
            raw_files = r.json().get("data", [])
        except Exception as e:
            print(f"[CurseForgeAPI] get_project_versions error: {e}")
            return []

        versions = []
        for f in raw_files:
            fid = f["id"]
            fname = f.get("fileName") or f"file-{fid}.jar"
            dl_url = f.get("downloadUrl")
            if not dl_url:
                # Direct Forge CDN convention
                dl_url = f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/{fname}"

            g_vers = [v for v in f.get("gameVersions", []) if re.match(r'^\d+\.\d+', v)]
            loaders = [v.lower() for v in f.get("gameVersions", []) if v.lower() in ("forge", "fabric", "quilt", "neoforge")]

            versions.append({
                "id": str(fid),
                "project_id": str(project_id),
                "name": f.get("displayName") or fname,
                "version_number": f.get("displayName") or fname,
                "game_versions": g_vers,
                "loaders": loaders,
                "download_url": dl_url,
                "is_available": f.get("isAvailable", True),
                "files": [{
                    "filename": fname,
                    "url": dl_url,
                    "primary": True,
                    "size": f.get("fileLength", 0),
                }]
            })
        return versions

    @classmethod
    def get_latest_version_file(
        cls,
        project_id: str,
        game_version: Optional[str] = None,
        loader: Optional[str | Sequence[str]] = None,
    ) -> Optional[dict]:
        versions = cls.get_project_versions(project_id, game_version=game_version, loader=loader)
        if not versions:
            return None
        v = versions[0]
        files = v.get("files", [])
        if not files:
            return None
        res = dict(files[0])
        res["version_id"] = v.get("id")
        return res

    @classmethod
    def get_file_download_url(cls, project_id: str | int, file_id: str | int) -> Optional[str]:
        """Query official API for authenticated direct download URL."""
        url = f"{BASE_URL}/mods/{project_id}/files/{file_id}/download-url"
        try:
            r = cls._get(url, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data")
                if data and isinstance(data, str) and data.startswith("http"):
                    return data
        except Exception:
            pass
        return None

    @classmethod
    def download_file(cls, url: str, dest_path: str) -> bool:
        """Download file with support for redirects to Forge CDN mirrors."""
        part_path = f"{dest_path}.part"
        try:
            r = requests.get(
                url,
                headers={"User-Agent": "VegaLauncher/2.0.0"},
                stream=True,
                timeout=30,
                allow_redirects=True,
            )
            r.raise_for_status()
            with open(part_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if os.path.exists(dest_path):
                os.remove(dest_path)
            os.replace(part_path, dest_path)
            return True
        except Exception as e:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass
            print(f"[CurseForgeAPI] download_file error: {e}")
            return False

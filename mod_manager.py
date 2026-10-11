import requests
import json

class ModrinthAPI:
    BASE_URL = "https://api.modrinth.com/v2"

    @staticmethod
    def search_projects(query, project_type="mod", index="relevance", limit=12, version=None, loader=None):
        url = f"{ModrinthAPI.BASE_URL}/search"
        facets = [
            [f"project_type:{project_type}"]
        ]
        if version:
            facets.append([f"versions:{version}"])
        if loader:
            if isinstance(loader, (list, tuple)):
                facets.append([f"categories:{l.lower()}" for l in loader])
            elif loader.lower() == "quilt":
                facets.append(["categories:quilt", "categories:fabric"])
            else:
                facets.append([f"categories:{loader.lower()}"])
            
        params = {
            "query": query,
            "index": index,
            "limit": limit,
            "facets": json.dumps(facets)
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("hits", [])
        except Exception as e:
            print(f"Modrinth API Hatası: {e}")
            return None

    @staticmethod
    def get_project_details(project_id):
        url = f"{ModrinthAPI.BASE_URL}/project/{project_id}"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Modrinth Project API Hatası: {e}")
            return None

    @staticmethod
    def get_latest_version_file(project_id, game_version=None, loader=None):
        url = f"{ModrinthAPI.BASE_URL}/project/{project_id}/version"
        params = {}
        if game_version:
            params["game_versions"] = json.dumps([game_version])
        if loader:
            if isinstance(loader, (list, tuple)):
                params["loaders"] = json.dumps([l.lower() for l in loader])
            elif loader.lower() == "quilt":
                params["loaders"] = json.dumps(["quilt", "fabric"])
            else:
                params["loaders"] = json.dumps([loader.lower()])

        try:
            response = requests.get(url, params=params if params else None, timeout=15)
            response.raise_for_status()
            versions = response.json()
            
            if game_version:
                versions = [v for v in versions if game_version in v.get("game_versions", [])]
            if loader:
                if isinstance(loader, (list, tuple)):
                    req_loaders = [l.lower() for l in loader]
                elif loader.lower() == "quilt":
                    req_loaders = ["quilt", "fabric"]
                else:
                    req_loaders = [loader.lower()]
                versions = [
                    v for v in versions
                    if any(rl in [l.lower() for l in v.get("loaders", [])] for rl in req_loaders)
                ]
            
            if not versions:
                return None
                
            latest_version = versions[0]
            files = latest_version.get("files", [])
            
            if not files:
                return None
                
            for f in files:
                if f.get("primary"):
                    f["version_id"] = latest_version.get("id")
                    return f
            files[0]["version_id"] = latest_version.get("id")
            return files[0]
            
        except Exception as e:
            print(f"Modrinth Version API Hatası: {e}")
            return None

    @staticmethod
    def download_file(url, dest_path):
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"İndirme Hatası: {e}")
            return False

import os
import re
from PySide6.QtCore import QThread, Signal

def detect_profile_loader(pdata):
    if not pdata or not isinstance(pdata, dict):
        return None
    loader_val = pdata.get("loader")
    if loader_val:
        return str(loader_val).lower()
    ver = str(pdata.get("version") or "").lower()
    for known in ["neoforge", "fabric", "quilt", "forge"]:
        if known in ver:
            return known
    prof_path = pdata.get("path") or ""
    if prof_path and os.path.isdir(prof_path):
        mods_dir = os.path.join(prof_path, "mods")
        if os.path.isdir(mods_dir):
            try:
                files = [f.lower() for f in os.listdir(mods_dir) if f.endswith(".jar")]
                neo_cnt = sum(1 for f in files if "neoforge" in f)
                fab_cnt = sum(1 for f in files if "fabric" in f)
                quilt_cnt = sum(1 for f in files if "quilt" in f)
                forge_cnt = sum(1 for f in files if "forge" in f and "neoforge" not in f)
                counts = {"neoforge": neo_cnt, "fabric": fab_cnt, "quilt": quilt_cnt, "forge": forge_cnt}
                top_loader = max(counts, key=counts.get)
                if counts[top_loader] > 0:
                    return top_loader
            except Exception:
                pass
    return None

def detect_profile_game_version(pdata):
    if not pdata or not isinstance(pdata, dict):
        return None
    ver = str(pdata.get("game_version") or "")
    if ver:
        return ver
    ver_str = str(pdata.get("version") or "")
    match = re.search(r'(?<![\d\.])(1\.(?:[7-9]|\d{2})(?:\.\d+)?)(?![\d\.])', ver_str)
    return match.group(1) if match else None

class UpdateCheckerThread(QThread):
    # profile_id, new_version_id, new_file_url
    update_available = Signal(str, str, str)
    
    def __init__(self, profiles):
        super().__init__()
        self.profiles_snapshot = list(profiles.items())
        self._is_running = True

    def stop(self):
        self._is_running = False
        
    def run(self):
        try:
            for profile_id, pdata in self.profiles_snapshot:
                if not self._is_running:
                    break
                project_id = pdata.get("project_id")
                current_version_id = pdata.get("version_id")
                
                if project_id and current_version_id:
                    loader = detect_profile_loader(pdata)
                    game_version = detect_profile_game_version(pdata)
                    
                    latest_file = None
                    if loader and game_version:
                        latest_file = ModrinthAPI.get_latest_version_file(
                            project_id, game_version=game_version, loader=loader
                        )
                    elif loader:
                        latest_file = ModrinthAPI.get_latest_version_file(
                            project_id, loader=loader
                        )
                    elif game_version:
                        latest_file = ModrinthAPI.get_latest_version_file(
                            project_id, game_version=game_version
                        )
                    else:
                        latest_file = ModrinthAPI.get_latest_version_file(project_id)

                    if not self._is_running:
                        break
                    if latest_file:
                        latest_version_id = latest_file.get("version_id")
                        if latest_version_id and latest_version_id != current_version_id:
                            self.update_available.emit(profile_id, latest_version_id, latest_file.get("url", ""))
        except Exception as e:
            print(f"UpdateCheckerThread Hatası: {e}")

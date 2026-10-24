import hashlib
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FILES_TO_CHECK = [
    "main.py",
    "server_widget.py",
    "card_widget.py",
    "mod_manager.py",
    "engine_installer.py",
    "playtime_tracker.py",
    "vanilla_thread.py",
    "auth_window.py",
    "server_thread.py",
    "ui_components.py",
    "server_downloader.py",
    "app_updater.py",
    "sound_manager.py",
    "particle_overlay.py",
    "theme_manager.py",
    "runtime_provisioner.py",
    "profile_store.py",
    "server_instance.py",
    "backup_manager.py",
    "vega_mcp_server.py",
    "legacy_mcp_server.py",
    "launch_pipeline.py",
    "server_console_parser.py",
    "auth_vault.py",
    "server_process_coordinator.py",
    "prism_meta_provider.py",
    "prism_instance_importer.py",
    "curseforge_api.py",
    "crash_analyzer.py",
    "java_provisioner.py",
    "content_browser.py"
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INTEGRITY_FILE = os.path.join(BASE_DIR, ".integrity")
def calculate_file_hash(filepath):
    if not os.path.exists(filepath):
        return None
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        content = f.read()
        # Normalize CRLF to LF so integrity check is deterministic across Git checkouts and platforms
        content = content.replace(b"\r\n", b"\n")
        sha256_hash.update(content)
    return sha256_hash.hexdigest()

def generate_hashes():
    hashes = {}
    for filename in FILES_TO_CHECK:
        abs_path = os.path.join(BASE_DIR, filename)
        file_hash = calculate_file_hash(abs_path)
        if file_hash:
            hashes[filename] = file_hash
    with open(INTEGRITY_FILE, "w", encoding="utf-8") as f:
        json.dump(hashes, f, indent=4)
    print(f"Hashes generated and saved to {INTEGRITY_FILE}")

def verify_integrity():
    import sys
    if getattr(sys, 'frozen', False):
        # When running as a compiled .exe (PyInstaller/Nuitka), the raw .py files 
        # do not exist to be hashed. The code is already packed inside the executable.
        return True, []
        
    if not os.path.exists(INTEGRITY_FILE):
        print("[BÜTÜNLÜK HATASI] .integrity dosyası bulunamadı!")
        print("Çözüm: Bütünlük hash'lerini oluşturmak için 'python integrity_check.py generate' çalıştırın.")
        return False, ["<missing_integrity_file>"]
    
    try:
        with open(INTEGRITY_FILE, "r", encoding="utf-8") as f:
            expected_hashes = json.load(f)
        if not isinstance(expected_hashes, dict):
            raise ValueError(".integrity must contain a JSON object")
    except Exception as e:
        print(f"[BÜTÜNLÜK HATASI] .integrity dosyası okunamadı veya bozuk: {e}")
        print("Çözüm: 'python integrity_check.py generate' çalıştırarak yeniden oluşturun.")
        return False, ["<invalid_integrity_file>"]
        
    tampered_files = []
    for filename in FILES_TO_CHECK:
        if filename not in expected_hashes:
            tampered_files.append(f"{filename} (eksik hash)")
            continue
        abs_path = os.path.join(BASE_DIR, filename)
        current_hash = calculate_file_hash(abs_path)
        if current_hash is None or current_hash != expected_hashes[filename]:
            tampered_files.append(filename)
    
    if tampered_files:
        print("[BÜTÜNLÜK HATASI] Bütünlük doğrulaması başarısız oldu! Uyuşmayan/eksik dosyalar:")
        for tf in tampered_files:
            print(f"  - {tf}")
        print("Çözüm: Dosyalarda değişiklik yaptıysanız bütünlüğü güncellemek için:")
        print("  python integrity_check.py generate")
        return False, tampered_files
    return True, []

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        generate_hashes()
    else:
        is_ok, tampered = verify_integrity()
        if is_ok:
            print("Integrity check passed.")
        else:
            sys.exit(1)

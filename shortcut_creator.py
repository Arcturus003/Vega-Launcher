import os
import sys
import subprocess

def create_desktop_shortcut():
    try:
        desktop_dir = os.path.join(os.environ["USERPROFILE"], "Desktop")
        shortcut_path = os.path.join(desktop_dir, "Vega Launcher.lnk")
        
        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            target_path = sys.executable
            arguments_line = ""
            work_dir = os.path.dirname(sys.executable)
            icon_candidate = os.path.join(work_dir, "icon.ico")
            icon_path = icon_candidate if os.path.exists(icon_candidate) else sys.executable
        else:
            target_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
            target_path = sys.executable.replace("python.exe", "pythonw.exe")
            arguments_line = f'oLink.Arguments = chr(34) & "{target_script}" & chr(34)'
            work_dir = os.path.dirname(target_script)
            icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "icon.ico"))
        
        vbs_script = f"""
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_path}"
{arguments_line}
oLink.Description = "Vega Launcher"
oLink.IconLocation = "{icon_path}, 0"
oLink.WorkingDirectory = "{work_dir}"
oLink.Save
"""
        vbs_path = os.path.join(os.environ["TEMP"], "create_shortcut.vbs")
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_script)
            
        subprocess.run(["wscript", vbs_path], check=True)
        os.remove(vbs_path)
        return True, "Kısayol masaüstüne başarıyla oluşturuldu."
    except Exception as e:
        return False, str(e)

if __name__ == "__main__":
    success, msg = create_desktop_shortcut()
    print(msg)
# Test comment


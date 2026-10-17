; MyAppVersion main.py icindeki __version__ ile AYNI olmalidir (bkz. RELEASING.md)
#define MyAppVersion "2.0.0"

[Setup]
AppName=Vega Launcher
AppVersion={#MyAppVersion}
AppPublisher=Arcturus
DefaultDirName={autopf}\Arcturus\Vega Launcher
DefaultGroupName=Vega Launcher
UninstallDisplayIcon={app}\main.exe
Compression=lzma2
SolidCompression=yes
OutputDir=build_out
OutputBaseFilename=VegaLauncher_Setup_v{#MyAppVersion}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "build_out\main\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\Vega Launcher"; Filename: "{app}\main.exe"; Tasks: desktopicon
Name: "{group}\Vega Launcher"; Filename: "{app}\main.exe"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
; Normal kurulumda: son ekranda "Vega Launcher'i baslat" secenegi
Filename: "{app}\main.exe"; WorkingDir: "{app}"; Description: "Vega Launcher'ı başlat"; Flags: nowait postinstall skipifsilent
; Otomatik (sessiz) guncellemeden sonra uygulamayi yeniden ac
Filename: "{app}\main.exe"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent runasoriginaluser

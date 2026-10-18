; MyAppVersion main.py icindeki __version__ ile AYNI olmalidir (bkz. RELEASING.md)
#define MyAppVersion "2.0.0"

[Setup]
AppName=Vega Launcher
AppVersion={#MyAppVersion}
AppPublisher=Arcturus
DefaultDirName={autopf}\Arcturus\Vega Launcher
DefaultGroupName=Vega Launcher
UninstallDisplayIcon={app}\main.exe
SetupIconFile=assets\ender_eye.ico
WizardStyle=modern
WizardImageFile=assets\installer\wizard_banner.bmp
WizardSmallImageFile=assets\installer\wizard_small.bmp
DisableWelcomePage=no
AppMutex=Global\VegaLauncher_SingleInstance_Mutex
Compression=lzma2
SolidCompression=yes
OutputDir=build_out
OutputBaseFilename=VegaLauncher_Setup_v{#MyAppVersion}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
turkish.LaunchProgram=Vega Launcher'ı başlat
english.LaunchProgram=Launch Vega Launcher
turkish.KeepUserDataPrompt=Vega Launcher kaldırılıyor.%n%nOyun profilleriniz, dünyalarınız ve ayarlarınız saklansın mı?%n%n(Önerilen: Evet)
english.KeepUserDataPrompt=Uninstalling Vega Launcher.%n%nDo you want to keep your game profiles, saved worlds, and settings?%n%n(Recommended: Yes)

[Files]
Source: "build_out\main\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\Vega Launcher"; Filename: "{app}\main.exe"; Tasks: desktopicon
Name: "{group}\Vega Launcher"; Filename: "{app}\main.exe"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Run]
; Normal kurulumda: son ekranda "Vega Launcher'i baslat" secenegi
Filename: "{app}\main.exe"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram}"; Flags: nowait postinstall skipifsilent runasoriginaluser
; Otomatik (sessiz) guncellemeden sonra uygulamayi yeniden ac
Filename: "{app}\main.exe"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent runasoriginaluser

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    UserDataDir := ExpandConstant('{userappdata}\.vega_launcher');
    if DirExists(UserDataDir) then
    begin
      if MsgBox(CustomMessage('KeepUserDataPrompt'), mbConfirmation, MB_YESNO) = IDNO then
      begin
        DelTree(UserDataDir, True, True, True);
      end;
    end;
  end;
end;

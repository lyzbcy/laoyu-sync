#define AppVersion "0.3.4"
[Setup]
AppId=studio.laoyu.sync
AppName=捞鱼同步小助手
AppVersion={#AppVersion}
AppPublisher=捞鱼工作室
AppPublisherURL=https://github.com/lyzbcy/laoyu-sync
DefaultDirName={localappdata}\Programs\LaoyuSync
DefaultGroupName=捞鱼同步小助手
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=laoyu-sync-{#AppVersion}-win-x64-setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\LaoyuSync.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE
[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked
Name: "autostart"; Description: "登录 Windows 时打开同步助手"; Flags: unchecked
[Files]
Source: "..\dist\LaoyuSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\捞鱼同步小助手"; Filename: "{app}\LaoyuSync.exe"; WorkingDir: "{app}"
Name: "{group}\卸载捞鱼同步小助手"; Filename: "{uninstallexe}"
Name: "{autodesktop}\捞鱼同步小助手"; Filename: "{app}\LaoyuSync.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LaoyuSync"; ValueData: """{app}\LaoyuSync.exe"""; Tasks: autostart; Flags: uninsdeletevalue
[Run]
Filename: "{app}\LaoyuSync.exe"; Description: "打开捞鱼同步小助手"; Flags: nowait postinstall skipifsilent

#define AppVersion "0.3.18"
[Setup]
AppId=studio.laoyu.sync
AppName=捞鱼文件夹同步
AppVersion={#AppVersion}
AppPublisher=捞鱼工作室
AppPublisherURL=https://github.com/lyzbcy/laoyu-sync
DefaultDirName={code:DefaultInstallDir}
DisableDirPage=no
DisableWelcomePage=no
DefaultGroupName=捞鱼文件夹同步
UsePreviousGroup=no
UninstallDisplayName=捞鱼文件夹同步 (Laoyu Sync)
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
WizardImageFile=welcome.bmp
WizardSmallImageFile=header.bmp
WizardImageStretch=yes
WizardImageBackColor=$E2EFE3
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
Name: "{group}\捞鱼文件夹同步"; Filename: "{app}\LaoyuSync.exe"; WorkingDir: "{app}"
Name: "{group}\卸载捞鱼文件夹同步"; Filename: "{uninstallexe}"
Name: "{autodesktop}\捞鱼文件夹同步"; Filename: "{app}\LaoyuSync.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LaoyuSync"; ValueData: """{app}\LaoyuSync.exe"""; Tasks: autostart; Flags: uninsdeletevalue
[Run]
Filename: "{app}\LaoyuSync.exe"; Description: "打开捞鱼文件夹同步"; Flags: nowait postinstall skipifsilent

[Code]
function GetDriveType(root: string): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function SuitableDrive(Letter: Char): Boolean;
var
  FreeMB, TotalMB: Cardinal;
  Root: string;
begin
  Root := Letter + ':\';
  Result := (GetDriveType(Root) = 3) and GetSpaceOnDisk(Root, True, FreeMB, TotalMB)
    and (FreeMB >= 512);
end;

function DefaultInstallDir(Param: string): string;
var
  Letter: Char;
  Index: Integer;
  SystemRoot: string;
begin
  SystemRoot := ExtractFileDrive(ExpandConstant('{win}'));
  for Index := Ord('D') to Ord('Z') do
  begin
    Letter := Chr(Index);
    if (CompareText(Letter + ':', SystemRoot) <> 0) and SuitableDrive(Letter) then
    begin
      Result := Letter + ':\Laoyu\LaoyuSync';
      Exit;
    end;
  end;
  Result := ExpandConstant('{localappdata}\Programs\LaoyuSync');
end;

procedure ChooseDrive(Sender: TObject);
var
  Letter: Char;
begin
  Letter := TNewButton(Sender).Caption[1];
  if CompareText(Letter + ':', ExtractFileDrive(ExpandConstant('{win}'))) = 0 then
    WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\Programs\LaoyuSync')
  else
    WizardForm.DirEdit.Text := Letter + ':\Laoyu\LaoyuSync';
end;

procedure InitializeWizard;
var
  Intro, Hint: TNewStaticText;
  Button: TNewButton;
  Letter: Char;
  Count, Index: Integer;
begin
  WizardForm.MainPanel.Color := $E9F2EE;
  WizardForm.PageNameLabel.Color := $E9F2EE;
  WizardForm.PageDescriptionLabel.Color := $E9F2EE;
  WizardForm.WelcomeLabel1.Font.Color := $485D20;
  WizardForm.FinishedHeadingLabel.Font.Color := $485D20;
  WizardForm.PageNameLabel.Font.Color := $485D20;

  Intro := TNewStaticText.Create(WizardForm);
  Intro.Parent := WizardForm.DirEdit.Parent;
  Intro.Left := WizardForm.DirEdit.Left;
  Intro.Top := WizardForm.DirEdit.Top + WizardForm.DirEdit.Height + ScaleY(17);
  Intro.Caption := '快捷选盘  ·  建议装到非系统盘，给系统盘留出空间';
  Intro.Font.Style := [fsBold];
  Intro.Font.Color := $485D20;

  Count := 0;
  for Index := Ord('C') to Ord('Z') do
  begin
    Letter := Chr(Index);
    if SuitableDrive(Letter) and (Count < 5) then
    begin
      Button := TNewButton.Create(WizardForm);
      Button.Parent := WizardForm.DirEdit.Parent;
      Button.Left := Intro.Left + Count * ScaleX(65);
      Button.Top := Intro.Top + ScaleY(22);
      Button.Width := ScaleX(58);
      Button.Height := ScaleY(28);
      Button.Caption := Letter + ': 盘';
      Button.OnClick := @ChooseDrive;
      Count := Count + 1;
    end;
  end;

  Hint := TNewStaticText.Create(WizardForm);
  Hint.Parent := WizardForm.DirEdit.Parent;
  Hint.Left := Intro.Left;
  Hint.Top := Intro.Top + ScaleY(60);
  Hint.Caption := '自定义位置可编辑上面的路径，或点击「浏览」。同步文件位置在助手内单独设置。';
  Hint.Font.Color := $5A6652;
end;

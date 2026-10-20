#define MyAppName "Cân AI tự động (thử nghiệm)"
#define MyAppVersion "0.2.0-ai-auto-beta1"
#define MyAppExeName "TramCanQRAuto.exe"
[Setup]
AppId={{0952EB6C-ADBA-4BD5-9047-1B3C5C15B9E8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Viet Nhat IPT
DefaultDirName={localappdata}\Programs\TramCanQRAuto
DefaultGroupName={#MyAppName}
OutputDir=..\dist\installer-auto
OutputBaseFilename=TramCanQRAuto-Setup-{#MyAppVersion}
Compression=lzma2/fast
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
[Files]
Source: "..\dist\TramCanQRAuto\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\packaging\HUONG-DAN-CAN-AI-TU-DONG.md"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\Cấu hình Cân AI tự động"; Filename: "{sys}\notepad.exe"; Parameters: """{localappdata}\TramCanQRAuto\config.env"""
[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng Cân AI tự động ngoài màn hình"; GroupDescription: "Biểu tượng:"
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mở {#MyAppName}"; Flags: nowait postinstall skipifsilent
[Code]
var StationPage: TInputOptionWizardPage;
procedure InitializeWizard;
begin
  StationPage := CreateInputOptionPage(wpSelectTasks, 'Chọn trạm', 'Chỉ cần chọn khi máy chưa cài bản Gemini.', 'Bản thử nghiệm cài riêng, không thay thế bản Gemini. Nếu có cấu hình Gemini, ứng dụng tự sao chép thông tin trạm và kết nối sang cấu hình riêng.', True, False);
  StationPage.Add('Trạm 01'); StationPage.Add('Trạm 02');
  StationPage.Add('Trạm 03'); StationPage.Add('Trạm 04');
  StationPage.SelectedValueIndex := 0;
end;
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = StationPage.ID) and (FileExists(ExpandConstant('{localappdata}\TramCanQRAuto\config.env')) or FileExists(ExpandConstant('{localappdata}\TramCanQR\config.env')));
end;
procedure CurStepChanged(CurStep: TSetupStep);
var ConfigPath, Suffix, Text: String;
begin
  if CurStep <> ssPostInstall then Exit;
  ConfigPath := ExpandConstant('{localappdata}\TramCanQRAuto\config.env');
  if FileExists(ConfigPath) or FileExists(ExpandConstant('{localappdata}\TramCanQR\config.env')) then Exit;
  Suffix := '0' + IntToStr(StationPage.SelectedValueIndex + 1);
  ForceDirectories(ExtractFileDir(ConfigPath));
  Text := 'ROLL_SCALE_STATION_COUNT=1' + #13#10 + 'ROLL_SCALE_GATEWAY_ID=gateway-' + Suffix + #13#10 + 'ROLL_SCALE_STATION_IDS=station-' + Suffix + #13#10 + 'ROLL_SCALE_CAMERA_IDS=camera-' + Suffix + #13#10 + 'ROLL_SCALE_PORT=8081' + #13#10;
  if not SaveStringToFile(ConfigPath, Text, False) then RaiseException('Không tạo được cấu hình Cân AI tự động');
end;

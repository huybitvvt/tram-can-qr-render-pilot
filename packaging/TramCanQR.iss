#define MyAppName "Tram Can QR"
#define MyAppVersion "0.2.0-rc25"
#define MyAppExeName "TramCanQR.exe"

[Setup]
AppId={{78F30B4A-47A5-4B9C-A183-E6B7E5E5A241}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Viet Nhat IPT
DefaultDirName={localappdata}\Programs\TramCanQR
DefaultGroupName={#MyAppName}
OutputDir=..\dist\installer
OutputBaseFilename=TramCanQR-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\TramCanQR\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\packaging\customer-config.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\gemini-pilot-config.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\HUONG-DAN-KHACH-HANG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\GEMINI-COST.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\CAP-NHAT-BAN-MOI.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\packaging\CAI-ANTIGRAVITY.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autodesktop}\Cập nhật Trạm Cân QR"; Filename: "{app}\CAP-NHAT-BAN-MOI.cmd"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon
Name: "{autoprograms}\Cài Antigravity CLI"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NoExit -ExecutionPolicy Bypass -File ""{app}\CAI-ANTIGRAVITY.ps1"""

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài màn hình"; GroupDescription: "Biểu tượng:"
Name: "startupicon"; Description: "Tự mở Trạm cân QR khi đăng nhập Windows"; GroupDescription: "Khởi động:"; Flags: unchecked
Name: "antigravitycli"; Description: "Cài Antigravity CLI để đăng nhập Google đọc cân"; GroupDescription: "Tùy chọn AI:"; Flags: unchecked

[Run]
Filename: "{sys}\notepad.exe"; Parameters: """{localappdata}\TramCanQR\config.env"""; Description: "Mở cấu hình để điền Supabase và Gemini (lần cài đầu)"; Flags: postinstall skipifsilent; Check: ShouldOpenInitialConfig
Filename: "{app}\{#MyAppExeName}"; Description: "Mở {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -NoExit -ExecutionPolicy Bypass -File ""{app}\CAI-ANTIGRAVITY.ps1"""; Description: "Cài Antigravity CLI"; Flags: nowait postinstall skipifsilent; Tasks: antigravitycli

[Code]
var
  StationPage: TInputOptionWizardPage;
  InitialConfigCreated: Boolean;

function RuntimeConfigPath: String;
begin
  Result := ExpandConstant('{localappdata}\TramCanQR\config.env');
end;

function ShouldOpenInitialConfig: Boolean;
begin
  Result := InitialConfigCreated;
end;

function SelectedStationSuffix: String;
begin
  Result := IntToStr(StationPage.SelectedValueIndex + 1);
  if Length(Result) = 1 then
    Result := '0' + Result;
end;

procedure InitializeWizard;
begin
  StationPage := CreateInputOptionPage(
    wpSelectTasks,
    'Chọn trạm cho máy tính này',
    'Mỗi máy tính chỉ chạy một trạm độc lập.',
    'Chọn đúng trạm 01-04. Lựa chọn chỉ tạo cấu hình ở lần cài đầu; khi cập nhật, cấu hình và dữ liệu hiện có được giữ nguyên.',
    True,
    False
  );
  StationPage.Add('Trạm 01');
  StationPage.Add('Trạm 02');
  StationPage.Add('Trạm 03');
  StationPage.Add('Trạm 04');
  StationPage.SelectedValueIndex := 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = StationPage.ID) and FileExists(RuntimeConfigPath);
end;

procedure CreateInitialRuntimeConfig;
var
  ConfigDir: String;
  ConfigPath: String;
  StationSuffix: String;
  ConfigText: String;
begin
  ConfigPath := RuntimeConfigPath;
  if FileExists(ConfigPath) then
    Exit;

  ConfigDir := ExtractFileDir(ConfigPath);
  if not ForceDirectories(ConfigDir) then
    RaiseException('Không tạo được thư mục cấu hình: ' + ConfigDir);

  StationSuffix := SelectedStationSuffix;
  ConfigText :=
    '# Cau hinh rieng cua may Tram ' + StationSuffix + #13#10 +
    '# Cai ban moi se giu nguyen file nay va du lieu trong cung thu muc.' + #13#10 +
    '# Sau khi dien: bam Ctrl+S, dong Notepad; ung dung se tu mo.' + #13#10 +
    'ROLL_SCALE_STATION_COUNT=1' + #13#10 +
    'ROLL_SCALE_GATEWAY_ID=gateway-' + StationSuffix + #13#10 +
    'ROLL_SCALE_STATION_IDS=station-' + StationSuffix + #13#10 +
    'ROLL_SCALE_CAMERA_IDS=camera-' + StationSuffix + #13#10 +
    'ROLL_SCALE_LOCAL_RETENTION_DAYS=7' + #13#10 +
    'ROLL_SCALE_PORT=8080' + #13#10 +
    'ROLL_SCALE_WEIGHT_BURST_FRAMES=5' + #13#10 +
    '' + #13#10 +
    'ROLL_SCALE_WEIGHT_ENGINE=gemini' + #13#10 +
    'ROLL_SCALE_GEMINI_API_KEY=replace-with-key-for-station-' + StationSuffix + #13#10 +
    '# ROLL_SCALE_GEMINI_BACKUP_API_KEY=replace-with-second-key-for-station-' + StationSuffix + #13#10 +
    'ROLL_SCALE_GEMINI_MODEL=gemini-3.5-flash-lite' + #13#10 +
    'ROLL_SCALE_GEMINI_ACCURATE_MODEL=gemini-3.1-pro-preview' + #13#10 +
    'ROLL_SCALE_GEMINI_TIMEOUT=30.0' + #13#10 +
    'ROLL_SCALE_GEMINI_ACCURATE_TIMEOUT=30.0' + #13#10 +
    '# ROLL_SCALE_ANTIGRAVITY_MODEL=gemini-3.5-flash-low' + #13#10 +
    '' + #13#10 +
    '# Dien bo Supabase rieng duoc cap cho dung tram nay.' + #13#10 +
    '# ROLL_SCALE_API_URL=https://YOUR_PROJECT_REF.supabase.co/functions/v1/ingest-measurement' + #13#10 +
    '# ROLL_SCALE_DEVICE_TOKEN=replace-with-device-ingest-token' + #13#10 +
    '# ROLL_SCALE_LOOKUP_URL=https://YOUR_PROJECT_REF.supabase.co/functions/v1/lookup-roll' + #13#10 +
    '# ROLL_SCALE_LOOKUP_TOKEN=replace-with-device-lookup-token' + #13#10;

  if not SaveStringToFile(ConfigPath, ConfigText, False) then
    RaiseException('Không ghi được cấu hình: ' + ConfigPath);
  InitialConfigCreated := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    CreateInitialRuntimeConfig;
end;

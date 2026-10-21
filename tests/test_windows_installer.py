from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "packaging" / "TramCanQR.iss").read_text(encoding="utf-8")


def test_installer_keeps_stable_upgrade_identity_and_customer_data() -> None:
    assert "AppId={{78F30B4A-47A5-4B9C-A183-E6B7E5E5A241}" in INSTALLER
    assert "if FileExists(ConfigPath) then" in INSTALLER
    assert "Exit;" in INSTALLER
    assert "{localappdata}\\TramCanQR\\config.env" in INSTALLER


def test_installer_assigns_one_unique_local_station_from_four_choices() -> None:
    for station_number in range(1, 5):
        assert f"StationPage.Add('Trạm 0{station_number}')" in INSTALLER
    assert "'ROLL_SCALE_STATION_COUNT=1'" in INSTALLER
    assert "'ROLL_SCALE_GATEWAY_ID=gateway-' + StationSuffix" in INSTALLER
    assert "'ROLL_SCALE_STATION_IDS=station-' + StationSuffix" in INSTALLER
    assert "'ROLL_SCALE_CAMERA_IDS=camera-' + StationSuffix" in INSTALLER
    assert "'ROLL_SCALE_LOCAL_RETENTION_DAYS=7'" in INSTALLER
    assert "'ROLL_SCALE_GEMINI_API_KEY=replace-with-key-for-station-' + StationSuffix" in INSTALLER
    assert "Dien bo Supabase rieng duoc cap cho dung tram nay" in INSTALLER


def test_installer_generated_config_is_ascii_safe_for_all_windows_code_pages() -> None:
    config_block = INSTALLER.split("ConfigText :=", 1)[1].split(
        "if not SaveStringToFile", 1
    )[0]
    config_block.encode("ascii")


def test_installer_can_create_an_optional_windows_startup_shortcut() -> None:
    assert 'Name: "startupicon"' in INSTALLER
    assert 'Name: "{userstartup}\\{#MyAppName}"' in INSTALLER


def test_first_install_opens_config_before_starting_the_gateway() -> None:
    assert 'Check: ShouldOpenInitialConfig' in INSTALLER
    assert 'Filename: "{sys}\\notepad.exe"' in INSTALLER
    assert 'InitialConfigCreated := True' in INSTALLER
    run_section = INSTALLER.split('[Run]', 1)[1].split('[Code]', 1)[0]
    assert run_section.index('Filename: "{sys}\\notepad.exe"') < run_section.index('Filename: "{app}\\{#MyAppExeName}"')

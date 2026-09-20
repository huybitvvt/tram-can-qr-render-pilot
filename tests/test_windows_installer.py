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
    assert "bộ Supabase riêng được cấp cho đúng trạm này" in INSTALLER


def test_installer_can_create_an_optional_windows_startup_shortcut() -> None:
    assert 'Name: "startupicon"' in INSTALLER
    assert 'Name: "{userstartup}\\{#MyAppName}"' in INSTALLER

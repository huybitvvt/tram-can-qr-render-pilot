from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = (ROOT / "render.yaml").read_text(encoding="utf-8")


def _service_blocks() -> list[str]:
    marker = "\n  - type: web\n"
    return ["  - type: web\n" + block for block in BLUEPRINT.split(marker)[1:]]


def test_render_blueprint_defines_four_runtime_isolated_services() -> None:
    blocks = _service_blocks()

    assert len(blocks) == 4
    assert [
        "name: tram-can-qr-pilot\n" in blocks[0],
        "name: tram-can-qr-pilot-02\n" in blocks[1],
        "name: tram-can-qr-pilot-03\n" in blocks[2],
        "name: tram-can-qr-pilot-04\n" in blocks[3],
    ] == [True, True, True, True]
    assert all('autoDeployTrigger: "off"' in block for block in blocks)
    assert all("numInstances: 1" in block for block in blocks)
    assert all(
        "- key: ROLL_SCALE_STATION_COUNT\n        value: \"1\"" in block
        for block in blocks
    )


def test_render_services_have_unique_identity_and_persistent_disks() -> None:
    blocks = _service_blocks()
    disk_names = [
        "tram-can-qr-data",
        "tram-can-qr-data-02",
        "tram-can-qr-data-03",
        "tram-can-qr-data-04",
    ]

    for number, (block, disk_name) in enumerate(zip(blocks, disk_names), start=1):
        suffix = f"{number:02d}"
        assert f"name: {disk_name}\n" in block
        assert "mountPath: /var/data" in block
        assert "sizeGB: 10" in block
        assert (
            "- key: ROLL_SCALE_LOCAL_RETENTION_DAYS\n        value: \"7\"" in block
        )
        assert f"value: render-pilot-{suffix}\n" in block
        assert f"value: station-{suffix}\n" in block
        assert f"value: camera-{suffix}\n" in block


def test_each_render_service_declares_its_own_secrets() -> None:
    secret_keys = (
        "ROLL_SCALE_GEMINI_API_KEY",
        "ROLL_SCALE_GEMINI_BACKUP_API_KEY",
        "ROLL_SCALE_API_URL",
        "ROLL_SCALE_DEVICE_TOKEN",
        "ROLL_SCALE_LOOKUP_URL",
        "ROLL_SCALE_LOOKUP_TOKEN",
    )

    for block in _service_blocks():
        for key in secret_keys:
            assert f"- key: {key}\n        sync: false" in block
        assert "- key: ROLL_SCALE_WEB_PASSWORD\n        sync: false" in block

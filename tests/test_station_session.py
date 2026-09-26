from __future__ import annotations

import hashlib
import uuid

import numpy as np
import pytest
import roll_qr_scale.station_session as station_session_module

from roll_qr_scale.station_session import (
    AnalysisBindingMismatch,
    SessionConflictError,
    StationSessionRegistry,
)


def test_analysis_binding_is_immutable_and_backed_by_staged_jpeg(tmp_path) -> None:
    registry = StationSessionRegistry(tmp_path / "staging", ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    frame = np.full((480, 640, 3), 180, dtype=np.uint8)
    event_id = str(uuid.uuid4())

    binding = registry.stage(
        frame,
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
    )

    assert binding.staged_path.is_file()
    assert hashlib.sha256(binding.staged_path.read_bytes()).hexdigest() == binding.frame_sha256
    assert registry.validate(
        binding.analysis_id,
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
        frame_sha256=binding.frame_sha256,
        require_ready=False,
    ) == binding

    with pytest.raises(AnalysisBindingMismatch, match="không thuộc"):
        registry.stage(
            frame,
            event_id=str(uuid.uuid4()),
            station_id="station-01",
            camera_id="camera-02",
        )


def test_station_does_not_overwrite_unsaved_review_and_releases_after_save(tmp_path) -> None:
    registry = StationSessionRegistry(tmp_path / "staging", ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    frame = np.full((480, 640, 3), 170, dtype=np.uint8)
    first = registry.stage(
        frame,
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )
    registry.mark_ready(first.analysis_id)

    with pytest.raises(SessionConflictError, match="chưa lưu"):
        registry.stage(
            frame,
            event_id=str(uuid.uuid4()),
            station_id="station-01",
            camera_id="camera-01",
        )

    registry.mark_saved(first.analysis_id)
    second = registry.stage(
        frame.copy(),
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )
    assert second.analysis_id != first.analysis_id


def test_failed_analysis_is_discarded_before_retrying_with_a_new_frame(tmp_path) -> None:
    registry = StationSessionRegistry(tmp_path / "staging", ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    first_event_id = str(uuid.uuid4())
    first = registry.stage(
        np.full((480, 640, 3), 170, dtype=np.uint8),
        event_id=first_event_id,
        station_id="station-01",
        camera_id="camera-01",
    )
    registry.mark_failed(first.analysis_id, RuntimeError("AI failed"))

    with pytest.raises(AnalysisBindingMismatch, match="cùng event_id"):
        registry.stage(
            np.full((480, 640, 3), 190, dtype=np.uint8),
            event_id=first_event_id,
            station_id="station-01",
            camera_id="camera-01",
        )

    assert registry.discard("station-01", event_id=first_event_id) is True
    retry = registry.stage(
        np.full((480, 640, 3), 190, dtype=np.uint8),
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )

    assert retry.analysis_id != first.analysis_id
    assert retry.event_id != first.event_id


def test_registry_rejects_duplicate_configured_camera_identity(tmp_path) -> None:
    registry = StationSessionRegistry(tmp_path / "staging", ["station-01", "station-02"])
    registry.configure_camera("station-01", "camera-shared")
    with pytest.raises(ValueError, match="đã được gán"):
        registry.configure_camera("station-02", "camera-shared")


def test_registry_automatically_restores_active_binding_after_restart(tmp_path) -> None:
    staging = tmp_path / "staging"
    registry = StationSessionRegistry(staging, ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    frame = np.full((480, 640, 3), 190, dtype=np.uint8)
    original = registry.stage(
        frame,
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )
    ready = registry.mark_ready(original.analysis_id)

    restored_registry = StationSessionRegistry(staging, ["station-01"])
    restored_registry.configure_camera("station-01", "camera-01")
    restored = restored_registry.binding(ready.analysis_id)

    assert restored == ready
    assert restored_registry.statuses()[0]["state"] == "ready"
    assert restored_registry.validate(
        original.analysis_id,
        event_id=original.event_id,
        station_id=original.station_id,
        camera_id=original.camera_id,
        frame_sha256=ready.frame_sha256,
    ) == ready



def test_restart_marks_interrupted_analysis_as_error_without_losing_staged_image(tmp_path) -> None:
    staging = tmp_path / "staging"
    registry = StationSessionRegistry(staging, ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    original = registry.stage(
        np.full((480, 640, 3), 190, dtype=np.uint8),
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )

    restored_registry = StationSessionRegistry(staging, ["station-01"])
    restored = restored_registry.binding(original.analysis_id)

    assert restored is not None
    assert restored.state == "error"
    assert restored.staged_path.read_bytes() == original.staged_path.read_bytes()
    status = restored_registry.statuses()[0]
    assert status["event_id"] == original.event_id
    assert status["state"] == "error"
    assert "khởi động lại" in status["last_error"]

    restarted_again = StationSessionRegistry(staging, ["station-01"])
    assert restarted_again.statuses()[0]["state"] == "error"


def test_pending_binding_does_not_expire_after_ten_minutes(tmp_path, monkeypatch) -> None:
    registry = StationSessionRegistry(tmp_path / "staging", ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    event_id = str(uuid.uuid4())
    binding = registry.stage(
        np.full((480, 640, 3), 190, dtype=np.uint8),
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
    )
    binding = registry.mark_ready(binding.analysis_id)
    real_time = station_session_module.time.time
    monkeypatch.setattr(station_session_module.time, "time", lambda: real_time() + 11 * 60)

    assert registry.validate(
        binding.analysis_id,
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
        frame_sha256=binding.frame_sha256,
    ) == binding


def test_corrupt_staged_image_is_not_restored(tmp_path) -> None:
    staging = tmp_path / "staging"
    registry = StationSessionRegistry(staging, ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    binding = registry.stage(
        np.full((480, 640, 3), 190, dtype=np.uint8),
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )
    registry.mark_ready(binding.analysis_id)
    binding.staged_path.write_bytes(b"not-a-jpeg")

    restored_registry = StationSessionRegistry(staging, ["station-01"])

    assert restored_registry.binding(binding.analysis_id) is None
    assert restored_registry.statuses()[0]["state"] == "idle"


@pytest.mark.parametrize("completion", ["saved", "discarded"])
def test_completed_binding_is_not_restored(tmp_path, completion) -> None:
    staging = tmp_path / "staging"
    registry = StationSessionRegistry(staging, ["station-01"])
    registry.configure_camera("station-01", "camera-01")
    binding = registry.stage(
        np.full((480, 640, 3), 190, dtype=np.uint8),
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )
    registry.mark_ready(binding.analysis_id)
    if completion == "saved":
        registry.mark_saved(binding.analysis_id)
    else:
        registry.discard("station-01", event_id=binding.event_id)

    restored_registry = StationSessionRegistry(staging, ["station-01"])

    assert restored_registry.binding(binding.analysis_id) is None
    assert restored_registry.statuses()[0]["state"] == "idle"

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDGE_SOURCE = (
    ROOT / "backend" / "supabase" / "functions" / "ingest-measurement" / "index.ts"
).read_text(encoding="utf-8")
RETENTION_MIGRATION = (
    ROOT
    / "backend"
    / "supabase"
    / "migrations"
    / "20260911193000_local_image_retention.sql"
).read_text(encoding="utf-8")
RENDER_BLUEPRINT = (ROOT / "render.yaml").read_text(encoding="utf-8")
SYNC_SOURCE = (ROOT / "backend" / "src" / "roll_qr_scale" / "sync.py").read_text(
    encoding="utf-8"
)
API_CLIENT_SOURCE = (ROOT / "backend" / "src" / "roll_qr_scale" / "api_client.py").read_text(
    encoding="utf-8"
)
UI_SOURCE = (ROOT / "backend" / "src" / "roll_qr_scale" / "test_ui.py").read_text(
    encoding="utf-8"
)


def test_image_bytes_stay_on_render_disk_and_supabase_storage_is_not_used() -> None:
    assert 'LOCAL_BACKUP_PROVIDER = "render_persistent_disk"' in EDGE_SOURCE
    assert ".download(" not in EDGE_SOURCE
    assert ".getPublicUrl(" not in EDGE_SOURCE
    assert "roll-captures-backup" not in EDGE_SOURCE
    assert "local_backup_committed: true" in EDGE_SOURCE
    assert "cloudinary_pending" in EDGE_SOURCE
    assert "return json(503" not in EDGE_SOURCE
    assert "image_url: uploaded?.secureUrl ?? null" in EDGE_SOURCE
    assert "image_path: uploaded?.publicId ?? imagePublicId" in EDGE_SOURCE
    assert "persist_product_evidence" not in API_CLIENT_SOURCE
    # A short-lived signed URL remains a read-only compatibility path for
    # legacy rows; new evidence is never uploaded to this bucket.
    assert "def sign_storage_image(" in API_CLIENT_SOURCE
    assert "/storage/v1/object/roll-captures/" not in API_CLIENT_SOURCE
    assert "persist_product_evidence" not in UI_SOURCE
    assert "sign_storage_image" in UI_SOURCE


def test_retention_schema_keeps_ai_rows_after_image_release() -> None:
    assert "alter column image_url drop not null" in RETENTION_MIGRATION
    assert "alter column image_public_id drop not null" in RETENTION_MIGRATION
    assert "capture_kind in ('core', 'product', 'inventory')" in RETENTION_MIGRATION


def test_render_blueprint_mounts_persistent_disk_for_local_evidence() -> None:
    assert "mountPath: /var/data" in RENDER_BLUEPRINT
    assert "sizeGB: 10" in RENDER_BLUEPRINT
    assert "ROLL_SCALE_DATA_ROOT" in RENDER_BLUEPRINT
    assert "ROLL_SCALE_LOCAL_RETENTION_DAYS" in RENDER_BLUEPRINT


def test_daily_maintenance_sends_metadata_report_and_releases_only_acknowledged_files() -> None:
    assert "local_backup_report(" in SYNC_SOURCE
    assert '"local_evidence": report' in SYNC_SOURCE
    assert "prune_local_captures(" in SYNC_SOURCE
    assert "local_retention_days" in SYNC_SOURCE
    assert "image_retention_released_roles" in EDGE_SOURCE
    assert "releasedForRow" in EDGE_SOURCE

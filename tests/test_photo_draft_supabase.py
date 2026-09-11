from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FUNCTION = (
    ROOT / "backend" / "supabase" / "functions" / "ingest-measurement" / "index.ts"
).read_text(encoding="utf-8")
MIGRATION = (
    ROOT
    / "backend"
    / "supabase"
    / "migrations"
    / "20260824150000_anh_can_cho_ai.sql"
).read_text(encoding="utf-8")
PARENT_EVENT_MIGRATION = (
    ROOT
    / "backend"
    / "supabase"
    / "migrations"
    / "20260824170000_photo_draft_parent_event.sql"
).read_text(encoding="utf-8")
WEIGH_BATCH_MIGRATION = (
    ROOT
    / "backend"
    / "supabase"
    / "migrations"
    / "20260907010000_ca_can_and_measurement_errors.sql"
).read_text(encoding="utf-8")


def test_photo_draft_table_keeps_weight_data_truly_empty() -> None:
    table_sql = MIGRATION.lower().split("create table", 1)[1].split(");", 1)[0]
    assert "public.anh_can_cho_ai" in table_sql
    assert "qr_code text" in table_sql
    assert "status text not null default 'awaiting_ai'" in table_sql
    assert "weight" not in table_sql
    assert "khoi_luong" not in table_sql


def test_ingest_routes_photo_draft_before_measurement_validation() -> None:
    assert 'const photoDraft = workflow === "photo_draft"' in FUNCTION
    assert 'const PHOTO_DRAFT_TABLE = "anh_can_cho_ai"' in FUNCTION
    assert 'if (!photoDraft && (!Number.isFinite(weight)' in FUNCTION
    assert 'status: "awaiting_ai"' in FUNCTION
    assert 'ai_requested: false' in FUNCTION
    assert "/photo-draft/${parentEventId}/${captureKind}-${captureRound + 1}/${eventId}" in FUNCTION


def test_delete_measurement_also_deletes_grouped_photo_drafts() -> None:
    delete_block = FUNCTION.split('if (body.action === "delete_measurement")', 1)[1].split(
        'if (body.action === "update_measurement")', 1
    )[0]
    assert ".from(PHOTO_DRAFT_TABLE)" in delete_block
    assert ".or(`parent_event_id.eq.${eventId},event_id.eq.${eventId}`)" in delete_block
    assert "photo_drafts_deleted: photoDraftsDeleted" in delete_block


def test_measurement_list_is_filtered_counted_and_bandwidth_limited() -> None:
    assert "const EVENT_LIST_SELECT" in FUNCTION
    assert '.select(EVENT_LIST_SELECT, { count: "exact" })' in FUNCTION
    assert 'params.get("work_date")' in FUNCTION
    assert 'params.get("machine")' in FUNCTION
    assert 'params.get("production_order")' in FUNCTION
    assert 'query.eq("metadata->>work_date", workDate)' in FUNCTION
    assert 'query.eq("metadata->>machine", machine)' in FUNCTION
    assert 'query.eq("metadata->>production_order", productionOrder)' in FUNCTION
    assert "total_count: count" in FUNCTION


def test_photo_draft_is_linked_to_weigh_event_and_slot() -> None:
    lowered = PARENT_EVENT_MIGRATION.lower()
    assert "parent_event_id uuid" in lowered
    assert "capture_kind text" in lowered
    assert "capture_round integer" in lowered
    assert "anh_can_cho_ai_parent_event_idx" in lowered
    assert "parent_event_id: parenteventid" in FUNCTION.lower()


def test_every_ten_roll_batch_is_persisted_and_must_be_confirmed_in_order() -> None:
    lowered = WEIGH_BATCH_MIGRATION.lower()
    assert "create table if not exists public.ca_can" in lowered
    assert "moc_so_luong = dot_can * 10" in lowered
    assert "so_luong = 10" in lowered
    assert "danh_sach_san_pham jsonb" in lowered
    assert 'if (body.action === "confirm_weighing_batch")' in FUNCTION
    assert 'error: "previous_weighing_batch_not_confirmed"' in FUNCTION
    assert ".slice(offset, offset + 10)" in FUNCTION

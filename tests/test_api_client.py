import urllib.parse

from roll_qr_scale.api_client import (
    delete_supabase_photo_drafts,
    fetch_remote_measurement_page,
    fetch_remote_weigh_batches,
    fetch_supabase_photo_draft_parent_ids,
    fetch_supabase_table,
    fetch_supabase_table_count,
    post_remote_action,
)


def test_remote_measurement_page_sends_all_filters_and_reads_exact_count(monkeypatch) -> None:
    captured = {}

    def fake_remote_json(url, token, *, params, timeout):
        captured.update(url=url, token=token, params=params, timeout=timeout)
        return {"ok": True, "total_count": 321, "items": [{"event_id": "event-1"}]}

    monkeypatch.setattr("roll_qr_scale.api_client.fetch_remote_json", fake_remote_json)

    items, total = fetch_remote_measurement_page(
        "https://project.supabase.co/functions/v1/ingest-measurement",
        "device-token",
        limit=50,
        offset=100,
        work_date="2026-09-06",
        shift="12C2",
        machine="Máy Bao Bì",
        production_order="LSX-DH067",
        qr_code="SP-01",
    )

    assert items == [{"event_id": "event-1"}]
    assert total == 321
    assert captured["params"] == {
        "limit": 50,
        "offset": 100,
        "work_date": "2026-09-06",
        "shift": "12C2",
        "machine": "Máy Bao Bì",
        "production_order": "LSX-DH067",
        "qr_code": "SP-01",
    }


def test_remote_weigh_batches_uses_ca_can_action_and_source_filters(monkeypatch) -> None:
    captured = {}

    def fake_remote_json(url, token, *, params, timeout):
        captured.update(url=url, token=token, params=params, timeout=timeout)
        return {"ok": True, "items": [{"dot_can": 2, "so_luong": 10}]}

    monkeypatch.setattr("roll_qr_scale.api_client.fetch_remote_json", fake_remote_json)

    rows = fetch_remote_weigh_batches(
        "https://project.supabase.co/functions/v1/ingest-measurement",
        "device-token",
        work_date="2026-09-07",
        shift="12C1",
        machine="Máy 1",
        production_order="LSX-01",
    )

    assert rows == [{"dot_can": 2, "so_luong": 10}]
    assert captured["params"] == {
        "action": "weighing-batches",
        "limit": 50,
        "work_date": "2026-09-07",
        "shift": "12C1",
        "machine": "Máy 1",
        "production_order": "LSX-01",
    }


def test_post_remote_action_sends_authenticated_json(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"ok":true,"item":{"dot_can":1}}'

    def fake_urlopen(request, timeout):
        captured.update(request=request, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    body = {"action": "confirm_weighing_batch", "milestone": 10}

    result = post_remote_action(
        "https://project.supabase.co/functions/v1/ingest-measurement",
        "device-token",
        body=body,
    )

    assert result["item"] == {"dot_can": 1}
    assert captured["request"].get_header("X-device-token") == "device-token"
    assert captured["request"].data == b'{"action": "confirm_weighing_batch", "milestone": 10}'


def test_fetch_supabase_table_limits_columns_rows_and_filters(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'[{"event_id":"event-1"}]'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    rows = fetch_supabase_table(
        "https://project.supabase.co",
        "public-key",
        limit=50,
        offset=100,
        work_date="2026-09-06",
        shift="12C2",
        machine="Máy Bao Bì",
        production_order="LSX-DH067",
    )

    query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(captured["request"].full_url).query
    )
    assert rows == [{"event_id": "event-1"}]
    assert query["limit"] == ["50"]
    assert query["offset"] == ["100"]
    assert query["metadata->>work_date"] == ["eq.2026-09-06"]
    assert query["metadata->>shift"] == ["eq.12C2"]
    assert query["metadata->>machine"] == ["eq.Máy Bao Bì"]
    assert query["metadata->>production_order"] == ["eq.LSX-DH067"]
    assert "image_public_id" not in query["select"][0]


def test_fetch_supabase_table_count_uses_all_source_filters(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        headers = {"Content-Range": "0-0/237"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    total = fetch_supabase_table_count(
        "https://project.supabase.co",
        "public-key",
        work_date="2026-08-24",
        shift="12C2",
        machine="Máy cách nhiệt",
        production_order="LSX-DH061",
    )

    query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(captured["request"].full_url).query
    )
    assert total == 237
    assert query["metadata->>work_date"] == ["eq.2026-08-24"]
    assert query["metadata->>shift"] == ["eq.12C2"]
    assert query["metadata->>machine"] == ["eq.Máy cách nhiệt"]
    assert query["metadata->>production_order"] == ["eq.LSX-DH061"]
    assert captured["request"].get_header("Prefer") == "count=exact"
    assert captured["timeout"] == 10.0


def test_fetch_supabase_table_count_supports_date_range_and_qr(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        headers = {"Content-Range": "0-0/12"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    total = fetch_supabase_table_count(
        "https://project.supabase.co",
        "public-key",
        date_from="2026-08-01",
        date_to="2026-08-24",
        shift="HC1",
        qr_code="SP-01",
    )

    query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(captured["request"].full_url).query
    )
    assert total == 12
    assert query["and"] == [
        "(metadata->>work_date.gte.2026-08-01,metadata->>work_date.lte.2026-08-24)"
    ]
    assert query["metadata->>shift"] == ["eq.HC1"]
    assert query["qr_code"] == ["ilike.*SP-01*"]


def test_fetch_supabase_photo_drafts_counts_distinct_error_products(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'[{"parent_event_id":"error-1","event_id":"core-1"},'
                b'{"parent_event_id":"error-1","event_id":"product-1"},'
                b'{"parent_event_id":"error-2","event_id":"core-2"}]'
            )

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    parent_ids = fetch_supabase_photo_draft_parent_ids(
        "https://project.supabase.co",
        "service-key",
        work_date="2026-08-24",
        shift="12C2",
        machine="Máy cách nhiệt",
        production_order="LSX-DH061",
    )

    query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(captured["request"].full_url).query
    )
    assert parent_ids == {"error-1", "error-2"}
    assert query["work_date"] == ["eq.2026-08-24"]
    assert query["shift"] == ["eq.12C2"]
    assert query["machine"] == ["eq.Máy cách nhiệt"]
    assert query["production_order"] == ["eq.LSX-DH061"]


def test_delete_supabase_photo_drafts_removes_the_whole_displayed_row(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'[{"event_id":"core-1","parent_event_id":"parent-1"},'
                b'{"event_id":"product-1","parent_event_id":"parent-1"}]'
            )

    def fake_urlopen(request, timeout):
        captured.update(request=request, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    deleted = delete_supabase_photo_drafts(
        "https://project.supabase.co",
        "service-key",
        "parent-1",
    )

    query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(captured["request"].full_url).query
    )
    assert deleted == 2
    assert captured["request"].method == "DELETE"
    assert captured["request"].get_header("Prefer") == "return=representation"
    assert query["or"] == ["(parent_event_id.eq.parent-1,event_id.eq.parent-1)"]
    assert query["select"] == ["event_id,parent_event_id"]

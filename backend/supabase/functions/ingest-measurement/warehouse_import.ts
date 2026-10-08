import type { SupabaseClient } from "npm:@supabase/supabase-js@2";

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SELECT = "id,event_id,qr_code,metadata";

function response(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json; charset=utf-8" },
  });
}

// The caller authenticates the device token before invoking this handler.
// A check validates every event before any warehouse rows are written.
export async function warehouseImportStatus(
  body: Record<string, unknown>, supabase: Pick<SupabaseClient, "from">,
): Promise<Response> {
  const ids = Array.isArray(body.event_ids) ? body.event_ids : [];
  if (!ids.length || ids.length > 2000 || ids.some((id) => typeof id !== "string" || !ID_PATTERN.test(id))) {
    return response(422, { ok: false, error: "invalid_event_ids" });
  }
  const eventIds = [...new Set(ids as string[])];
  const checkOnly = body.check_only === true;
  const receipt = typeof body.ma_phieu === "string" ? body.ma_phieu.trim() : "";
  if (!checkOnly && (!receipt || receipt.length > 200)) {
    return response(422, { ok: false, error: "invalid_ma_phieu" });
  }
  const person = typeof body.nguoi === "string" ? body.nguoi.trim().slice(0, 200) : "Trạm cân";
  const rows: Record<string, unknown>[] = [];
  for (let offset = 0; offset < eventIds.length; offset += 100) {
    const { data, error } = await supabase.from("can_tu_dong")
      .select(SELECT).in("event_id", eventIds.slice(offset, offset + 100));
    if (error) return response(500, { ok: false, error: "warehouse_status_read_failed", detail: error.message });
    rows.push(...(data ?? []));
  }
  const found = new Set(rows.map((row) => String(row.event_id)));
  const missing = eventIds.filter((id) => !found.has(id));
  if (missing.length) {
    return response(409, { ok: false, error: "warehouse_measurements_missing", detail: "Chưa đồng bộ đủ phiếu cân AI", missing });
  }
  if (checkOnly) return response(200, { ok: true, items: rows, confirmed_count: eventIds.length });

  const timestamp = new Date().toISOString();
  let updated = 0;
  for (const row of rows) {
    const metadata = row.metadata && typeof row.metadata === "object" && !Array.isArray(row.metadata)
      ? { ...row.metadata as Record<string, unknown> } : {};
    if (metadata.nhap_kho_trang_thai === "Đã nhập kho" && metadata.nhap_kho_ma_phieu === receipt) continue;
    metadata.nhap_kho_trang_thai = "Đã nhập kho";
    metadata.nhap_kho_ma_phieu = receipt;
    metadata.nhap_kho_luc = timestamp;
    metadata.nhap_kho_boi = person || "Trạm cân";
    const { data, error } = await supabase.from("can_tu_dong")
      .update({ metadata }).eq("id", row.id).select("id").maybeSingle();
    if (error || !data) {
      return response(500, {
        ok: false, error: "warehouse_status_update_failed", detail: error?.message || "empty_update",
      });
    }
    updated += 1;
  }
  return response(200, {
    ok: true, updated, confirmed_count: eventIds.length, nhap_kho_trang_thai: "Đã nhập kho",
    nhap_kho_luc: timestamp, nhap_kho_boi: person || "Trạm cân",
  });
}

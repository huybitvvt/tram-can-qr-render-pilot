import { createClient } from "npm:@supabase/supabase-js@2";

const MEASUREMENT_TABLE = "can_tu_dong";

function json(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function getSupabaseAdminKey(): string | undefined {
  const secretKeys = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (secretKeys) {
    try {
      const parsed = JSON.parse(secretKeys) as Record<string, unknown>;
      if (typeof parsed.default === "string") return parsed.default;
    } catch {
      // Fall through to the legacy key used by older Supabase projects.
    }
  }
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
}

function isLegacyStoragePath(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim()) &&
    !value.trim().startsWith("roll-captures/");
}

Deno.serve(async (request: Request) => {
  if (request.method !== "GET") {
    return json(405, { ok: false, error: "method_not_allowed" });
  }

  const expectedToken = Deno.env.get("DEVICE_LOOKUP_TOKEN");
  const suppliedToken = request.headers.get("x-device-token");
  if (!expectedToken) {
    return json(500, { ok: false, error: "server_not_configured" });
  }
  if (!suppliedToken || suppliedToken !== expectedToken) {
    return json(401, { ok: false, error: "unauthorized" });
  }

  const qrCode = new URL(request.url).searchParams.get("qr")?.trim() ?? "";
  if (!qrCode || qrCode.length > 512) {
    return json(422, { ok: false, error: "invalid_qr_code" });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const adminKey = getSupabaseAdminKey();
  if (!supabaseUrl || !adminKey) {
    return json(500, { ok: false, error: "supabase_not_configured" });
  }
  const supabase = createClient(supabaseUrl, adminKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { data: measurement, error } = await supabase
    .from(MEASUREMENT_TABLE)
    .select(
      "id,event_id,qr_code,weight,tare_weight,net_weight,unit,captured_at," +
      "device_id,gateway_id,station_id,camera_id,analysis_id,frame_sha256,payload_hash," +
      "weight_source,qr_source,image_path,image_url,image_public_id," +
      "core_image_path,core_image_url,core_image_public_id," +
      "qr_image_path,qr_image_url,qr_image_public_id,qr_frame_sha256,status,metadata",
    )
    .eq("qr_code", qrCode)
    .eq("status", "confirmed")
    .order("captured_at", { ascending: false })
    .order("id", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) {
    return json(500, { ok: false, error: "lookup_failed" });
  }
  if (!measurement) {
    return json(404, { ok: false, found: false, qr_code: qrCode });
  }
  const measurementRow = measurement as unknown as Record<string, unknown>;

  const { count } = await supabase
    .from(MEASUREMENT_TABLE)
    .select("id", { count: "exact", head: true })
    .eq("qr_code", qrCode)
    .eq("status", "confirmed");

  let imageUrl: string | null = typeof measurementRow.image_url === "string"
    ? measurementRow.image_url
    : null;
  let imageUrlExpiresIn: number | null = null;
  // New rows use deterministic Cloudinary public IDs in image_path. Only
  // legacy rows that still point at the private compatibility bucket may
  // request a short signed URL; never probe Supabase Storage for new/pending
  // local-disk evidence because that creates needless egress and returns a
  // broken URL after the seven-day Cloudinary retention window.
  if (!imageUrl && isLegacyStoragePath(measurementRow.image_path)) {
    const { data: signed } = await supabase.storage
      .from("roll-captures")
      .createSignedUrl(measurementRow.image_path, 300);
    imageUrl = signed?.signedUrl ?? null;
    imageUrlExpiresIn = imageUrl ? 300 : null;
  }

  const coreImageUrl = typeof measurementRow.core_image_url === "string"
    ? measurementRow.core_image_url
    : imageUrl;

  return json(200, {
    ok: true,
    found: true,
    history_count: count ?? 1,
    measurement: {
      ...measurementRow,
      gateway_id: measurementRow.gateway_id ?? measurementRow.device_id ?? null,
      gross_weight: measurementRow.weight,
      image_url: imageUrl,
      image_url_expires_in: imageUrlExpiresIn,
      core_image_url: coreImageUrl,
    },
  });
});

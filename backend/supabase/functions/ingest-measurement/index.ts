import { createClient, type SupabaseClient } from "npm:@supabase/supabase-js@2";

const MAX_IMAGE_BYTES = 6 * 1024 * 1024;
const UNITS = new Set(["kg", "g", "lb"]);
const MEASUREMENT_TABLE = "can_tu_dong";
const WEIGH_BATCH_TABLE = "ca_can";
const INVENTORY_TABLE = "can_kiem_kho";
const PHOTO_DRAFT_TABLE = "anh_can_cho_ai";
const SECRET_TABLE = "roll_scale_secrets";
const DEFAULT_CLOUDINARY_RETENTION_DAYS = 7;
const LOCAL_BACKUP_PROVIDER = "render_persistent_disk";
const MAX_LOCAL_EVIDENCE_ITEMS = 500;
const MAX_LOCAL_EVIDENCE_ROLES = 3;
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function normalizeEventId(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(Math.trunc(value));
  return "";
}
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;
const EVENT_SELECT =
  "id,event_id,image_path,image_url,image_public_id,core_image_path,core_image_url," +
  "core_image_public_id,product_image_path,product_image_url,product_image_public_id,qr_code,weight,tare_weight,net_weight,unit,captured_at," +
  "device_id,gateway_id,station_id,camera_id,analysis_id,frame_sha256,payload_hash," +
  "weight_source,qr_source,error_status,error_reason,metadata";
const EVENT_LIST_SELECT =
  "id,event_id,image_url,core_image_url,product_image_url,product_image_path," +
  "qr_code,weight,tare_weight,net_weight,unit,captured_at,error_status,error_reason,metadata";

function json(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function sha256Hex(value: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", Uint8Array.from(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0"))
    .join("");
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

function sameEvent(
  existing: Record<string, unknown>,
  qrCode: string,
  weight: number,
  unit: string,
  capturedAt: string,
  weightSource: string,
  qrSource: string,
  weightRaw: string,
  weightStable: boolean,
  gatewayId: string,
  stationId: string | null,
  cameraId: string | null,
  analysisId: string | null,
  frameSha256: string | null,
  payloadHash: string | null,
): boolean {
  const metadata = existing.metadata !== null && typeof existing.metadata === "object"
    ? existing.metadata as Record<string, unknown>
    : {};
  const existingGateway = existing.gateway_id ?? existing.device_id;
  const storedTare = Number(existing.tare_weight ?? 0);
  const existingCoreWeight = Number(
    metadata.core_weight ?? (storedTare > 0 ? storedTare : existing.weight),
  );
  return existing.qr_code === qrCode &&
    existingCoreWeight === weight &&
    existing.unit === unit &&
    Date.parse(String(existing.captured_at)) === Date.parse(capturedAt) &&
    existing.weight_source === weightSource &&
    existing.qr_source === qrSource &&
    storedValueMatches(metadata.weight_raw, weightRaw) &&
    storedValueMatches(metadata.weight_stable, weightStable) &&
    storedValueMatches(existingGateway, gatewayId) &&
    storedValueMatches(existing.station_id, stationId) &&
    storedValueMatches(existing.camera_id, cameraId) &&
    storedValueMatches(existing.analysis_id, analysisId) &&
    storedHashMatches(existing.frame_sha256, frameSha256) &&
    storedHashMatches(existing.payload_hash, payloadHash);
}

// A NULL stored value identifies a row created before that field existed. Such
// rows accept the richer retry payload. Once stored, an immutable field must be
// supplied and match on every retry of the same event_id.
function storedValueMatches(existing: unknown, incoming: unknown): boolean {
  if (existing === null || existing === undefined) return true;
  return incoming !== null && incoming !== undefined && existing === incoming;
}

function storedHashMatches(existing: unknown, incoming: string | null): boolean {
  if (existing === null || existing === undefined) return true;
  return incoming !== null && String(existing).toLowerCase() === incoming;
}

function sameInventoryCheck(
  existing: Record<string, unknown>,
  productCode: string,
  weight: number,
  coreWeight: number,
  tareWeight: number,
  unit: string,
  capturedAt: string,
  gatewayId: string,
  stationId: string | null,
  cameraId: string | null,
  analysisId: string | null,
  frameSha256: string | null,
  payloadHash: string | null,
): boolean {
  return existing.ma_san_pham === productCode &&
    Number(existing.khoi_luong) === weight &&
    Number(existing.khoi_luong_loi) === coreWeight &&
    Number(existing.khoi_luong_bi) === tareWeight &&
    existing.don_vi === unit &&
    Date.parse(String(existing.captured_at)) === Date.parse(capturedAt) &&
    storedValueMatches(existing.gateway_id, gatewayId) &&
    storedValueMatches(existing.station_id, stationId) &&
    storedValueMatches(existing.camera_id, cameraId) &&
    storedValueMatches(existing.analysis_id, analysisId) &&
    storedHashMatches(existing.frame_sha256, frameSha256) &&
    storedHashMatches(existing.payload_hash, payloadHash);
}

type CloudinaryUpload = {
  publicId: string;
  secureUrl: string;
};

async function destroyCloudinary(publicId: string): Promise<void> {
  const cloudName = Deno.env.get("CLOUDINARY_CLOUD_NAME");
  const apiKey = Deno.env.get("CLOUDINARY_API_KEY");
  const apiSecret = Deno.env.get("CLOUDINARY_API_SECRET");
  if (!cloudName || !apiKey || !apiSecret) {
    throw new Error("cloudinary_not_configured");
  }
  const params = new URLSearchParams({ invalidate: "true" });
  params.append("public_ids[]", publicId);
  const response = await fetch(
    `https://api.cloudinary.com/v1_1/${encodeURIComponent(cloudName)}/resources/image/upload?${params}`,
    {
      method: "DELETE",
      headers: { authorization: `Basic ${btoa(`${apiKey}:${apiSecret}`)}` },
    },
  );
  let result: Record<string, unknown> = {};
  try {
    result = await response.json() as Record<string, unknown>;
  } catch {
    // HTTP status is authoritative below.
  }
  const deleted = result.deleted && typeof result.deleted === "object"
    ? (result.deleted as Record<string, unknown>)[publicId]
    : undefined;
  if (!response.ok || !["deleted", "not_found"].includes(String(deleted ?? ""))) {
    throw new Error(`cloudinary_destroy_failed:${response.status}`);
  }
}

function backupMetadata(
  metadata: Record<string, unknown>,
  capturedAt: string,
): Record<string, unknown> {
  return {
    ...metadata,
    image_backup: {
      provider: LOCAL_BACKUP_PROVIDER,
      committed_before_cloud: true,
      retention_days: DEFAULT_CLOUDINARY_RETENTION_DAYS,
      evidence_window_ends_at: new Date(
        Date.parse(capturedAt) + DEFAULT_CLOUDINARY_RETENTION_DAYS * 86400000,
      ).toISOString(),
    },
    local_backup_committed_at: new Date().toISOString(),
    cloudinary_delete_after: new Date(
      Date.parse(capturedAt) + DEFAULT_CLOUDINARY_RETENTION_DAYS * 86400000,
    ).toISOString(),
  };
}

function hasLocalBackupCommit(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const metadata = value as Record<string, unknown>;
  const imageBackup = metadata.image_backup;
  if (!imageBackup || typeof imageBackup !== "object" || Array.isArray(imageBackup)) {
    return false;
  }
  const backup = imageBackup as Record<string, unknown>;
  return backup.provider === LOCAL_BACKUP_PROVIDER && backup.committed_before_cloud === true;
}

function rowHasLocalBackupCommit(row: Record<string, unknown>): boolean {
  return hasLocalBackupCommit(row.metadata);
}

function metadataCloudinaryPending(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const metadata = value as Record<string, unknown>;
  return metadata.cloudinary_pending === true || metadata.local_backup_only === true;
}

function cloudinaryUrl(value: unknown): string {
  const url = typeof value === "string" ? value.trim() : "";
  return url.startsWith("https://res.cloudinary.com/") ? url : "";
}

type LocalEvidenceRole = {
  sha256: string;
  bytes: number;
};

type LocalEvidenceItem = {
  table: string;
  event_id: string;
  captured_at: string;
  roles: Record<string, LocalEvidenceRole>;
};

type LocalEvidenceReport = {
  provider: string;
  retention_days: number;
  generated_at: string;
  items: LocalEvidenceItem[];
};

function parseLocalEvidence(value: unknown): LocalEvidenceReport {
  const empty: LocalEvidenceReport = {
    provider: "",
    retention_days: DEFAULT_CLOUDINARY_RETENTION_DAYS,
    generated_at: "",
    items: [],
  };
  if (!value || typeof value !== "object") return empty;
  const input = value as Record<string, unknown>;
  const provider = typeof input.provider === "string" ? input.provider.trim() : "";
  if (provider !== LOCAL_BACKUP_PROVIDER) return empty;
  const requestedRetention = Number(input.retention_days);
  const retentionDays = Number.isInteger(requestedRetention)
    ? Math.max(1, Math.min(requestedRetention, 30))
    : DEFAULT_CLOUDINARY_RETENTION_DAYS;
  const rawItems = Array.isArray(input.items) ? input.items : [];
  const items: LocalEvidenceItem[] = [];
  for (const rawItem of rawItems.slice(0, MAX_LOCAL_EVIDENCE_ITEMS)) {
    if (!rawItem || typeof rawItem !== "object") continue;
    const item = rawItem as Record<string, unknown>;
    const table = typeof item.table === "string" ? item.table.trim() : "";
    const eventId = typeof item.event_id === "string" ? item.event_id.trim() : "";
    const capturedAt = typeof item.captured_at === "string" ? item.captured_at.trim() : "";
    if (
      ![MEASUREMENT_TABLE, INVENTORY_TABLE, PHOTO_DRAFT_TABLE].includes(table) ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(eventId) ||
      !capturedAt || Number.isNaN(Date.parse(capturedAt))
    ) continue;
    const rawRoles = item.roles && typeof item.roles === "object"
      ? item.roles as Record<string, unknown>
      : {};
    const roles: Record<string, LocalEvidenceRole> = {};
    for (const [role, rawRole] of Object.entries(rawRoles).slice(0, MAX_LOCAL_EVIDENCE_ROLES)) {
      if (!rawRole || typeof rawRole !== "object") continue;
      const roleValue = rawRole as Record<string, unknown>;
      const sha256 = typeof roleValue.sha256 === "string"
        ? roleValue.sha256.trim().toLowerCase()
        : "";
      const bytes = Number(roleValue.bytes);
      if (
        !["core", "product", "image"].includes(role) ||
        !SHA256_PATTERN.test(sha256) ||
        !Number.isSafeInteger(bytes) || bytes < 4 || bytes > MAX_IMAGE_BYTES
      ) continue;
      roles[role] = { sha256, bytes };
    }
    if (Object.keys(roles).length) {
      items.push({ table, event_id: eventId, captured_at: capturedAt, roles });
    }
  }
  return {
    provider,
    retention_days: retentionDays,
    generated_at: typeof input.generated_at === "string" ? input.generated_at : "",
    items,
  };
}

function evidenceRoleMatches(
  table: string,
  row: Record<string, unknown>,
  role: string,
  evidence: LocalEvidenceRole,
): boolean {
  const expectedHash = role === "core" || role === "image" ? row.frame_sha256 : null;
  if (expectedHash && SHA256_PATTERN.test(String(expectedHash))) {
    return String(expectedHash).toLowerCase() === evidence.sha256 &&
      Number(evidence.bytes) > 0;
  }
  // Product images did not have a dedicated hash column in older schemas. The
  // gateway still reports a checksum after reading the committed local file;
  // the event identity and bounded byte count are the independent proof here.
  return table === MEASUREMENT_TABLE && role === "product" && evidence.bytes > 0;
}

async function runBackupMaintenance(
  supabase: SupabaseClient,
  retentionDays: number,
  localEvidence: LocalEvidenceReport,
): Promise<Record<string, unknown>> {
  const cutoff = new Date(Date.now() - retentionDays * 86400000).toISOString();
  let checked = 0;
  let verified = 0;
  let deleted = 0;
  const errors: string[] = [];
  const released: Array<Record<string, string>> = [];
  if (!localEvidence.items.length) {
    return {
      checked,
      verified,
      cloudinary_deleted: deleted,
      released,
      errors,
      retention_days: retentionDays,
      cutoff,
      backup_provider: LOCAL_BACKUP_PROVIDER,
      metadata_only: true,
    };
  }
  const tableConfigs = [
    {
      table: MEASUREMENT_TABLE,
      select:
        "id,event_id,gateway_id,captured_at,image_url,image_public_id,core_image_url,core_image_public_id," +
        "product_image_url,product_image_public_id,frame_sha256,metadata",
      roles: ["core", "product"],
    },
    {
      table: INVENTORY_TABLE,
      select: "id,event_id,gateway_id,captured_at,image_url,image_public_id,frame_sha256,metadata",
      roles: ["image"],
    },
    {
      table: PHOTO_DRAFT_TABLE,
      select: "id,event_id,gateway_id,captured_at,image_url,image_public_id,frame_sha256,metadata",
      roles: ["image"],
    },
  ];
  const reportByKey = new Map(
    localEvidence.items.map((item) => [`${item.table}:${item.event_id}`, item]),
  );
  for (const config of tableConfigs) {
    const pending = [...reportByKey.values()].filter((item) => item.table === config.table);
    for (let start = 0; start < pending.length; start += 8) {
      await Promise.all(pending.slice(start, start + 8).map(async (reportItem) => {
      const { data: rawRow, error } = await supabase.from(config.table)
        .select(config.select)
        .eq("event_id", reportItem.event_id)
        .lte("captured_at", cutoff)
        .maybeSingle();
      if (error) {
        errors.push(`${config.table}:${reportItem.event_id}:select:${error.message}`);
        return;
      }
      if (!rawRow) return;
      const row = rawRow as unknown as Record<string, unknown>;
      if (Date.parse(String(row.captured_at ?? "")) !== Date.parse(reportItem.captured_at)) {
        errors.push("captured_at_mismatch:" + config.table + ":" + reportItem.event_id);
        return;
      }
      const metadata = row.metadata && typeof row.metadata === "object"
        ? { ...(row.metadata as Record<string, unknown>) }
        : {};
      const storedReleasedRoles = metadata.image_retention_released_roles &&
          typeof metadata.image_retention_released_roles === "object" &&
          !Array.isArray(metadata.image_retention_released_roles)
        ? { ...(metadata.image_retention_released_roles as Record<string, unknown>) }
        : {};
      const updates: Record<string, unknown> = {};
      let rowChanged = false;
      const releasedForRow: Array<Record<string, string>> = [];
      for (const role of config.roles) {
        const prefix = role === "core" ? "core_image" : role === "product"
          ? "product_image"
          : "image";
        const imageUrl = String(
          row[`${prefix}_url`] ?? (role === "core" ? row.image_url : "") ?? "",
        );
        const publicId = String(
          row[`${prefix}_public_id`] ?? (role === "core" ? row.image_public_id : "") ?? "",
        );
        const evidence = reportItem.roles[role];
        if (!evidence) continue;
        const priorRelease = storedReleasedRoles[role];
        if (priorRelease && typeof priorRelease === "object") {
          const priorHash = String((priorRelease as Record<string, unknown>).sha256 ?? "")
            .trim().toLowerCase();
          if (priorHash === evidence.sha256) {
            // The DB update may have committed after Cloudinary was destroyed,
            // but before the worker could prune its local file. Re-emit the
            // release without downloading or destroying the remote object a
            // second time. This makes maintenance idempotent across crashes.
            if (imageUrl || publicId) {
              updates[`${prefix}_url`] = null;
              updates[`${prefix}_public_id`] = null;
              if (config.table === MEASUREMENT_TABLE && role === "core") {
                updates.image_url = null;
                updates.image_public_id = null;
              }
              rowChanged = true;
            }
            releasedForRow.push({
              table: config.table,
              event_id: reportItem.event_id,
              role,
              sha256: evidence.sha256,
            });
            continue;
          }
          errors.push(`${config.table}:${row.id}:${role}:released_evidence_mismatch`);
          continue;
        }
        const hasCloudinaryPair = Boolean(cloudinaryUrl(imageUrl) && publicId);
        if (!hasCloudinaryPair) {
          const localOnly = rowHasLocalBackupCommit(row) && (
            metadata.cloudinary_pending === true ||
            metadata.local_backup_only === true ||
            (!imageUrl && !publicId)
          );
          if (!localOnly || imageUrl) {
            if (localOnly && imageUrl && !publicId) {
              errors.push(`${config.table}:${row.id}:${role}:missing_cloudinary_public_id`);
            }
            continue;
          }
          checked += 1;
          if (!evidenceRoleMatches(config.table, row, role, evidence)) {
            errors.push(`${config.table}:${row.id}:${role}:local_evidence_mismatch`);
            continue;
          }
          verified += 1;
          if (publicId) {
            try {
              await destroyCloudinary(publicId);
              deleted += 1;
            } catch (deleteError) {
              errors.push(
                `${config.table}:${row.id}:${role}:` +
                  (deleteError instanceof Error ? deleteError.message : "delete_failed"),
              );
              continue;
            }
          }
          updates[`${prefix}_url`] = null;
          updates[`${prefix}_public_id`] = null;
          if (config.table === MEASUREMENT_TABLE && role === "core") {
            updates.image_url = null;
            updates.image_public_id = null;
          }
          storedReleasedRoles[role] = {
            sha256: evidence.sha256,
            released_at: new Date().toISOString(),
            cloudinary: "not_uploaded",
          };
          releasedForRow.push({
            table: config.table,
            event_id: reportItem.event_id,
            role,
            sha256: evidence.sha256,
          });
          rowChanged = true;
          continue;
        }
        checked += 1;
        if (!evidenceRoleMatches(config.table, row, role, evidence)) {
          errors.push(`${config.table}:${row.id}:${role}:local_evidence_mismatch`);
          continue;
        }
        verified += 1;
        try {
          await destroyCloudinary(publicId);
          updates[`${prefix}_url`] = null;
          updates[`${prefix}_public_id`] = null;
          if (config.table === MEASUREMENT_TABLE && role === "core") {
            updates.image_url = null;
            updates.image_public_id = null;
          }
          storedReleasedRoles[role] = {
            sha256: evidence.sha256,
            released_at: new Date().toISOString(),
          };
          releasedForRow.push({
            table: config.table,
            event_id: reportItem.event_id,
            role,
            sha256: evidence.sha256,
          });
          deleted += 1;
          rowChanged = true;
        } catch (deleteError) {
          errors.push(
            `${config.table}:${row.id}:${role}:` +
              (deleteError instanceof Error ? deleteError.message : "delete_failed"),
          );
        }
      }
      metadata.backup_last_checked_at = new Date().toISOString();
      if (rowChanged) {
        metadata.cloudinary_deleted_at = new Date().toISOString();
        metadata.image_retention_released = true;
        metadata.image_retention_released_roles = storedReleasedRoles;
      }
      const { error: updateError } = await supabase.from(config.table)
        .update({ ...updates, metadata })
        .eq("event_id", reportItem.event_id);
      if (updateError) {
        errors.push(`${config.table}:${row.id}:update:${updateError.message}`);
      } else if (releasedForRow.length) {
        // Only authorize local deletion after the row records the remote
        // release. If this update fails, the next run can retry the
        // idempotent Cloudinary destroy while retaining the local evidence.
        released.push(...releasedForRow);
      }
      }));
    }
  }
  return {
    checked,
    verified,
    cloudinary_deleted: deleted,
    errors: errors.slice(0, 100),
    retention_days: retentionDays,
    cutoff,
    backup_provider: LOCAL_BACKUP_PROVIDER,
    metadata_only: true,
    released,
  };
}

async function uploadToCloudinary(
  image: Uint8Array,
  publicId: string,
): Promise<CloudinaryUpload> {
  const cloudName = Deno.env.get("CLOUDINARY_CLOUD_NAME");
  const apiKey = Deno.env.get("CLOUDINARY_API_KEY");
  const apiSecret = Deno.env.get("CLOUDINARY_API_SECRET");
  if (!cloudName || !apiKey || !apiSecret) {
    throw new Error("cloudinary_not_configured");
  }

  const form = new FormData();
  form.append(
    "file",
    new Blob([Uint8Array.from(image)], { type: "image/jpeg" }),
    `${publicId.split("/").at(-1)}.jpg`,
  );
  form.append("public_id", publicId);
  // Public IDs are deterministic event keys. Overwrite makes a retry after a
  // successful upload/failed DB insert idempotent instead of treating the
  // existing Cloudinary object as a permanent failure.
  form.append("overwrite", "true");

  const response = await fetch(
    `https://api.cloudinary.com/v1_1/${encodeURIComponent(cloudName)}/image/upload`,
    {
      method: "POST",
      headers: { authorization: `Basic ${btoa(`${apiKey}:${apiSecret}`)}` },
      body: form,
    },
  );
  let result: Record<string, unknown> = {};
  try {
    result = await response.json() as Record<string, unknown>;
  } catch {
    // The status below remains the authoritative failure signal.
  }
  if (!response.ok) {
    throw new Error(`cloudinary_upload_failed:${response.status}`);
  }
  const secureUrl = typeof result.secure_url === "string" ? result.secure_url : "";
  const returnedPublicId = typeof result.public_id === "string" ? result.public_id : "";
  if (!secureUrl || !returnedPublicId) {
    throw new Error("cloudinary_invalid_response");
  }
  return { publicId: returnedPublicId, secureUrl };
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST" && request.method !== "GET") {
    return json(405, { ok: false, error: "method_not_allowed" });
  }

  const expectedToken = Deno.env.get("DEVICE_INGEST_TOKEN");
  const suppliedToken = request.headers.get("x-device-token");
  if (!expectedToken) {
    return json(500, { ok: false, error: "server_not_configured" });
  }
  if (!suppliedToken || suppliedToken !== expectedToken) {
    return json(401, { ok: false, error: "unauthorized" });
  }

  const requestUrl = new URL(request.url);
  const action = requestUrl.searchParams.get("action") ?? "";

  if (request.method === "GET" && (action === "codex-auth" || action === "encrypted-secret")) {
    const name = requestUrl.searchParams.get("name")?.trim() ?? "";
    if (!ID_PATTERN.test(name)) {
      return json(422, { ok: false, error: "invalid_secret_name" });
    }
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { data, error } = await supabase
      .from(SECRET_TABLE)
      .select("encrypted_value")
      .eq("name", name)
      .maybeSingle();
    if (error) {
      return json(500, { ok: false, error: "secret_read_failed" });
    }
    return json(200, {
      ok: true,
      found: Boolean(data),
      encrypted_value: data?.encrypted_value ?? null,
    });
  }

  if (request.method === "GET" && action === "weighing-batches") {
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const workDate = (requestUrl.searchParams.get("work_date") ?? "").trim();
    const shift = (requestUrl.searchParams.get("shift") ?? "").trim();
    const machine = (requestUrl.searchParams.get("machine") ?? "").trim();
    const productionOrder = (requestUrl.searchParams.get("production_order") ?? "").trim();
    const requestedLimit = Number(requestUrl.searchParams.get("limit") ?? "50");
    const limit = Number.isInteger(requestedLimit)
      ? Math.max(1, Math.min(requestedLimit, 200))
      : 50;
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    let query = supabase
      .from(WEIGH_BATCH_TABLE)
      .select("*")
      .eq("trang_thai", "confirmed")
      .order("xac_nhan_luc", { ascending: false })
      .limit(limit);
    if (workDate) query = query.eq("ngay_can", workDate);
    if (shift) query = query.eq("ca", shift);
    if (machine) query = query.eq("may", machine);
    if (productionOrder) query = query.eq("lenh_san_xuat", productionOrder);
    const { data, error } = await query;
    if (error) {
      return json(500, {
        ok: false,
        error: "weighing_batch_list_failed",
        detail: error.message,
      });
    }
    return json(200, {
      ok: true,
      source: WEIGH_BATCH_TABLE,
      items: data ?? [],
    });
  }

  if (request.method === "GET" && action === "production-orders") {
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const workDate = (requestUrl.searchParams.get("work_date") ?? "").trim();
    const shift = (requestUrl.searchParams.get("shift") ?? "").trim();
    const machine = (requestUrl.searchParams.get("machine") ?? "").trim();
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const configuredTable = (Deno.env.get("PRODUCTION_ORDER_TABLE") ?? "").trim();
    const tables = [
      configuredTable,
      "lenh_san_xuat",
      "Lenh_San_Xuat",
      "Lệnh Sản xuất",
      "Lệnh sản xuất",
      "lenh_sx",
      "production_orders",
      "lsx",
    ].filter((name, index, list) => name && list.indexOf(name) === index);
    const orderKeys = [
      "production_order",
      "ma_lsx",
      "so_lsx",
      "so_lenh",
      "lenh_sx",
      "ma_lenh",
      "ten_lsx",
      "order_code",
      "order_no",
      "lsx",
      "ma",
      "code",
    ];
    const dateKeys = [
      "work_date",
      "ngay",
      "ngay_lsx",
      "ngay_san_xuat",
      "ngay_sx",
      "date",
      "bat_dau",
      "ngay_bat_dau",
    ];
    const shiftKeys = ["shift", "ca", "ca_lam_viec", "ca_sx", "shift_code"];
    const machineKeys = [
      "machine",
      "may",
      "máy",
      "ten_may",
      "ma_may",
      "loai_may",
      "machine_name",
    ];
    const normalizeDate = (value: unknown): string => {
      const text = String(value ?? "").trim();
      if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
      const match = text.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/);
      if (!match) return "";
      const first = Number(match[1]);
      const second = Number(match[2]);
      const year = Number(match[3]);
      let day: number;
      let month: number;
      if (first > 12 && second <= 12) {
        day = first;
        month = second;
      } else if (second > 12 && first <= 12) {
        day = second;
        month = first;
      } else {
        day = first;
        month = second;
      }
      if (month > 12 || day > 31) return "";
      return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    };
    const orderCode = (row: Record<string, unknown>): string => {
      const lowered = Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key.trim().toLowerCase(), value]),
      );
      for (const key of orderKeys) {
        const text = String(lowered[key] ?? "").trim();
        if (text) return text.slice(0, 80);
      }
      for (const [key, value] of Object.entries(lowered)) {
        if (/(lsx|lenh|order)/i.test(key)) {
          const text = String(value ?? "").trim();
          if (text) return text.slice(0, 80);
        }
      }
      return "";
    };
    const rowField = (
      row: Record<string, unknown>,
      names: string[],
      fuzzyTokens: string[] = [],
    ): string => {
      const lowered = Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key.trim().toLowerCase(), value]),
      );
      for (const name of names) {
        const text = String(lowered[name] ?? "").trim();
        if (text) return text.slice(0, 80);
      }
      for (const [key, value] of Object.entries(lowered)) {
        if (fuzzyTokens.some((token) => key.includes(token))) {
          const text = String(value ?? "").trim();
          if (text) return text.slice(0, 80);
        }
      }
      return "";
    };
    const rawTag = (raw: string, name: string): string => {
      const match = raw.match(new RegExp(`(?:^|; )\\s*${name}=([^;]+)`));
      return match ? match[1].trim() : "";
    };
    const sourceValue = (
      row: Record<string, unknown>,
      field: string,
      tag: string,
    ): string => {
      const direct = String(row[field] ?? "").trim();
      if (direct) return direct;
      const metadata = row.metadata;
      if (metadata && typeof metadata === "object") {
        const meta = metadata as Record<string, unknown>;
        const metaValue = String(meta[field] ?? "").trim();
        if (metaValue) return metaValue;
        const raw = String(meta.weight_raw ?? row.weight_raw ?? "");
        const tagged = rawTag(raw, tag);
        if (tagged) return tagged;
      }
      return rawTag(String(row.weight_raw ?? ""), tag);
    };
    const orderDate = (row: Record<string, unknown>): string => {
      const tagged = sourceValue(row, "work_date", "SOURCE_DATE");
      if (tagged) return normalizeDate(tagged);
      const lowered = Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key.trim().toLowerCase(), value]),
      );
      for (const key of dateKeys) {
        const normalized = normalizeDate(lowered[key]);
        if (normalized) return normalized;
      }
      const capturedAt = String(row.captured_at ?? "");
      if (/^\d{4}-\d{2}-\d{2}/.test(capturedAt)) return capturedAt.slice(0, 10);
      return "";
    };
    const orderShift = (row: Record<string, unknown>): string =>
      sourceValue(row, "shift", "SOURCE_SHIFT") || rowField(row, shiftKeys);
    const orderMachine = (row: Record<string, unknown>): string =>
      sourceValue(row, "machine", "SOURCE_MACHINE") || rowField(row, machineKeys);
    const rowMatchesFilters = (row: Record<string, unknown>): boolean => {
      if (workDate) {
        const rowDate = orderDate(row);
        if (rowDate && rowDate !== workDate) return false;
      }
      if (shift) {
        const rowShift = orderShift(row);
        if (rowShift && rowShift !== shift) return false;
      }
      if (machine) {
        const rowMachine = orderMachine(row);
        if (rowMachine && rowMachine !== machine) return false;
      }
      return true;
    };
    const uniqueOrders = (rows: Record<string, unknown>[]): string[] => {
      const matching: string[] = [];
      for (const row of rows) {
        const code = orderCode(row);
        if (!code || !rowMatchesFilters(row)) continue;
        matching.push(code);
      }
      return [...new Set(matching.map((item) => item.trim()).filter(Boolean))].sort(
        (left, right) => left.localeCompare(right, "vi"),
      );
    };

    for (const table of tables) {
      const { data, error } = await supabase.from(table).select("*").limit(1000);
      if (error || !Array.isArray(data)) continue;
      const orders = uniqueOrders(data as Record<string, unknown>[]);
      if (orders.length) {
        return json(200, {
          ok: true,
          source: table,
          work_date: workDate,
          shift: shift || null,
          machine: machine || null,
          orders,
        });
      }
    }

    const { data: measurements, error: measurementError } = await supabase
      .from(MEASUREMENT_TABLE)
      .select("captured_at,metadata")
      .order("captured_at", { ascending: false })
      .limit(200);
    if (measurementError) {
      return json(500, { ok: false, error: "production_order_list_failed" });
    }
    const measurementRows = (measurements ?? []).map((item) => {
      const row = item as Record<string, unknown>;
      const metadata = row.metadata !== null && typeof row.metadata === "object"
        ? row.metadata as Record<string, unknown>
        : {};
      return {
        captured_at: row.captured_at,
        work_date: metadata.work_date,
        shift: metadata.shift,
        machine: metadata.machine,
        production_order: metadata.production_order,
        weight_raw: metadata.weight_raw,
        metadata,
      };
    });
    return json(200, {
      ok: true,
      source: MEASUREMENT_TABLE,
      work_date: workDate,
      shift: shift || null,
      machine: machine || null,
      orders: uniqueOrders(measurementRows),
    });
  }

  if (request.method === "GET") {
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const params = new URL(request.url).searchParams;
    const requestedLimit = Number(params.get("limit") ?? "50");
    const requestedOffset = Number(params.get("offset") ?? "0");
    const limit = Number.isInteger(requestedLimit)
      ? Math.max(1, Math.min(requestedLimit, 1000))
      : 50;
    const offset = Number.isInteger(requestedOffset)
      ? Math.max(0, Math.min(requestedOffset, 50000))
      : 0;
    const dateFrom = (params.get("date_from") ?? "").trim();
    const dateTo = (params.get("date_to") ?? "").trim();
    const workDate = (params.get("work_date") ?? "").trim();
    const shift = (params.get("shift") ?? "").trim();
    const machine = (params.get("machine") ?? "").trim();
    const productionOrder = (params.get("production_order") ?? "").trim();
    const qrCode = (params.get("qr_code") ?? "").trim();
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    let query = supabase
      .from(MEASUREMENT_TABLE)
      .select(EVENT_LIST_SELECT, { count: "exact" })
      .order("captured_at", { ascending: false })
      .range(offset, offset + limit - 1);
    if (workDate) {
      query = query.eq("metadata->>work_date", workDate);
    } else if (dateFrom) {
      query = query.gte("metadata->>work_date", dateFrom);
    }
    if (dateTo) {
      query = query.lte("metadata->>work_date", dateTo);
    }
    if (shift) {
      query = query.eq("metadata->>shift", shift);
    }
    if (machine) {
      query = query.eq("metadata->>machine", machine);
    }
    if (productionOrder) {
      query = query.eq("metadata->>production_order", productionOrder);
    }
    if (qrCode) {
      query = query.ilike("qr_code", `%${qrCode}%`);
    }
    const { data, error, count } = await query;
    if (error) {
      return json(500, { ok: false, error: "measurement_list_failed" });
    }
    return json(200, {
      ok: true,
      source: MEASUREMENT_TABLE,
      offset,
      limit,
      total_count: count ?? (data ?? []).length,
      count_exact: count !== null,
      items: data ?? [],
    });
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return json(400, { ok: false, error: "invalid_json" });
  }

  if (body.action === "backup_maintenance") {
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const requestedDays = Number(body.retention_days ?? 7);
    const retentionDays = Number.isInteger(requestedDays)
      ? Math.max(DEFAULT_CLOUDINARY_RETENTION_DAYS, Math.min(requestedDays, 30))
      : DEFAULT_CLOUDINARY_RETENTION_DAYS;
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const localEvidence = parseLocalEvidence(body.local_evidence);
    const result = await runBackupMaintenance(supabase, retentionDays, localEvidence);
    return json(200, { ok: true, action: "backup_maintenance", ...result });
  }

  if (body.action === "confirm_weighing_batch") {
    const workDate = typeof body.work_date === "string" ? body.work_date.trim() : "";
    const shift = typeof body.shift === "string" ? body.shift.trim().slice(0, 80) : "";
    const machine = typeof body.machine === "string" ? body.machine.trim().slice(0, 80) : "";
    const productionOrder = typeof body.production_order === "string"
      ? body.production_order.trim().slice(0, 80)
      : "";
    const confirmedBy = typeof body.confirmed_by === "string"
      ? body.confirmed_by.trim().slice(0, 120)
      : "";
    const milestone = Number(body.milestone);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(workDate) || Number.isNaN(Date.parse(`${workDate}T00:00:00Z`))) {
      return json(422, { ok: false, error: "invalid_work_date" });
    }
    if (!shift || !productionOrder) {
      return json(422, { ok: false, error: "missing_weighing_source" });
    }
    if (!Number.isInteger(milestone) || milestone < 10 || milestone % 10 !== 0) {
      return json(422, { ok: false, error: "invalid_weighing_milestone" });
    }
    const batchNumber = milestone / 10;
    const batchKey = [workDate, shift, machine, productionOrder, batchNumber].join("|");
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { data: existingBatch, error: existingError } = await supabase
      .from(WEIGH_BATCH_TABLE)
      .select("*")
      .eq("batch_key", batchKey)
      .maybeSingle();
    if (existingError) {
      return json(500, {
        ok: false,
        error: "weighing_batch_lookup_failed",
        detail: existingError.message,
      });
    }
    if (existingBatch) {
      return json(200, { ok: true, duplicate: true, item: existingBatch });
    }
    if (batchNumber > 1) {
      const previousBatchKey = [
        workDate,
        shift,
        machine,
        productionOrder,
        batchNumber - 1,
      ].join("|");
      const { data: previousBatch, error: previousBatchError } = await supabase
        .from(WEIGH_BATCH_TABLE)
        .select("id")
        .eq("batch_key", previousBatchKey)
        .eq("trang_thai", "confirmed")
        .maybeSingle();
      if (previousBatchError) {
        return json(500, {
          ok: false,
          error: "previous_weighing_batch_lookup_failed",
          detail: previousBatchError.message,
        });
      }
      if (!previousBatch) {
        return json(409, {
          ok: false,
          error: "previous_weighing_batch_not_confirmed",
          message: `Phải xác nhận đợt ${batchNumber - 1} trước`,
        });
      }
    }

    const offset = (batchNumber - 1) * 10;
    let rowsQuery = supabase
      .from(MEASUREMENT_TABLE)
      .select(
        "event_id,qr_code,weight,tare_weight,net_weight,unit,captured_at,error_status,error_reason,metadata",
      )
      .eq("metadata->>work_date", workDate)
      .eq("metadata->>shift", shift)
      .eq("metadata->>production_order", productionOrder)
      .order("captured_at", { ascending: true })
      .range(offset, offset + 9);
    if (machine) rowsQuery = rowsQuery.eq("metadata->>machine", machine);
    const { data: batchRows, error: rowsError } = await rowsQuery;
    if (rowsError) {
      return json(500, {
        ok: false,
        error: "weighing_batch_rows_failed",
        detail: rowsError.message,
      });
    }
    if (!Array.isArray(batchRows) || batchRows.length !== 10) {
      return json(409, {
        ok: false,
        error: "weighing_batch_not_synced",
        message: "Chưa đủ 10 cuộn đã đồng bộ Supabase cho đợt này",
        expected: 10,
        found: Array.isArray(batchRows) ? batchRows.length : 0,
      });
    }
    const products = batchRows.map((row, index) => {
      const item = row as Record<string, unknown>;
      const metadata = item.metadata !== null && typeof item.metadata === "object"
        ? item.metadata as Record<string, unknown>
        : {};
      const qrCode = String(item.qr_code ?? "").trim();
      const productCode = qrCode.includes("_") ? qrCode.split("_", 1)[0].trim() : qrCode;
      const status = String(item.error_status ?? metadata.error_status ?? "ok") === "error"
        ? "error"
        : "ok";
      return {
        stt: index + 1,
        event_id: item.event_id,
        qr_code: qrCode,
        ma_san_pham: productCode,
        can_loi: Number(metadata.core_weight ?? item.tare_weight ?? 0),
        can_san_pham: Number(metadata.product_weight ?? item.weight ?? 0),
        trong_luong_nvl: Number(item.net_weight ?? 0),
        don_vi: item.unit,
        can_luc: item.captured_at,
        trang_thai_loi: status,
        ly_do_loi: status === "error"
          ? String(item.error_reason ?? metadata.error_reason ?? "").trim()
          : "",
      };
    });
    const productCodes = [...new Set(products.map((item) => item.ma_san_pham).filter(Boolean))];
    const rowToInsert = {
      batch_key: batchKey,
      dot_can: batchNumber,
      moc_so_luong: milestone,
      ma_san_pham: productCodes.join(", ") || "--",
      so_luong: 10,
      ngay_can: workDate,
      gio_bat_dau: products[0].can_luc,
      gio_ket_thuc: products[products.length - 1].can_luc,
      ca: shift,
      may: machine,
      lenh_san_xuat: productionOrder,
      danh_sach_san_pham: products,
      trang_thai: "confirmed",
      xac_nhan_boi: confirmedBy,
      xac_nhan_luc: new Date().toISOString(),
    };
    const { data: insertedBatch, error: insertBatchError } = await supabase
      .from(WEIGH_BATCH_TABLE)
      .insert(rowToInsert)
      .select("*")
      .single();
    if (insertBatchError || !insertedBatch) {
      if (insertBatchError?.code === "23505") {
        const { data: racedBatch } = await supabase
          .from(WEIGH_BATCH_TABLE)
          .select("*")
          .eq("batch_key", batchKey)
          .maybeSingle();
        if (racedBatch) {
          return json(200, { ok: true, duplicate: true, item: racedBatch });
        }
      }
      return json(500, {
        ok: false,
        error: "weighing_batch_insert_failed",
        detail: insertBatchError?.message || "empty_insert",
      });
    }
    return json(201, { ok: true, duplicate: false, item: insertedBatch });
  }

  if (body.action === "delete_measurement") {
    const eventId = normalizeEventId(body.event_id);
    if (!ID_PATTERN.test(eventId)) {
      return json(422, { ok: false, error: "invalid_event_id" });
    }
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    let measurementDeleted = false;
    const byEvent = await supabase
      .from(MEASUREMENT_TABLE)
      .delete()
      .eq("event_id", eventId)
      .select("id,event_id");
    if (byEvent.error) {
      return json(500, { ok: false, error: "measurement_delete_failed" });
    }
    if (!byEvent.error && Array.isArray(byEvent.data) && byEvent.data.length) {
      measurementDeleted = true;
    } else {
      const byId = await supabase
        .from(MEASUREMENT_TABLE)
        .delete()
        .eq("id", eventId)
        .select("id,event_id");
      if (!byId.error && Array.isArray(byId.data) && byId.data.length) {
        measurementDeleted = true;
      } else if (byId.error) {
        return json(500, { ok: false, error: "measurement_delete_failed" });
      }
    }
    const photoDrafts = await supabase
      .from(PHOTO_DRAFT_TABLE)
      .delete()
      .or(`parent_event_id.eq.${eventId},event_id.eq.${eventId}`)
      .select("id,event_id,parent_event_id");
    if (photoDrafts.error) {
      return json(500, { ok: false, error: "photo_draft_delete_failed" });
    }
    const photoDraftsDeleted = Array.isArray(photoDrafts.data) ? photoDrafts.data.length : 0;
    if (!measurementDeleted && photoDraftsDeleted === 0) {
      return json(404, { ok: false, error: "measurement_not_found" });
    }
    return json(200, {
      ok: true,
      deleted: true,
      event_id: eventId,
      measurement_deleted: measurementDeleted,
      photo_drafts_deleted: photoDraftsDeleted,
    });
  }

  if (body.action === "update_measurement") {
    const eventId = normalizeEventId(body.event_id);
    if (!ID_PATTERN.test(eventId)) {
      return json(422, { ok: false, error: "invalid_event_id" });
    }
    const qrCode = typeof body.qr_code === "string" ? body.qr_code.trim() : "";
    const coreWeight = Number(body.core_weight ?? body.weight);
    const productWeight = Number(body.product_weight);
    const workDate = typeof body.work_date === "string" ? body.work_date.trim() : "";
    const shift = typeof body.shift === "string" ? body.shift.trim() : "";
    const machine = typeof body.machine === "string" ? body.machine.trim() : "";
    const productionOrder = typeof body.production_order === "string"
      ? body.production_order.trim()
      : "";
    const requestedErrorStatus = typeof body.error_status === "string"
      ? body.error_status.trim().toLowerCase()
      : "ok";
    const errorStatus = requestedErrorStatus === "error" ? "error" : "ok";
    const errorReason = errorStatus === "error" && typeof body.error_reason === "string"
      ? body.error_reason.trim().slice(0, 500)
      : "";
    if (!qrCode || qrCode.length > 200) {
      return json(422, { ok: false, error: "invalid_qr_code" });
    }
    if (!Number.isFinite(coreWeight) || coreWeight < 0) {
      return json(422, { ok: false, error: "invalid_core_weight" });
    }
    if (!Number.isFinite(productWeight) || productWeight < 0) {
      return json(422, { ok: false, error: "invalid_product_weight" });
    }
    if (requestedErrorStatus !== errorStatus || (errorStatus === "error" && !errorReason)) {
      return json(422, { ok: false, error: "invalid_error_status" });
    }
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const byEventId = await supabase
      .from(MEASUREMENT_TABLE)
      .select(EVENT_SELECT)
      .eq("event_id", eventId)
      .maybeSingle();
    let existing = (!byEventId.error && byEventId.data)
      ? byEventId.data as unknown as Record<string, unknown>
      : null;
    if (!existing) {
      const numericId = /^\d+$/.test(eventId) ? Number(eventId) : NaN;
      const byId = await supabase
        .from(MEASUREMENT_TABLE)
        .select(EVENT_SELECT)
        .eq("id", Number.isFinite(numericId) ? numericId : eventId)
        .maybeSingle();
      if (!byId.error && byId.data) {
        existing = byId.data as unknown as Record<string, unknown>;
      }
    }
    if (!existing) {
      return json(404, { ok: false, error: "measurement_not_found" });
    }
    if (coreWeight > productWeight) {
      return json(422, {
        ok: false,
        error: "core_exceeds_product_weight",
        message: "Cân lõi phải ≤ cân SP (ràng buộc bảng can_tu_dong).",
      });
    }
    const metadata = existing.metadata !== null && typeof existing.metadata === "object"
      ? { ...(existing.metadata as Record<string, unknown>) }
      : {};
    metadata.core_weight = coreWeight;
    metadata.product_weight = productWeight;
    metadata.error_status = errorStatus;
    metadata.error_reason = errorReason;
    if (workDate) metadata.work_date = workDate;
    if (shift) metadata.shift = shift;
    if (machine) metadata.machine = machine;
    if (productionOrder) metadata.production_order = productionOrder;
    const raw = typeof metadata.weight_raw === "string" ? metadata.weight_raw : "";
    metadata.weight_raw = raw.includes("PRODUCT_WEIGHT=")
      ? raw.replace(/(?:^|; )PRODUCT_WEIGHT=[^;]*/g, `; PRODUCT_WEIGHT=${productWeight}`).replace(/^; /, "")
      : `${raw ? `${raw}; ` : ""}PRODUCT_WEIGHT=${productWeight}`;
    const rowId = typeof existing.id === "number" || typeof existing.id === "string"
      ? existing.id
      : null;
    if (rowId === null || rowId === "") {
      return json(500, { ok: false, error: "measurement_update_failed", detail: "missing_row_id" });
    }
    const { data: updated, error: updateError } = await supabase
      .from(MEASUREMENT_TABLE)
      .update({
        qr_code: qrCode,
        weight: productWeight,
        tare_weight: coreWeight,
        error_status: errorStatus,
        error_reason: errorReason,
        metadata,
      })
      .eq("id", rowId)
      .select(EVENT_SELECT)
      .maybeSingle();
    if (updateError || !updated) {
      return json(500, {
        ok: false,
        error: "measurement_update_failed",
        detail: updateError?.message || "empty_update",
        code: updateError?.code || null,
      });
    }
    return json(200, { ok: true, updated: true, item: updated });
  }

  if (body.action === "codex-auth" || body.action === "encrypted-secret") {
    const name = typeof body.name === "string" ? body.name.trim() : "";
    const encryptedValue = typeof body.encrypted_value === "string"
      ? body.encrypted_value.trim()
      : "";
    if (!ID_PATTERN.test(name)) {
      return json(422, { ok: false, error: "invalid_secret_name" });
    }
    if (!encryptedValue || encryptedValue.length > 16384) {
      return json(422, { ok: false, error: "invalid_encrypted_value" });
    }
    const supabaseUrl = Deno.env.get("SUPABASE_URL");
    const serviceKey = getSupabaseAdminKey();
    if (!supabaseUrl || !serviceKey) {
      return json(500, { ok: false, error: "supabase_not_configured" });
    }
    const supabase = createClient(supabaseUrl, serviceKey, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const { error } = await supabase.from(SECRET_TABLE).upsert(
      {
        name,
        encrypted_value: encryptedValue,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "name" },
    );
    if (error) {
      return json(500, { ok: false, error: "secret_write_failed" });
    }
    return json(200, { ok: true, stored: true });
  }

  const workflow = typeof body.workflow === "string" ? body.workflow.trim() : "production";
  const inventoryCheck = workflow === "inventory_check";
  const photoDraft = workflow === "photo_draft";
  if (!inventoryCheck && !photoDraft && workflow !== "production" && workflow !== "") {
    return json(422, { ok: false, error: "invalid_workflow" });
  }
  const eventId = typeof body.event_id === "string" ? body.event_id : "";
  const parentEventId = typeof body.parent_event_id === "string"
    ? body.parent_event_id.trim()
    : eventId;
  const captureKind = typeof body.capture_kind === "string"
    ? body.capture_kind.trim().toLowerCase()
    : "core";
  const captureRound = typeof body.capture_round === "number"
    ? body.capture_round
    : 0;
  const qrCode = typeof body.qr_code === "string" ? body.qr_code.trim() : "";
  const productCode = typeof body.product_code === "string"
    ? body.product_code.trim()
    : qrCode;
  const suppliedGatewayId = typeof body.gateway_id === "string" ? body.gateway_id.trim() : null;
  const legacyDeviceId = typeof body.device_id === "string" ? body.device_id.trim() : null;
  const gatewayId = suppliedGatewayId || legacyDeviceId || "";
  const stationId = typeof body.station_id === "string" ? body.station_id.trim() : null;
  const cameraId = typeof body.camera_id === "string" ? body.camera_id.trim() : null;
  const analysisId = typeof body.analysis_id === "string" ? body.analysis_id.trim() : null;
  const frameSha256 = typeof body.frame_sha256 === "string"
    ? body.frame_sha256.trim().toLowerCase()
    : null;
  const payloadHash = typeof body.payload_hash === "string"
    ? body.payload_hash.trim().toLowerCase()
    : null;
  const unit = typeof body.unit === "string" ? body.unit : "";
  const weight = typeof body.weight === "number" ? body.weight : Number.NaN;
  const coreWeight = typeof body.core_weight === "number"
    ? body.core_weight
    : Number.NaN;
  const inventoryTareWeight = typeof body.tare_weight === "number"
    ? body.tare_weight
    : Number.NaN;
  const productWeight = typeof body.product_weight === "number"
    ? body.product_weight
    : Number.NaN;
  const capturedAt = typeof body.captured_at === "string" ? body.captured_at : "";
  const imageBase64 = typeof body.image_base64 === "string" ? body.image_base64 : "";
  const productImageBase64 = typeof body.product_image_base64 === "string"
    ? body.product_image_base64
    : "";
  const imageRole = typeof body.image_role === "string" ? body.image_role : "";
  const weightSource = typeof body.weight_source === "string"
    ? body.weight_source.slice(0, 100)
    : "unknown";
  const qrSource = typeof body.qr_source === "string" ? body.qr_source.slice(0, 100) : "unknown";
  const weightRaw = typeof body.weight_raw === "string" ? body.weight_raw.slice(0, 1000) : "";
  const weightStable = body.weight_stable === true;
  const sourceTag = (name: string, maxLength = 80): string => {
    const match = weightRaw.match(new RegExp(`(?:^|; )\\s*${name}=([^;]+)`));
    return match ? match[1].trim().slice(0, maxLength) : "";
  };
  const workDate = typeof body.work_date === "string"
    ? body.work_date.trim().slice(0, 10)
    : sourceTag("SOURCE_DATE");
  const shift = typeof body.shift === "string"
    ? body.shift.trim().slice(0, 80)
    : sourceTag("SOURCE_SHIFT");
  const machine = typeof body.machine === "string"
    ? body.machine.trim().slice(0, 80)
    : sourceTag("SOURCE_MACHINE");
  const productionOrder = typeof body.production_order === "string"
    ? body.production_order.trim().slice(0, 80)
    : sourceTag("SOURCE_PRODUCTION_ORDER");
  const biWeightRaw = sourceTag("BI_WEIGHT");
  const biWeightParsed = Number(biWeightRaw);
  const biWeight = Number.isFinite(biWeightParsed) && biWeightParsed >= 0
    ? biWeightParsed
    : 0.16;
  const taggedErrorStatus = sourceTag("ERROR_STATUS").toLowerCase();
  const requestedErrorStatus = typeof body.error_status === "string"
    ? body.error_status.trim().toLowerCase()
    : taggedErrorStatus || "ok";
  const errorStatus = requestedErrorStatus === "error" ? "error" : "ok";
  const errorReason = errorStatus === "error"
    ? (typeof body.error_reason === "string"
      ? body.error_reason.trim().slice(0, 500)
      : sourceTag("ERROR_REASON", 500))
    : "";

  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(eventId)) {
    return json(422, { ok: false, error: "invalid_event_id" });
  }
  if (
    photoDraft &&
    (!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(parentEventId) ||
      !["core", "product", "inventory"].includes(captureKind) ||
      !Number.isInteger(captureRound) || captureRound < 0 || captureRound > 3)
  ) {
    return json(422, { ok: false, error: "invalid_photo_event_slot" });
  }
  if (
    (!photoDraft && !qrCode) || qrCode.length > 512 ||
    (inventoryCheck && productCode !== qrCode)
  ) {
    return json(422, { ok: false, error: "invalid_qr_code" });
  }
  if (body.gateway_id !== undefined && body.gateway_id !== null && !suppliedGatewayId) {
    return json(422, { ok: false, error: "invalid_gateway_id" });
  }
  if (body.device_id !== undefined && body.device_id !== null && !legacyDeviceId) {
    return json(422, { ok: false, error: "invalid_device_id" });
  }
  if (!ID_PATTERN.test(gatewayId)) {
    return json(422, { ok: false, error: "invalid_gateway_id" });
  }
  if (suppliedGatewayId && legacyDeviceId && suppliedGatewayId !== legacyDeviceId) {
    return json(422, { ok: false, error: "gateway_device_id_mismatch" });
  }
  for (
    const [field, value] of [
      ["station_id", stationId],
      ["camera_id", cameraId],
      ["analysis_id", analysisId],
    ] as const
  ) {
    if (body[field] !== undefined && body[field] !== null && (!value || !ID_PATTERN.test(value))) {
      return json(422, { ok: false, error: `invalid_${field}` });
    }
  }
  if (
    body.frame_sha256 !== undefined && body.frame_sha256 !== null &&
    (!frameSha256 || !SHA256_PATTERN.test(frameSha256))
  ) {
    return json(422, { ok: false, error: "invalid_frame_sha256" });
  }
  if (
    body.payload_hash !== undefined && body.payload_hash !== null &&
    (!payloadHash || !SHA256_PATTERN.test(payloadHash))
  ) {
    return json(422, { ok: false, error: "invalid_payload_hash" });
  }
  if (!photoDraft && (!Number.isFinite(weight) || weight < 0 || !UNITS.has(unit))) {
    return json(422, { ok: false, error: "invalid_weight" });
  }
  if (
    !photoDraft && !inventoryCheck &&
    (requestedErrorStatus !== errorStatus || (errorStatus === "error" && !errorReason))
  ) {
    return json(422, { ok: false, error: "invalid_error_status" });
  }
  if (!capturedAt || Number.isNaN(Date.parse(capturedAt))) {
    return json(422, { ok: false, error: "invalid_captured_at" });
  }
  if (imageBase64.length > Math.ceil(MAX_IMAGE_BYTES / 3) * 4 + 4) {
    return json(413, { ok: false, error: "image_too_large" });
  }
  if (!inventoryCheck && !photoDraft && (!Number.isFinite(productWeight) || productWeight < 0)) {
    return json(422, { ok: false, error: "invalid_product_weight" });
  }
  if (
    inventoryCheck &&
    (!Number.isFinite(coreWeight) || coreWeight < 0 ||
      !Number.isFinite(inventoryTareWeight) || inventoryTareWeight < 0)
  ) {
    return json(422, { ok: false, error: "invalid_inventory_weights" });
  }
  if (productImageBase64.length > Math.ceil(MAX_IMAGE_BYTES / 3) * 4 + 4) {
    return json(413, { ok: false, error: "product_image_too_large" });
  }
  const expectedImageRole = photoDraft
    ? "photo_draft"
    : inventoryCheck
    ? "inventory_check"
    : "core_weight";
  if (imageRole && imageRole !== expectedImageRole) {
    return json(422, { ok: false, error: "invalid_image_role" });
  }

  let image: Uint8Array;
  try {
    image = decodeBase64(imageBase64);
  } catch {
    return json(422, { ok: false, error: "invalid_image_base64" });
  }
  if (
    image.length < 4 || image.length > MAX_IMAGE_BYTES ||
    image[0] !== 0xff || image[1] !== 0xd8
  ) {
    return json(422, { ok: false, error: "invalid_jpeg" });
  }
  if (frameSha256 && await sha256Hex(image) !== frameSha256) {
    return json(422, { ok: false, error: "frame_sha256_mismatch" });
  }
  let productImage: Uint8Array | null = null;
  if (productImageBase64) {
    try {
      productImage = decodeBase64(productImageBase64);
    } catch {
      return json(422, { ok: false, error: "invalid_product_image_base64" });
    }
    if (
      productImage.length < 4 || productImage.length > MAX_IMAGE_BYTES ||
      productImage[0] !== 0xff || productImage[1] !== 0xd8
    ) {
      return json(422, { ok: false, error: "invalid_product_jpeg" });
    }
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceKey = getSupabaseAdminKey();
  if (!supabaseUrl || !serviceKey) {
    return json(500, { ok: false, error: "supabase_not_configured" });
  }
  const supabase = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  if (photoDraft) {
    const photoSelect =
      "id,event_id,qr_code,captured_at,image_path,image_url,image_public_id," +
      "gateway_id,station_id,camera_id,frame_sha256,payload_hash,qr_source," +
      "work_date,shift,machine,production_order,status,parent_event_id," +
      "capture_kind,capture_round,metadata";
    const { data: existingPhoto, error: photoLookupError } = await supabase
      .from(PHOTO_DRAFT_TABLE)
      .select(photoSelect)
      .eq("event_id", eventId)
      .maybeSingle();
    if (photoLookupError) {
      return json(500, { ok: false, error: "photo_draft_lookup_failed" });
    }
    if (existingPhoto) {
      const existingRow = existingPhoto as unknown as Record<string, unknown>;
      if (
        existingRow.payload_hash !== payloadHash ||
        existingRow.frame_sha256 !== frameSha256 ||
        existingRow.parent_event_id !== parentEventId ||
        existingRow.capture_kind !== captureKind ||
        existingRow.capture_round !== captureRound
      ) {
        return json(409, { ok: false, error: "event_id_conflict" });
      }
      const existingPhotoUrl = cloudinaryUrl(existingRow.image_url);
      const existingPhotoPublicId = typeof existingRow.image_public_id === "string"
        ? existingRow.image_public_id.trim()
        : "";
      const existingPhotoLocal = rowHasLocalBackupCommit(existingRow);
      if (!existingPhotoUrl || !existingPhotoPublicId) {
        const photoMetadata = existingRow.metadata && typeof existingRow.metadata === "object"
          ? { ...(existingRow.metadata as Record<string, unknown>) }
          : {};
        const pendingPhotoPublicId = typeof existingRow.image_path === "string" &&
            existingRow.image_path.trim()
          ? existingRow.image_path.trim()
          : "";
        if (existingPhotoLocal && pendingPhotoPublicId) {
          let retryUploaded: CloudinaryUpload | null = null;
          try {
            retryUploaded = await uploadToCloudinary(image, pendingPhotoPublicId);
          } catch {
            // Keep the row acknowledged as a local durable commit; the worker
            // retains its cloudinary_pending marker and retries later.
          }
          if (retryUploaded) {
            const updatedMetadata = backupMetadata({
              ...photoMetadata,
              cloudinary_uploaded: true,
              cloudinary_pending: false,
              local_backup_only: false,
            }, capturedAt);
            const { data: updatedPhoto, error: photoUpdateError } = await supabase
              .from(PHOTO_DRAFT_TABLE)
              .update({
                image_path: retryUploaded.publicId,
                image_url: retryUploaded.secureUrl,
                image_public_id: retryUploaded.publicId,
                metadata: updatedMetadata,
              })
              .eq("event_id", eventId)
              .select(photoSelect)
              .single();
            if (!photoUpdateError && updatedPhoto) {
              const updatedPhotoRow = updatedPhoto as unknown as Record<string, unknown>;
              return json(200, {
                ok: true,
                id: updatedPhotoRow.id,
                event_id: eventId,
                parent_event_id: parentEventId,
                capture_kind: captureKind,
                capture_round: captureRound,
                image_url: updatedPhotoRow.image_url,
                image_public_id: updatedPhotoRow.image_public_id,
                local_backup_committed: true,
                cloudinary_uploaded: true,
                cloudinary_pending: false,
                qr_code: updatedPhotoRow.qr_code,
                status: updatedPhotoRow.status,
                workflow: "photo_draft",
                duplicate: true,
              });
            }
          }
        }
      }
      return json(200, {
        ok: true,
        id: existingRow.id,
        event_id: eventId,
        parent_event_id: parentEventId,
        capture_kind: captureKind,
        capture_round: captureRound,
        image_url: existingRow.image_url,
        image_public_id: existingRow.image_public_id,
        local_backup_committed: existingPhotoLocal,
        cloudinary_uploaded: Boolean(existingPhotoUrl && existingPhotoPublicId),
        cloudinary_pending: metadataCloudinaryPending(existingRow.metadata),
        qr_code: existingRow.qr_code,
        status: existingRow.status,
        workflow: "photo_draft",
        duplicate: true,
      });
    }

    const photoNow = new Date().toISOString();
    const { error: photoDeviceError } = await supabase.from("devices").upsert(
      { id: gatewayId, last_seen_at: photoNow },
      { onConflict: "id" },
    );
    if (photoDeviceError) {
      return json(500, { ok: false, error: "device_upsert_failed" });
    }
    const captureDate = new Date(capturedAt);
    const year = captureDate.getUTCFullYear();
    const month = String(captureDate.getUTCMonth() + 1).padStart(2, "0");
    const day = String(captureDate.getUTCDate()).padStart(2, "0");
    const photoPublicId = `roll-captures/${gatewayId}/${year}/${month}/${day}/photo-draft/${parentEventId}/${captureKind}-${captureRound + 1}/${eventId}`;
    let uploaded: CloudinaryUpload | null = null;
    let cloudinaryError = "";
    try {
      uploaded = await uploadToCloudinary(image, photoPublicId);
    } catch (error) {
      cloudinaryError = error instanceof Error
        ? error.message.split(":", 1)[0]
        : "upload_failed";
    }
    const cloudinaryPending = !uploaded;
    const { data: insertedPhoto, error: photoInsertError } = await supabase
      .from(PHOTO_DRAFT_TABLE)
      .insert({
        event_id: eventId,
        parent_event_id: parentEventId,
        capture_kind: captureKind,
        capture_round: captureRound,
        qr_code: qrCode || null,
        captured_at: capturedAt,
        image_path: photoPublicId,
        image_url: uploaded?.secureUrl ?? null,
        image_public_id: uploaded?.publicId ?? null,
        gateway_id: gatewayId,
        station_id: stationId,
        camera_id: cameraId,
        frame_sha256: frameSha256,
        payload_hash: payloadHash,
        qr_source: qrSource,
        work_date: workDate || null,
        shift: shift || null,
        machine: machine || null,
        production_order: productionOrder || null,
        status: "awaiting_ai",
        metadata: backupMetadata({
          ai_requested: false,
          ingested_at: photoNow,
          workflow: "photo_draft",
          parent_event_id: parentEventId,
          capture_kind: captureKind,
          capture_round: captureRound,
          cloudinary_uploaded: Boolean(uploaded),
          cloudinary_pending: cloudinaryPending,
          local_backup_only: cloudinaryPending,
          cloudinary_error: cloudinaryError || null,
        }, capturedAt),
      })
      .select(photoSelect)
      .single();
    if (photoInsertError || !insertedPhoto) {
      if (photoInsertError?.code === "23505") {
        const { data: racedPhoto } = await supabase
          .from(PHOTO_DRAFT_TABLE)
          .select(photoSelect)
          .eq("event_id", eventId)
          .maybeSingle();
        if (racedPhoto) {
          const racedRow = racedPhoto as unknown as Record<string, unknown>;
          if (
            racedRow.payload_hash !== payloadHash ||
            racedRow.frame_sha256 !== frameSha256 ||
            racedRow.parent_event_id !== parentEventId ||
            racedRow.capture_kind !== captureKind ||
            racedRow.capture_round !== captureRound
          ) {
            return json(409, { ok: false, error: "event_id_conflict" });
          }
          return json(200, {
            ok: true,
            id: racedRow.id,
            event_id: eventId,
            parent_event_id: parentEventId,
            capture_kind: captureKind,
            capture_round: captureRound,
            image_url: racedRow.image_url,
            image_public_id: racedRow.image_public_id,
            local_backup_committed: rowHasLocalBackupCommit(racedRow),
            cloudinary_uploaded: Boolean(cloudinaryUrl(racedRow.image_url) && racedRow.image_public_id),
            cloudinary_pending: metadataCloudinaryPending(racedRow.metadata),
            qr_code: racedRow.qr_code,
            status: racedRow.status,
            workflow: "photo_draft",
            duplicate: true,
          });
        }
      }
      return json(500, { ok: false, error: "photo_draft_insert_failed" });
    }
    const insertedPhotoRow = insertedPhoto as unknown as Record<string, unknown>;
    return json(201, {
      ok: true,
      id: insertedPhotoRow.id,
      event_id: eventId,
      parent_event_id: parentEventId,
      capture_kind: captureKind,
      capture_round: captureRound,
      image_url: uploaded?.secureUrl ?? null,
      image_public_id: uploaded?.publicId ?? null,
      local_backup_committed: true,
      cloudinary_uploaded: Boolean(uploaded),
      cloudinary_pending: cloudinaryPending,
      cloudinary_error: cloudinaryError || null,
      qr_code: insertedPhotoRow.qr_code,
      status: insertedPhotoRow.status,
      workflow: "photo_draft",
      duplicate: false,
    });
  }

  if (inventoryCheck) {
    const inventorySelect =
      "id,event_id,ma_san_pham,khoi_luong,khoi_luong_loi,khoi_luong_bi,don_vi," +
      "captured_at,image_path,image_url,image_public_id,gateway_id,station_id," +
      "camera_id,analysis_id,frame_sha256,payload_hash,metadata";
    const { data: existingInventory, error: inventoryLookupError } = await supabase
      .from(INVENTORY_TABLE)
      .select(inventorySelect)
      .eq("event_id", eventId)
      .maybeSingle();
    if (inventoryLookupError) {
      return json(500, { ok: false, error: "inventory_lookup_failed" });
    }
    if (existingInventory) {
      const existingRow = existingInventory as unknown as Record<string, unknown>;
      if (
        !sameInventoryCheck(
          existingRow,
          productCode,
          weight,
          coreWeight,
          inventoryTareWeight,
          unit,
          capturedAt,
          gatewayId,
          stationId,
          cameraId,
          analysisId,
          frameSha256,
          payloadHash,
        )
      ) {
        return json(409, { ok: false, error: "event_id_conflict" });
      }
      const existingInventoryUrl = cloudinaryUrl(existingRow.image_url);
      const existingInventoryPublicId = typeof existingRow.image_public_id === "string"
        ? existingRow.image_public_id.trim()
        : "";
      const existingInventoryLocal = rowHasLocalBackupCommit(existingRow);
      const pendingInventoryPublicId = typeof existingRow.image_path === "string" &&
          existingRow.image_path.trim()
        ? existingRow.image_path.trim()
        : "";
      if (
        existingInventoryLocal &&
        (!existingInventoryUrl || !existingInventoryPublicId) &&
        pendingInventoryPublicId
      ) {
        let retryUploaded: CloudinaryUpload | null = null;
        try {
          retryUploaded = await uploadToCloudinary(image, pendingInventoryPublicId);
        } catch {
          // The local commit remains authoritative; retry on the next outbox
          // pass instead of dropping the inventory row.
        }
        if (retryUploaded) {
          const existingMetadata = existingRow.metadata && typeof existingRow.metadata === "object"
            ? { ...(existingRow.metadata as Record<string, unknown>) }
            : {};
          const { data: updatedInventory, error: inventoryUpdateError } = await supabase
            .from(INVENTORY_TABLE)
            .update({
              image_path: retryUploaded.publicId,
              image_url: retryUploaded.secureUrl,
              image_public_id: retryUploaded.publicId,
              metadata: backupMetadata({
                ...existingMetadata,
                cloudinary_uploaded: true,
                cloudinary_pending: false,
                local_backup_only: false,
              }, capturedAt),
            })
            .eq("event_id", eventId)
            .select(inventorySelect)
            .single();
          if (!inventoryUpdateError && updatedInventory) {
            const updatedInventoryRow = updatedInventory as unknown as Record<string, unknown>;
            return json(200, {
              ok: true,
              id: updatedInventoryRow.id,
              event_id: eventId,
              image_url: updatedInventoryRow.image_url,
              image_public_id: updatedInventoryRow.image_public_id,
              local_backup_committed: true,
              cloudinary_uploaded: true,
              cloudinary_pending: false,
              workflow: "inventory_check",
              duplicate: true,
            });
          }
        }
      }
      return json(200, {
        ok: true,
        id: existingRow.id,
        event_id: eventId,
        image_url: existingRow.image_url,
        image_public_id: existingRow.image_public_id,
        local_backup_committed: existingInventoryLocal,
        cloudinary_uploaded: Boolean(existingInventoryUrl && existingInventoryPublicId),
        cloudinary_pending: metadataCloudinaryPending(existingRow.metadata),
        gateway_id: existingRow.gateway_id,
        station_id: existingRow.station_id,
        camera_id: existingRow.camera_id,
        analysis_id: existingRow.analysis_id,
        frame_sha256: existingRow.frame_sha256,
        payload_hash: existingRow.payload_hash,
        workflow: "inventory_check",
        duplicate: true,
      });
    }

    const inventoryNow = new Date().toISOString();
    const { error: inventoryDeviceError } = await supabase.from("devices").upsert(
      { id: gatewayId, last_seen_at: inventoryNow },
      { onConflict: "id" },
    );
    if (inventoryDeviceError) {
      return json(500, { ok: false, error: "device_upsert_failed" });
    }
    const { error: inventoryRollError } = await supabase.from("rolls").upsert(
      { qr_code: productCode, last_seen_at: inventoryNow },
      { onConflict: "qr_code" },
    );
    if (inventoryRollError) {
      return json(500, { ok: false, error: "roll_upsert_failed" });
    }
    const inventoryDate = new Date(capturedAt);
    const inventoryYear = inventoryDate.getUTCFullYear();
    const inventoryMonth = String(inventoryDate.getUTCMonth() + 1).padStart(2, "0");
    const inventoryDay = String(inventoryDate.getUTCDate()).padStart(2, "0");
    const inventoryPublicId =
      `roll-captures/${gatewayId}/${inventoryYear}/${inventoryMonth}/${inventoryDay}/` +
      `inventory-check/${eventId}`;
    let inventoryUploaded: CloudinaryUpload | null = null;
    let inventoryCloudinaryError = "";
    try {
      inventoryUploaded = await uploadToCloudinary(image, inventoryPublicId);
    } catch (error) {
      inventoryCloudinaryError = error instanceof Error
        ? error.message.split(":", 1)[0]
        : "upload_failed";
    }
    const inventoryCloudinaryPending = !inventoryUploaded;
    const { data: insertedInventory, error: inventoryInsertError } = await supabase
      .from(INVENTORY_TABLE)
      .insert({
        event_id: eventId,
        ma_san_pham: productCode,
        khoi_luong: weight,
        khoi_luong_loi: coreWeight,
        khoi_luong_bi: inventoryTareWeight,
        don_vi: unit,
        captured_at: capturedAt,
        image_path: inventoryPublicId,
        image_url: inventoryUploaded?.secureUrl ?? null,
        image_public_id: inventoryUploaded?.publicId ?? null,
        gateway_id: gatewayId,
        station_id: stationId,
        camera_id: cameraId,
        analysis_id: analysisId,
        frame_sha256: frameSha256,
        payload_hash: payloadHash,
        weight_source: weightSource,
        qr_source: qrSource,
        status: "confirmed",
        metadata: backupMetadata({
          ingested_at: inventoryNow,
          weight_raw: weightRaw,
          weight_stable: weightStable,
          workflow: "inventory_check",
          work_date: workDate || null,
          shift: shift || null,
          machine: machine || null,
          production_order: productionOrder || null,
          cloudinary_uploaded: Boolean(inventoryUploaded),
          cloudinary_pending: inventoryCloudinaryPending,
          local_backup_only: inventoryCloudinaryPending,
          cloudinary_error: inventoryCloudinaryError || null,
        }, capturedAt),
      })
      .select(inventorySelect)
      .single();
    if (inventoryInsertError) {
      if (inventoryInsertError.code === "23505") {
        const { data: racedInventory } = await supabase
          .from(INVENTORY_TABLE)
          .select(inventorySelect)
          .eq("event_id", eventId)
          .single();
        if (racedInventory) {
          const racedRow = racedInventory as unknown as Record<string, unknown>;
          if (
            !sameInventoryCheck(
              racedRow,
              productCode,
              weight,
              coreWeight,
              inventoryTareWeight,
              unit,
              capturedAt,
              gatewayId,
              stationId,
              cameraId,
              analysisId,
              frameSha256,
              payloadHash,
            )
          ) {
            return json(409, { ok: false, error: "event_id_conflict" });
          }
          return json(200, {
            ok: true,
            id: racedRow.id,
            event_id: eventId,
            image_url: racedRow.image_url,
            image_public_id: racedRow.image_public_id,
            local_backup_committed: rowHasLocalBackupCommit(racedRow),
            cloudinary_uploaded: Boolean(cloudinaryUrl(racedRow.image_url) && racedRow.image_public_id),
            cloudinary_pending: metadataCloudinaryPending(racedRow.metadata),
            workflow: "inventory_check",
            duplicate: true,
          });
        }
      }
      return json(500, { ok: false, error: "inventory_insert_failed" });
    }
    const insertedInventoryRow = insertedInventory as unknown as Record<string, unknown>;
    return json(201, {
      ok: true,
      id: insertedInventoryRow.id,
      event_id: eventId,
      image_url: inventoryUploaded?.secureUrl ?? null,
      image_public_id: inventoryUploaded?.publicId ?? null,
      local_backup_committed: true,
      cloudinary_uploaded: Boolean(inventoryUploaded),
      cloudinary_pending: inventoryCloudinaryPending,
      cloudinary_error: inventoryCloudinaryError || null,
      gateway_id: gatewayId,
      station_id: stationId,
      camera_id: cameraId,
      analysis_id: analysisId,
      frame_sha256: frameSha256,
      payload_hash: payloadHash,
      workflow: "inventory_check",
      duplicate: false,
    });
  }

  const { data: existing, error: lookupError } = await supabase
    .from(MEASUREMENT_TABLE)
    .select(EVENT_SELECT)
    .eq("event_id", eventId)
    .maybeSingle();
  if (lookupError) {
    return json(500, { ok: false, error: "lookup_failed" });
  }
  if (existing) {
    const existingRow = existing as unknown as Record<string, unknown>;
    if (
      !sameEvent(
        existingRow,
        qrCode,
        weight,
        unit,
        capturedAt,
        weightSource,
        qrSource,
        weightRaw,
        weightStable,
        gatewayId,
        stationId,
        cameraId,
        analysisId,
        frameSha256,
        payloadHash,
      )
    ) {
      return json(409, { ok: false, error: "event_id_conflict" });
    }
    const existingCoreUrl = cloudinaryUrl(
      existingRow.core_image_url ?? existingRow.image_url,
    );
    const existingCorePublicId = typeof (
      existingRow.core_image_public_id ?? existingRow.image_public_id
    ) === "string"
      ? String(existingRow.core_image_public_id ?? existingRow.image_public_id).trim()
      : "";
    const existingProductUrl = cloudinaryUrl(existingRow.product_image_url);
    const existingProductPublicId = typeof existingRow.product_image_public_id === "string"
      ? existingRow.product_image_public_id.trim()
      : "";
    const existingLocalBackup = rowHasLocalBackupCommit(existingRow);
    const captureDate = new Date(capturedAt);
    const year = captureDate.getUTCFullYear();
    const month = String(captureDate.getUTCMonth() + 1).padStart(2, "0");
    const day = String(captureDate.getUTCDate()).padStart(2, "0");
    const deterministicCorePublicId =
      `roll-captures/${gatewayId}/${year}/${month}/${day}/core-weight/${eventId}`;
    const deterministicProductPublicId =
      `roll-captures/${gatewayId}/${year}/${month}/${day}/product-weight/${eventId}`;
    const coreNeedsUpload = !existingCoreUrl || !existingCorePublicId;
    const productNeedsUpload = Boolean(productImage) &&
      (!existingProductUrl || !existingProductPublicId);
    let retryCoreUploaded: CloudinaryUpload | null = null;
    let retryProductUploaded: CloudinaryUpload | null = null;
    if (existingLocalBackup && coreNeedsUpload) {
      try {
        retryCoreUploaded = await uploadToCloudinary(image, deterministicCorePublicId);
      } catch {
        // Keep the local commit acknowledged and retry while its Render-disk
        // evidence remains available.
      }
    }
    if (productNeedsUpload) {
      try {
        retryProductUploaded = await uploadToCloudinary(
          productImage as Uint8Array,
          deterministicProductPublicId,
        );
      } catch {
        // A partial retry must not erase the successful core or product row.
      }
    }
    if (retryCoreUploaded || retryProductUploaded) {
      const existingMetadata = existingRow.metadata !== null &&
          typeof existingRow.metadata === "object"
        ? { ...(existingRow.metadata as Record<string, unknown>) }
        : {};
      const coreAvailable = Boolean(existingCoreUrl && existingCorePublicId) ||
        Boolean(retryCoreUploaded);
      const productAvailable = Boolean(existingProductUrl && existingProductPublicId) ||
        Boolean(retryProductUploaded);
      const pending = !coreAvailable || (Boolean(productImage) && !productAvailable);
      const updates: Record<string, unknown> = {
        metadata: backupMetadata({
          ...existingMetadata,
          cloudinary_core_uploaded: coreAvailable,
          cloudinary_product_uploaded: productAvailable,
          cloudinary_pending: pending,
          local_backup_only: pending && !coreAvailable && !productAvailable,
          cloudinary_error: pending ? "retry_pending" : null,
        }, capturedAt),
      };
      if (retryCoreUploaded) {
        updates.image_path = retryCoreUploaded.publicId;
        updates.image_url = retryCoreUploaded.secureUrl;
        updates.image_public_id = retryCoreUploaded.publicId;
        updates.core_image_path = retryCoreUploaded.publicId;
        updates.core_image_url = retryCoreUploaded.secureUrl;
        updates.core_image_public_id = retryCoreUploaded.publicId;
      }
      if (retryProductUploaded) {
        updates.product_image_path = retryProductUploaded.publicId;
        updates.product_image_url = retryProductUploaded.secureUrl;
        updates.product_image_public_id = retryProductUploaded.publicId;
      }
      const { data: updated, error: updateError } = await supabase
        .from(MEASUREMENT_TABLE)
        .update(updates)
        .eq("event_id", eventId)
        .select(EVENT_SELECT)
        .single();
      if (!updateError && updated) {
        const updatedRow = updated as unknown as Record<string, unknown>;
        return json(200, {
          ok: true,
          id: updatedRow.id,
          event_id: eventId,
          image_url: updatedRow.image_url,
          image_public_id: updatedRow.image_public_id,
          core_image_url: updatedRow.core_image_url ?? updatedRow.image_url,
          core_image_public_id: updatedRow.core_image_public_id ?? updatedRow.image_public_id,
          product_image_url: updatedRow.product_image_url,
          product_image_public_id: updatedRow.product_image_public_id,
          local_backup_committed: true,
          cloudinary_core_uploaded: coreAvailable,
          cloudinary_product_uploaded: productAvailable,
          cloudinary_pending: pending,
          duplicate: true,
        });
      }
    }
    return json(200, {
      ok: true,
      id: existingRow.id,
      event_id: eventId,
      image_url: existingRow.image_url,
      image_public_id: existingRow.image_public_id,
      core_image_url: existingRow.core_image_url ?? existingRow.image_url,
      core_image_public_id: existingRow.core_image_public_id ?? existingRow.image_public_id,
      product_image_url: existingRow.product_image_url,
      product_image_public_id: existingRow.product_image_public_id,
      local_backup_committed: existingLocalBackup,
      cloudinary_core_uploaded: Boolean(existingCoreUrl && existingCorePublicId),
      cloudinary_product_uploaded: Boolean(existingProductUrl && existingProductPublicId),
      cloudinary_pending: metadataCloudinaryPending(existingRow.metadata),
      gateway_id: existingRow.gateway_id ?? existingRow.device_id,
      station_id: existingRow.station_id,
      camera_id: existingRow.camera_id,
      analysis_id: existingRow.analysis_id,
      frame_sha256: existingRow.frame_sha256,
      payload_hash: existingRow.payload_hash,
      duplicate: true,
    });
  }

  const now = new Date().toISOString();
  const { error: deviceError } = await supabase.from("devices").upsert(
    { id: gatewayId, last_seen_at: now },
    { onConflict: "id" },
  );
  if (deviceError) {
    return json(500, { ok: false, error: "device_upsert_failed" });
  }
  const { error: rollError } = await supabase.from("rolls").upsert(
    { qr_code: qrCode, last_seen_at: now },
    { onConflict: "qr_code" },
  );
  if (rollError) {
    return json(500, { ok: false, error: "roll_upsert_failed" });
  }

  const captureDate = new Date(capturedAt);
  const year = captureDate.getUTCFullYear();
  const month = String(captureDate.getUTCMonth() + 1).padStart(2, "0");
  const day = String(captureDate.getUTCDate()).padStart(2, "0");
  const imagePublicId = `roll-captures/${gatewayId}/${year}/${month}/${day}/core-weight/${eventId}`;
  const productImagePublicId = `roll-captures/${gatewayId}/${year}/${month}/${day}/product-weight/${eventId}`;
  let cloudinaryCoreError = "";
  let cloudinaryProductError = "";
  const [uploaded, productUploaded] = await Promise.all([
    uploadToCloudinary(image, imagePublicId).catch((error) => {
      cloudinaryCoreError = error instanceof Error
        ? error.message.split(":", 1)[0]
        : "upload_failed";
      return null;
    }),
    productImage
      ? uploadToCloudinary(
        productImage,
        productImagePublicId,
      ).catch((error) => {
        cloudinaryProductError = error instanceof Error
          ? error.message.split(":", 1)[0]
          : "upload_failed";
        return null;
      })
      : Promise.resolve(null),
  ]);
  const cloudinaryCorePending = !uploaded;
  const cloudinaryProductPending = productImage !== null && !productUploaded;
  const cloudinaryPending = cloudinaryCorePending || cloudinaryProductPending;

  const { data: inserted, error: insertError } = await supabase
    .from(MEASUREMENT_TABLE)
    .insert({
      event_id: eventId,
      qr_code: qrCode,
      // In can_tu_dong, weight is the gross/product reading. The core reading
      // is the tare, so the generated net_weight is gross minus core.
      weight: productWeight,
      tare_weight: weight,
      unit,
      captured_at: capturedAt,
      image_path: uploaded?.publicId ?? imagePublicId,
      image_url: uploaded?.secureUrl ?? null,
      image_public_id: uploaded?.publicId ?? null,
      core_image_path: uploaded?.publicId ?? imagePublicId,
      core_image_url: uploaded?.secureUrl ?? null,
      core_image_public_id: uploaded?.publicId ?? null,
      product_image_path: productImage ? productUploaded?.publicId ?? productImagePublicId : null,
      product_image_url: productUploaded?.secureUrl ?? null,
      product_image_public_id: productUploaded?.publicId ?? null,
      device_id: gatewayId,
      gateway_id: gatewayId,
      station_id: stationId,
      camera_id: cameraId,
      analysis_id: analysisId,
      frame_sha256: frameSha256,
      payload_hash: payloadHash,
      weight_source: weightSource,
      qr_source: qrSource,
      error_status: errorStatus,
      error_reason: errorReason,
      status: "confirmed",
      metadata: backupMetadata({
        ingested_at: now,
        weight_raw: weightRaw,
        weight_stable: weightStable,
        core_weight: weight,
        product_weight: productWeight,
        error_status: errorStatus,
        error_reason: errorReason,
        work_date: workDate || null,
        shift: shift || null,
        machine: machine || null,
        production_order: productionOrder || null,
        bi_weight: biWeight,
        cloudinary_core_uploaded: Boolean(uploaded),
        cloudinary_product_uploaded: Boolean(productUploaded),
        cloudinary_pending: cloudinaryPending,
        local_backup_only: cloudinaryPending && !uploaded && !productUploaded,
        cloudinary_error: cloudinaryPending
          ? [cloudinaryCoreError, cloudinaryProductError].filter(Boolean).join(",") ||
            "upload_pending"
          : null,
      }, capturedAt),
    })
    .select("id,image_path")
    .single();

  if (insertError) {
    if (insertError.code === "23505") {
      const { data: raced } = await supabase
        .from(MEASUREMENT_TABLE)
        .select(EVENT_SELECT)
        .eq("event_id", eventId)
        .single();
      if (raced) {
        const racedRow = raced as unknown as Record<string, unknown>;
        if (
          !sameEvent(
            racedRow,
            qrCode,
            weight,
            unit,
            capturedAt,
            weightSource,
            qrSource,
            weightRaw,
            weightStable,
            gatewayId,
            stationId,
            cameraId,
            analysisId,
            frameSha256,
            payloadHash,
          )
        ) {
          return json(409, { ok: false, error: "event_id_conflict" });
        }
        return json(200, {
          ok: true,
          id: racedRow.id,
          event_id: eventId,
          image_url: racedRow.image_url,
          image_public_id: racedRow.image_public_id,
          core_image_url: racedRow.core_image_url ?? racedRow.image_url,
          core_image_public_id: racedRow.core_image_public_id ?? racedRow.image_public_id,
          product_image_url: racedRow.product_image_url,
          product_image_public_id: racedRow.product_image_public_id,
          local_backup_committed: rowHasLocalBackupCommit(racedRow),
          cloudinary_core_uploaded: Boolean(
            cloudinaryUrl(racedRow.core_image_url ?? racedRow.image_url) &&
              (racedRow.core_image_public_id ?? racedRow.image_public_id)
          ),
          cloudinary_product_uploaded: Boolean(
            cloudinaryUrl(racedRow.product_image_url) && racedRow.product_image_public_id
          ),
          cloudinary_pending: metadataCloudinaryPending(racedRow.metadata),
          gateway_id: racedRow.gateway_id ?? racedRow.device_id,
          station_id: racedRow.station_id,
          camera_id: racedRow.camera_id,
          analysis_id: racedRow.analysis_id,
          frame_sha256: racedRow.frame_sha256,
          payload_hash: racedRow.payload_hash,
          duplicate: true,
        });
      }
    }
    return json(500, { ok: false, error: "measurement_insert_failed" });
  }

  return json(201, {
    ok: true,
    id: inserted.id,
    event_id: eventId,
    image_url: uploaded?.secureUrl ?? null,
    image_public_id: uploaded?.publicId ?? null,
    core_image_url: uploaded?.secureUrl ?? null,
    core_image_public_id: uploaded?.publicId ?? null,
    product_image_url: productUploaded?.secureUrl ?? null,
    product_image_public_id: productUploaded?.publicId ?? null,
    local_backup_committed: true,
    cloudinary_core_uploaded: Boolean(uploaded),
    cloudinary_product_uploaded: Boolean(productUploaded),
    cloudinary_pending: cloudinaryPending,
    cloudinary_error: cloudinaryPending
      ? [cloudinaryCoreError, cloudinaryProductError].filter(Boolean).join(",") ||
        "upload_pending"
      : null,
    gateway_id: gatewayId,
    station_id: stationId,
    camera_id: cameraId,
    analysis_id: analysisId,
    frame_sha256: frameSha256,
    payload_hash: payloadHash,
    duplicate: false,
  });
});

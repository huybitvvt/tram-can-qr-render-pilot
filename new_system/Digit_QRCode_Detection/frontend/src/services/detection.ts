import type { BoundingBox, Detection, RecognitionEvent, RecognitionStatus } from '../types/recognition'

const validStatuses = new Set<RecognitionStatus>(['WAITING', 'DETECTING', 'READY_TO_SAVE', 'SAVED', 'LOW_CONFIDENCE', 'INCOMPLETE', 'ERROR'])
const asNumber = (value: unknown, fallback = 0) => typeof value === 'number' && Number.isFinite(value) ? value : fallback

function parseDetection(raw: unknown): Detection | null {
  if (!raw || typeof raw !== 'object') return null
  const value = raw as Record<string, unknown>
  const box = value.bbox
  const coordinates: unknown[] | null = Array.isArray(box) ? box : box && typeof box === 'object' ? Object.values(box as BoundingBox) : null
  if (!coordinates || coordinates.length !== 4 || coordinates.some((coordinate) => typeof coordinate !== 'number')) return null
  return { type: value.type === 'qr' ? 'qr' : value.type === 'display' ? 'display' : 'digit', class: typeof value.class === 'number' ? value.class : undefined, value: typeof value.value === 'string' || typeof value.value === 'number' ? value.value : undefined, color: typeof value.color === 'string' ? value.color : undefined, confidence: asNumber(value.confidence), bbox: { x: coordinates[0] as number, y: coordinates[1] as number, width: coordinates[2] as number, height: coordinates[3] as number } }
}

export function parseRecognitionEvent(message: string): RecognitionEvent | null {
  const raw: unknown = JSON.parse(message)
  if (!raw || typeof raw !== 'object') return null
  const payload = raw as Record<string, unknown>
  const rawDigits = typeof payload.raw_digits === 'string' ? payload.raw_digits : null
  const detectionItems = Array.isArray(payload.detections) ? payload.detections : Array.isArray(payload.digits) ? payload.digits : []
  const digits = detectionItems.map(parseDetection).filter((detection): detection is Detection => detection !== null)
  const frameWidth = asNumber(payload.frame_width)
  const frameHeight = asNumber(payload.frame_height)
  const qr = payload.qr && typeof payload.qr === 'object' ? payload.qr as Record<string, unknown> : null
  const status = typeof payload.status === 'string' && validStatuses.has(payload.status as RecognitionStatus) ? payload.status as RecognitionStatus : rawDigits ? 'DETECTING' : 'WAITING'
  return { timestamp: asNumber(payload.timestamp, Date.now()), qrData: typeof qr?.data === 'string' ? qr.data : typeof payload.qr_data === 'string' ? payload.qr_data : null, digits, rawDigits, numericValue: typeof payload.numeric_value === 'number' ? payload.numeric_value : null, confidence: typeof payload.confidence === 'number' ? payload.confidence : null, status, frameSize: frameWidth > 0 && frameHeight > 0 ? { width: frameWidth, height: frameHeight } : null, storageEnabled: payload.storage_enabled !== false }
}

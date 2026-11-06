export type RecognitionStatus = 'WAITING' | 'DETECTING' | 'READY_TO_SAVE' | 'SAVED' | 'LOW_CONFIDENCE' | 'INCOMPLETE' | 'ERROR'
export type ConnectionState = 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' | 'ERROR'
export interface BoundingBox { x: number; y: number; width: number; height: number }
export interface Detection { type: 'digit' | 'qr' | 'display'; class?: number; value?: string | number; color?: string; confidence: number; bbox: BoundingBox }
export interface FrameSize { width: number; height: number }
export interface RecognitionEvent { timestamp: number; qrData: string | null; digits: Detection[]; rawDigits: string | null; numericValue: number | null; confidence: number | null; status: RecognitionStatus; frameSize: FrameSize | null; storageEnabled: boolean }
export interface Measurement { id: number | string; qr_data: string; raw_digits: string; numeric_value: number; confidence: number; captured_at?: string; created_at: string }
export interface SaveMeasurementRequest { qr_data: string; raw_digits: string; numeric_value: number; confidence: number }

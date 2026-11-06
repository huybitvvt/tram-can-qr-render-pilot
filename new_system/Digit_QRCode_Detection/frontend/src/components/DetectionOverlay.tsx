import type { CSSProperties } from 'react'
import type { Detection, FrameSize } from '../types/recognition'

export function DetectionOverlay({ detections, frameSize, displayRect }: { detections: Detection[]; frameSize: FrameSize | null; displayRect: CSSProperties }) {
  if (!frameSize) return null
  return <div className="detection-overlay" style={displayRect} aria-label="Live detections">{detections.filter((detection) => detection.type !== 'display').map((detection, index) => { const { bbox } = detection; const label = detection.type === 'qr' ? 'QR code' : String(detection.value ?? detection.class ?? '?'); return <div className={`detection-box detection-box--${detection.type}`} key={`${label}-${bbox.x}-${bbox.y}-${index}`} style={{ left: `${bbox.x / frameSize.width * 100}%`, top: `${bbox.y / frameSize.height * 100}%`, width: `${bbox.width / frameSize.width * 100}%`, height: `${bbox.height / frameSize.height * 100}%` }}><span>{label} · {Math.round(detection.confidence * 100)}%</span></div> })}</div>
}

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, SyntheticEvent } from 'react'
import { DetectionOverlay } from './DetectionOverlay'
import type { ConnectionState, Detection, FrameSize } from '../types/recognition'
interface Props { streamUrl: string; status: ConnectionState; frameSize: FrameSize | null; detections: Detection[]; onLoad: (event: SyntheticEvent<HTMLImageElement>) => void; onError: () => void; onReconnect: () => void }
export function CameraView({ streamUrl, status, frameSize, detections, onLoad, onError, onReconnect }: Props) {
  const stageRef = useRef<HTMLDivElement>(null)
  const [displayRect, setDisplayRect] = useState<CSSProperties>({ inset: 0 })
  useEffect(() => {
    const stage = stageRef.current
    if (!stage || !frameSize) return
    const updateRect = () => {
      const scale = Math.min(stage.clientWidth / frameSize.width, stage.clientHeight / frameSize.height)
      const width = frameSize.width * scale
      const height = frameSize.height * scale
      setDisplayRect({ left: (stage.clientWidth - width) / 2, top: (stage.clientHeight - height) / 2, width, height })
    }
    updateRect()
    const observer = new ResizeObserver(updateRect)
    observer.observe(stage)
    return () => observer.disconnect()
  }, [frameSize])
  const unavailable = status === 'ERROR' || status === 'DISCONNECTED'
  return <section className="camera-card" aria-labelledby="camera-title"><div className="section-heading"><div><p className="eyebrow">Live input</p><h2 id="camera-title">Camera view</h2></div><span className={`connection connection--${status.toLowerCase()}`}>{status.toLowerCase()}</span></div><div className="camera-stage" ref={stageRef}><img className="camera-stream" src={streamUrl} alt="Live camera stream" onLoad={onLoad} onError={onError} /><DetectionOverlay detections={detections} frameSize={frameSize} displayRect={displayRect} />{status === 'CONNECTING' && <div className="camera-message">Connecting to camera…</div>}{unavailable && <div className="camera-message"><strong>Camera unavailable</strong><button type="button" onClick={onReconnect}>Reconnect</button></div>}</div><p className="camera-caption">Detection boxes are supplied by the local CV service.</p></section>
}

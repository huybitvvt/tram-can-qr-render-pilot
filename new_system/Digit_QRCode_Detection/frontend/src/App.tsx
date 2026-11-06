import { useState } from 'react'
import { CameraView } from './components/CameraView'
import { RecentRecords } from './components/RecentRecords'
import { RecognitionPanel } from './components/RecognitionPanel'
import { SaveButton } from './components/SaveButton'
import { useCameraStream } from './hooks/useCameraStream'
import { useDetectionStream } from './hooks/useDetectionStream'
import { useMeasurements } from './hooks/useMeasurements'
import type { RecognitionStatus } from './types/recognition'
import './App.css'

function App() {
  const camera = useCameraStream(); const { recognition, status: detectionConnection } = useDetectionStream(); const measurements = useMeasurements(); const [saving, setSaving] = useState(false); const [saveResult, setSaveResult] = useState<{ timestamp: number; status: RecognitionStatus; error: string | null } | null>(null)
  const currentSaveResult = saveResult?.timestamp === recognition?.timestamp ? saveResult : null
  const status = currentSaveResult?.status ?? recognition?.status ?? (detectionConnection === 'ERROR' ? 'ERROR' : 'WAITING')
  const canSave = recognition?.status === 'READY_TO_SAVE' && recognition.storageEnabled && currentSaveResult?.status !== 'SAVED' && Boolean(recognition.qrData && recognition.rawDigits && recognition.numericValue !== null && recognition.confidence !== null)
  async function handleSave() { if (!recognition?.qrData || !recognition.rawDigits || recognition.numericValue === null || recognition.confidence === null || !canSave) return; setSaving(true); try { await measurements.save({ qr_data: recognition.qrData, raw_digits: recognition.rawDigits, numeric_value: recognition.numericValue, confidence: recognition.confidence }); setSaveResult({ timestamp: recognition.timestamp, status: 'SAVED', error: null }) } catch (error) { setSaveResult({ timestamp: recognition.timestamp, status: 'ERROR', error: error instanceof Error ? error.message : 'Could not save this measurement.' }) } finally { setSaving(false) } }
  return <main className="app-shell"><header className="app-header"><div className="brand-mark">CV</div><div><p className="eyebrow">Local capture station</p><h1>QR + seven-segment capture</h1></div><div className="service-state"><span className={`service-dot service-dot--${detectionConnection.toLowerCase()}`} />Detection service {detectionConnection.toLowerCase()}</div></header><div className="workspace"><CameraView streamUrl={camera.streamUrl} status={camera.status} frameSize={recognition?.frameSize ?? camera.frameSize} detections={recognition?.digits ?? []} onLoad={camera.handleLoad} onError={camera.handleError} onReconnect={camera.reconnect} /><aside className="review-panel"><RecognitionPanel recognition={recognition} status={status} /><div className="save-card"><p>Review the current camera result before adding it to the local record.</p><SaveButton enabled={canSave} saving={saving} onSave={() => void handleSave()} />{recognition?.storageEnabled === false && <p className="save-note">Saving is disabled in backend settings.</p>}{currentSaveResult?.error && <p className="save-error">{currentSaveResult.error}</p>}</div></aside></div><RecentRecords records={measurements.records} error={measurements.error} onRefresh={() => void measurements.refresh()} /></main>
}
export default App

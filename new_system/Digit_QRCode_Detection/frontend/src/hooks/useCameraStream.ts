import { useCallback, useState } from 'react'
import type { SyntheticEvent } from 'react'
import { config } from '../config'
import type { ConnectionState, FrameSize } from '../types/recognition'

export function useCameraStream() {
  const [status, setStatus] = useState<ConnectionState>('CONNECTING')
  const [frameSize, setFrameSize] = useState<FrameSize | null>(null)
  const [streamKey, setStreamKey] = useState(0)
  const handleLoad = useCallback((event: SyntheticEvent<HTMLImageElement>) => { setStatus('CONNECTED'); setFrameSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight }) }, [])
  return { status, frameSize, streamUrl: `${config.videoStreamUrl}${config.videoStreamUrl.includes('?') ? '&' : '?'}_=${streamKey}`, handleLoad, handleError: () => setStatus('ERROR'), reconnect: () => { setStatus('CONNECTING'); setStreamKey((key) => key + 1) } }
}

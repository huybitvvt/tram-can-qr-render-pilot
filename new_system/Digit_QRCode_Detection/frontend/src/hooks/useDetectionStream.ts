import { useEffect, useState } from 'react'
import { config } from '../config'
import { parseRecognitionEvent } from '../services/detection'
import type { ConnectionState, RecognitionEvent } from '../types/recognition'

export function useDetectionStream() {
  const [recognition, setRecognition] = useState<RecognitionEvent | null>(null)
  const [status, setStatus] = useState<ConnectionState>('CONNECTING')
  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    const connect = () => {
      if (stopped) return
      setStatus('CONNECTING')
      const connection = new WebSocket(config.detectionWebSocketUrl)
      socket = connection
      connection.onopen = () => setStatus('CONNECTED')
      connection.onclose = () => {
        if (stopped) return
        setStatus('DISCONNECTED')
        setRecognition(null)
        retryTimer = window.setTimeout(connect, 2000)
      }
      connection.onerror = () => { setStatus('ERROR'); connection.close() }
      connection.onmessage = (event) => {
        try {
          const detection = parseRecognitionEvent(String(event.data))
          if (detection) setRecognition(detection)
        } catch {
          setStatus('ERROR')
        }
      }
    }
    connect()
    return () => { stopped = true; window.clearTimeout(retryTimer); socket?.close() }
  }, [])
  return { recognition, status }
}

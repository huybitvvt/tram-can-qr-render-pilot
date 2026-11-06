const defaultApiBaseUrl = import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin
const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? defaultApiBaseUrl).replace(/\/$/, '')
const websocketProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const defaultWebSocketUrl = import.meta.env.DEV
  ? 'ws://localhost:8000/ws/detections'
  : `${websocketProtocol}//${window.location.host}/ws/detections`

export const config = {
  apiBaseUrl,
  videoStreamUrl: import.meta.env.VITE_VIDEO_STREAM_URL ?? `${apiBaseUrl}/stream`,
  detectionWebSocketUrl: import.meta.env.VITE_DETECTION_WS_URL ?? defaultWebSocketUrl,
}

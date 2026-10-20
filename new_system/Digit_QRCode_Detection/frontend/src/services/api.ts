import { config } from '../config'
import type { Measurement, SaveMeasurementRequest } from '../types/recognition'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${config.apiBaseUrl}${path}`, options)
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  return response.json() as Promise<T>
}
export const getMeasurements = () => request<Measurement[]>('/measurements')
export const saveMeasurement = (payload: SaveMeasurementRequest) => request<Measurement>('/measurements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })

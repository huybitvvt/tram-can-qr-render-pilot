import { useCallback, useEffect, useState } from 'react'
import { getMeasurements, saveMeasurement } from '../services/api'
import type { Measurement, SaveMeasurementRequest } from '../types/recognition'

export function useMeasurements() {
  const [records, setRecords] = useState<Measurement[]>([]); const [error, setError] = useState<string | null>(null)
  const refresh = useCallback(async () => { try { setError(null); setRecords(await getMeasurements()) } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not load records.') } }, [])
  useEffect(() => { const timer = window.setTimeout(() => void refresh(), 0); return () => window.clearTimeout(timer) }, [refresh])
  const save = useCallback(async (payload: SaveMeasurementRequest) => { const record = await saveMeasurement(payload); setRecords((current) => [record, ...current.filter((item) => item.id !== record.id)].slice(0, 20)); return record }, [])
  return { records, error, refresh, save }
}

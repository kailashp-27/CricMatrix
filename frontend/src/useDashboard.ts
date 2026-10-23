import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getStage, getTournaments, predict } from './api'
import { parseScenario, predictionKey, projectedTable } from './domain'
import { useScenario } from './store'
import type { Prediction, Scenario, Snapshot, Tournament } from './types'

function storedScenario(stageId: string): Scenario | null {
  try { return parseScenario(localStorage.getItem(`crease:scenario:v1:${stageId}`) || '') } catch { return null }
}
function sharedScenario(): Scenario | null {
  try { return window.location.hash.length > 90000 ? null : parseScenario(decodeURIComponent(window.location.hash.replace(/^#scenario=/, ''))) } catch { return null }
}

export function useDashboard() {
  const [catalog, setCatalog] = useState<Tournament[]>([])
  const [stageId, setStageId] = useState('')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [result, setResult] = useState<{ key: string; value: Prediction } | null>(null)
  const [error, setError] = useState('')
  const [predictionError, setPredictionError] = useState('')
  const [notice, setNotice] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [predictionRetry, setPredictionRetry] = useState(0)
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const scenario = useScenario()
  const [initialShared] = useState(sharedScenario)
  const shared = useRef<Scenario | null>(initialShared)
  const snapshotRef = useRef<Snapshot | null>(null)
  const lastAttached = useRef('')
  const retry = useCallback(() => setRefresh((r) => r + 1), [])
  const retryPrediction = useCallback(() => setPredictionRetry((r) => r + 1), [])
  useEffect(() => {
    const controller = new AbortController()
    getTournaments(controller.signal).then((data) => {
      setCatalog(data)
      const stages = data.flatMap((t) => t.seasons.flatMap((s) => s.stages))
      setStageId((current) => stages.some((s) => s.id === current) ? current : stages.some((s) => s.id === shared.current?.stageId) ? shared.current!.stageId : stages[0]?.id || '')
      if (!stages.length) setError('No tournament stages are configured yet.')
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [refresh])
  useEffect(() => {
    if (!stageId) return
    const controller = new AbortController()
    let inFlight = false
    setError(''); setNotice('')
    if (snapshotRef.current?.stage_id !== stageId) { setSnapshot(null); setResult(null) }
    const load = async () => {
      if (inFlight || controller.signal.aborted) return
      inFlight = true; setRefreshing(true)
      try {
        const next = await getStage(stageId, controller.signal)
        if (controller.signal.aborted) return
        const previous = snapshotRef.current
        const entering = lastAttached.current !== stageId
        const saved = entering ? (shared.current?.stageId === stageId ? shared.current : storedScenario(stageId)) : null
        const removed = useScenario.getState().attach(next, saved)
        if (removed) setNotice(`${removed} picks were removed because those fixtures now have results or are unavailable.`)
        else if (saved && saved.revision !== next.revision) setNotice('The saved scenario used an older table. Its remaining valid picks have been restored.')
        else if (previous?.stage_id === stageId && previous.revision !== next.revision) setNotice('New results arrived. The table and your remaining picks have been refreshed.')
        if (shared.current?.stageId === stageId) { useScenario.getState().setMode('sandbox'); shared.current = null }
        lastAttached.current = stageId; snapshotRef.current = next
        setSnapshot(next); setError('')
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message) }
      finally { inFlight = false; if (!controller.signal.aborted) setRefreshing(false) }
    }
    void load()
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 60000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [stageId, refresh])
  const active = snapshot?.stage_id === stageId ? snapshot : null
  const sandbox = scenario.mode === 'sandbox'
  const picks = useMemo(() => sandbox && scenario.stageId === stageId ? scenario.overrides : {}, [sandbox, scenario.stageId, scenario.overrides, stageId])
  const iterations = sandbox ? 1000 : 10000
  const key = active ? predictionKey(active.stage_id, active.revision, picks, scenario.model, scenario.washoutProbability, iterations) : ''
  const prediction = result?.key === key ? result.value : null
  useEffect(() => {
    if (!active || scenario.stageId !== active.stage_id || !active.rules.schedule_complete) { setBusy(false); return }
    const controller = new AbortController()
    setBusy(true); setPredictionError('')
    const timer = setTimeout(() => {
      predict(active.stage_id, picks, iterations, scenario.model, scenario.washoutProbability, controller.signal)
        .then((value) => { if (!controller.signal.aborted && value.revision === active.revision) setResult({ key, value }) })
        .catch((e) => { if (!controller.signal.aborted) setPredictionError(e.message) })
        .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    }, 300)
    return () => { clearTimeout(timer); controller.abort() }
  }, [key, active?.rules.schedule_complete, scenario.stageId, predictionRetry])
  useEffect(() => {
    if (!active || scenario.stageId !== active.stage_id) return
    const saved: Scenario = { version: 1, stageId, revision: active.revision, overrides: scenario.overrides, model: scenario.model, washoutProbability: scenario.washoutProbability }
    try { localStorage.setItem(`crease:scenario:v1:${stageId}`, JSON.stringify(saved)) } catch { /* Storage limits must not block predictions. */ }
  }, [stageId, active?.revision, scenario.stageId, scenario.overrides, scenario.model, scenario.washoutProbability])
  const rows = useMemo(() => active ? projectedTable(active, picks) : [], [active, picks])
  return { catalog, stageId, selectStage: setStageId, snapshot: active, rows, prediction, sandbox, scenario,
    error, predictionError, notice, setNotice, busy, refreshing, retry, retryPrediction }
}

import type { Job, Prediction, Snapshot, Tournament, Outcome, LiveFeed } from './types'
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { cache: 'no-store', ...options })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : response.status >= 500 ? 'CricMatrix cannot reach the API. Check that the backend is running on port 8010, then retry.' : `Request failed (${response.status})`)
  }
  return response.json()
}
export const getTournaments = (signal: AbortSignal) => request<Tournament[]>('/tournaments', { signal })
export const getStage = (id: string, signal: AbortSignal) => request<Snapshot>(`/stages/${id}`, { signal })
export const getLiveFeed = (signal: AbortSignal) => request<LiveFeed>('/live', { signal })
export async function predict(stage: string, overrides: Record<string, Outcome>, iterations: number, model: string, washoutProbability: number, signal: AbortSignal): Promise<Prediction> {
  let job = await request<Job>(`/stages/${stage}/predictions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ overrides, iterations, model, washout_probability: washoutProbability }), signal })
  return pollPrediction(job, signal)
}
export async function forecastCompetition(id: string, body: Record<string, unknown>, signal: AbortSignal): Promise<Prediction> {
  const job = await request<Job>(`/competitions/${id}/forecast`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal })
  return pollPrediction(job, signal)
}
async function pollPrediction(initial: Job, signal: AbortSignal): Promise<Prediction> {
  let job = initial
  for (let i = 0; i < 120; i++) {
    if (job.status === 'completed' && job.result) return job.result
    if (job.status === 'failed') throw new Error(job.error || 'Simulation failed')
    await new Promise<void>((resolve, reject) => {
      const onAbort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
      const timer = setTimeout(() => { signal.removeEventListener('abort', onAbort); resolve() }, 500)
      if (signal.aborted) onAbort()
      else signal.addEventListener('abort', onAbort, { once: true })
    })
    job = await request<Job>(`/predictions/${job.id}`, { signal })
  }
  throw new Error('Simulation is taking longer than expected. Please retry.')
}

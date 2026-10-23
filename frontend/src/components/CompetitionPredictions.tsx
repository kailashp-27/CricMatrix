import { useEffect, useState } from 'react'
import { LoaderCircle, RotateCcw } from 'lucide-react'
import { forecastCompetition } from '../api'
import type { Outcome, Prediction } from '../types'

type ScheduledMatch = { id: string; name: string; teams: string[]; starts_at: string; venue: string; format: string; state: string; status: string; outcome: Outcome | null; unresolved_result: boolean }
type Analysis = { series_id: string; name: string; fixtures: ScheduledMatch[]; fetched_at: string | null; schedule_complete: boolean; qualification_eligible: boolean; qualification_blocker: string | null; teams: { id: string; name: string }[]; simulation_basis: string; assumptions: string[] }
type Results = { baseline: Prediction; scenario: Prediction; key: string }

export function CompetitionPredictions({ seriesId, refreshToken }: { seriesId: string; refreshToken: number }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [loadError, setLoadError] = useState('')
  const [forecastError, setForecastError] = useState('')
  const [picks, setPicks] = useState<Record<string, Outcome>>({})
  const [spots, setSpots] = useState(2)
  const [model, setModel] = useState('equal')
  const [rain, setRain] = useState(3)
  const [accepted, setAccepted] = useState(false)
  const [requested, setRequested] = useState(false)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<Results | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    setAnalysis(null); setPicks({}); setRequested(false); setAccepted(false); setResults(null); setShowAll(false)
    const controller = new AbortController()
    let inFlight = false
    const load = async () => {
      if (inFlight || controller.signal.aborted) return
      inFlight = true
      try {
        const response = await fetch(`/api/competitions/${seriesId}/analysis`, { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error('The fetched fixture schedule could not be loaded.')
        const next: Analysis = await response.json()
        if (!controller.signal.aborted) {
          setAnalysis(next); setLoadError(''); setSpots((value) => Math.max(1, Math.min(value, next.teams.length)))
          const pending = new Set(next.fixtures.filter((m) => m.state !== 'completed' && !m.unresolved_result).map((m) => m.id))
          setPicks((current) => Object.fromEntries(Object.entries(current).filter(([id]) => pending.has(id))))
        }
      } catch (e) { if (!controller.signal.aborted) setLoadError((e as Error).message) }
      finally { inFlight = false }
    }
    void load()
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 60000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [seriesId, refreshToken])
  const key = JSON.stringify([seriesId, analysis?.fetched_at, spots, model, rain, picks])
  useEffect(() => {
    if (!requested || !accepted || !analysis?.qualification_eligible) { setBusy(false); return }
    const controller = new AbortController()
    setBusy(true); setForecastError('')
    const timer = setTimeout(async () => {
      const body = { qualifying_spots: spots, accept_points_assumptions: true, model, iterations: 10000, washout_probability: rain / 100 }
      try {
        const baselinePromise = forecastCompetition(seriesId, { ...body, overrides: {} }, controller.signal)
        const scenarioPromise = Object.keys(picks).length ? forecastCompetition(seriesId, { ...body, overrides: picks }, controller.signal) : baselinePromise
        const [baseline, scenario] = await Promise.all([baselinePromise, scenarioPromise])
        if (baseline.revision !== scenario.revision) throw new Error('The stored results changed during calculation. Refresh the table and calculate again.')
        if (!controller.signal.aborted) setResults({ baseline, scenario, key })
      } catch (e) { if (!controller.signal.aborted) setForecastError((e as Error).message) }
      finally { if (!controller.signal.aborted) setBusy(false) }
    }, 350)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [key, requested, accepted, analysis?.qualification_eligible, retry])
  const currentResults = results?.key === key && accepted ? results : null
  const remaining = (analysis?.fixtures || []).filter((match) => match.state !== 'completed')
  const upcoming = remaining.filter((match) => match.state === 'upcoming' && Date.parse(match.starts_at) >= Date.now())
  const next = upcoming[0]
  const pick = (id: string, outcome: Outcome) => setPicks((current) => {
    const updated = { ...current }
    if (updated[id] === outcome) delete updated[id]
    else updated[id] = outcome
    return updated
  })
  return <section className="prediction-workspace" aria-label="Qualification predictions and upcoming matches">
    <div className="live-heading"><div><span className="tiny-label">NEXT MATCH / WHAT IF?</span><h2>See how each result changes the race</h2></div></div>
    {loadError && <p className="error" role="alert">{loadError}</p>}
    {!analysis && !loadError && <p className="live-description">Loading the fetched schedule…</p>}
    {analysis && <>
      {next ? <article className="next-match"><span className="tiny-label">NEXT SCHEDULED MATCH</span><h3>{next.teams.join(' vs ')}</h3><p>{new Date(next.starts_at).toLocaleString()} · {next.venue}</p></article> : <p className="live-description">{remaining.length ? 'No future start time is available. Remaining provider fixtures are in progress, overdue or unresolved.' : 'No remaining matches in the fetched schedule.'}</p>}
      <div className="prediction-settings"><label>Assumed qualifying spots<select value={spots} onChange={(e) => setSpots(Number(e.target.value))}>{analysis.teams.map((_, index) => <option key={index + 1} value={index + 1}>Top {index + 1}</option>)}</select></label><label>Match model<select value={model} onChange={(e) => setModel(e.target.value)}><option value="equal">Equal chance / 50:50</option><option value="record">Smoothed fetched win/loss records</option></select></label><label>No-result chance<select value={rain} onChange={(e) => setRain(Number(e.target.value))}>{[0, 3, 5, 10, 20].map((value) => <option key={value} value={value}>{value}%</option>)}</select></label></div>
      <label className="assumption-choice"><input type="checkbox" checked={accepted} onChange={(e) => { setAccepted(e.target.checked); if (!e.target.checked) setRequested(false) }} />Use a 2 points/win, 1/no-result, 0/loss Top {spots} scenario. Randomize points ties because NRR is unavailable. These are model assumptions, not verified official qualification rules.</label>
      {!analysis.qualification_eligible && <p className="notice">Qualification estimates unavailable: {analysis.qualification_blocker}</p>}
      <div className="prediction-actions"><button className="primary-button" disabled={!accepted || !analysis.qualification_eligible || busy} onClick={() => { setRequested(true); setRetry((v) => v + 1) }}>{busy && <LoaderCircle size={15} className="spin" />}{busy ? 'Calculating every team…' : 'Calculate qualification chances'}</button><button className="reset-picks" disabled={!Object.keys(picks).length} onClick={() => setPicks({})}><RotateCcw size={13} />Reset picks</button><span>{Object.keys(picks).length} selected results</span></div>
      {forecastError && <p className="error" role="alert">{forecastError}</p>}
      {currentResults && <div className="qualification-results" aria-live="polite"><h3>Every team: baseline vs your scenario</h3><div className="table-scroll"><table><caption className="sr-only">Qualification estimates under the selected scenario assumptions. Change is measured in percentage points.</caption><thead><tr><th className="team-cell" scope="col">TEAM</th><th scope="col">BASELINE</th><th scope="col">YOUR SCENARIO</th><th scope="col">CHANGE</th><th scope="col">MODEL POINTS</th></tr></thead><tbody>{currentResults.scenario.standings.map((team) => {
        const baseline = currentResults.baseline.probabilities.find((p) => p.team_id === team.id)!
        const scenario = currentResults.scenario.probabilities.find((p) => p.team_id === team.id)!
        const change = scenario.qualification_pct - baseline.qualification_pct
        return <tr key={team.id}><th className="team-cell" scope="row">{team.name}</th><td>{baseline.qualification_pct.toFixed(1)}%</td><td className="points">{scenario.qualification_pct.toFixed(1)}%</td><td className={change > 0.05 ? 'chance-increase' : change < -0.05 ? 'chance-decrease' : ''}>{change > 0.05 ? '+' : ''}{Math.abs(change) < 0.05 ? '0.0' : change.toFixed(1)} pp</td><td>{team.points}</td></tr>
      })}</tbody></table></div><p className="live-footnote">10,000 simulations · Changes are percentage points under the same model. Small changes may reflect sampling noise. {analysis.simulation_basis} Unknown NRR ties are randomized.</p></div>}
      <div className="fixture-picks"><h3>Pick the remaining results</h3><p className="live-description">Select a winner or no-result. Once calculated, chances and each team's change update when you edit a pick. Completed matches stay fixed.</p>{(showAll ? remaining : remaining.slice(0, 6)).map((match) => <article className={`fixture-pick ${picks[match.id] ? 'has-pick' : ''}`} key={match.id}><div><span className="tiny-label">{match.state === 'live' ? 'PROVIDER: IN PROGRESS' : Date.parse(match.starts_at) < Date.now() ? 'AWAITING PROVIDER UPDATE' : 'SCHEDULED'}</span><h4>{match.teams.join(' vs ')}</h4><p>{new Date(match.starts_at).toLocaleString()} · {match.status}</p></div><div className="fixture-outcomes"><button aria-pressed={picks[match.id] === 'home'} disabled={match.state === 'unknown'} onClick={() => pick(match.id, 'home')}>{match.teams[0]} wins</button><button aria-pressed={picks[match.id] === 'washout'} disabled={match.state === 'unknown'} onClick={() => pick(match.id, 'washout')}>No result</button><button aria-pressed={picks[match.id] === 'away'} disabled={match.state === 'unknown'} onClick={() => pick(match.id, 'away')}>{match.teams[1]} wins</button></div></article>)}{remaining.length > 6 && <button className="reset-picks" onClick={() => setShowAll((v) => !v)}>{showAll ? 'Show fewer matches' : `Show all ${remaining.length} remaining matches`}</button>}</div>
      <p className="live-footnote">Schedule retrieved: {analysis.fetched_at ? new Date(analysis.fetched_at).toLocaleString() : 'Unavailable'}. Daily snapshots can lag match events. Estimates are not official qualification probabilities or validated match forecasts.</p>
    </>}
  </section>
}

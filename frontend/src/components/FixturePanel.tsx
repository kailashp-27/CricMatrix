import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, CloudRain, RotateCcw } from 'lucide-react'
import { filterFixtures } from '../domain'
import type { Outcome, Snapshot } from '../types'

export function FixturePanel({ snapshot, sandbox, overrides, teamId, onTeam, onPick, onReset }: {
  snapshot: Snapshot; sandbox: boolean; overrides: Record<string, Outcome>; teamId: string;
  onTeam: (id: string) => void; onPick: (id: string, value: Outcome) => void; onReset: () => void;
}) {
  const [view, setView] = useState<'remaining' | 'results' | 'all'>('remaining')
  const [limit, setLimit] = useState(9)
  const teams = useMemo(() => new Map(snapshot.teams.map((t) => [t.id, t])), [snapshot.teams])
  const fixtures = useMemo(() => filterFixtures(snapshot.fixtures, teamId, view), [snapshot.fixtures, teamId, view])
  useEffect(() => setLimit(9), [snapshot.stage_id, teamId, view])
  const picks = Object.keys(overrides).length
  return <section className="fixture-section" id="fixtures"><div className="section-heading"><div><span className="section-number">02 /</span><h2>The matches that matter</h2><span className="count-pill">{fixtures.length} fixtures</span></div><div className="fixture-actions">{sandbox && <><span>{picks} picked</span><button disabled={!picks} onClick={onReset}><RotateCcw size={13} />Reset picks</button></>}</div></div>
    <div className="fixture-toolbar"><div className="view-tabs" aria-label="Fixture view">{(['remaining', 'results', 'all'] as const).map((value) => <button key={value} className={value === view ? 'active' : ''} aria-pressed={value === view} onClick={() => setView(value)}>{value === 'remaining' ? 'To play' : value === 'results' ? 'Results' : 'All matches'}</button>)}</div><div className="select-wrap"><label className="sr-only" htmlFor="fixture-team">Filter fixtures by team</label><select id="fixture-team" value={teamId} onChange={(e) => onTeam(e.target.value)}><option value="">Every team</option>{snapshot.teams.map((t) => <option value={t.id} key={t.id}>{t.name}</option>)}</select><ChevronDown size={13} /></div></div>
    <p className="section-description">{sandbox ? 'Choose an outcome. Your table changes immediately; new odds follow. Click a pick again to undo it.' : 'Switch to What if? to pick the remaining results. Completed matches stay fixed.'}</p>
    <div className="fixture-grid">{fixtures.slice(0, limit).map((match) => {
      const home = teams.get(match.home_id)!, away = teams.get(match.away_id)!
      const finished = match.outcome !== 'pending'
      const chosen = finished ? match.outcome : sandbox && Object.hasOwn(overrides, match.id) ? overrides[match.id] : undefined
      return <article className={`fixture-card ${chosen && !finished ? 'has-pick' : ''}`} key={match.id}>
        <div className="fixture-meta"><span>{finished ? 'RESULT' : chosen ? 'YOUR PICK' : 'TO PLAY'}</span><span>{new Date(match.starts_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })} / {new Date(match.starts_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })} UTC</span></div>
        <div className="fixture-teams"><span style={{ color: home.color }}>{home.short_name}</span><small>vs</small><span style={{ color: away.color }}>{away.short_name}</span></div><div className="fixture-venue">{match.venue}</div>
        {finished ? <p className="result-label">{match.outcome === 'washout' ? 'No result / 1 point each' : `${match.outcome === 'home' ? home.name : away.name} won`}</p> : <div className="outcomes">{(['home', 'washout', 'away'] as const).map((outcome) => <button key={outcome} disabled={!sandbox} className={chosen === outcome ? 'picked' : ''} aria-pressed={chosen === outcome} aria-label={`${home.short_name} versus ${away.short_name}: ${outcome === 'washout' ? 'washout' : `${outcome === 'home' ? home.name : away.name} wins`}`} onClick={() => onPick(match.id, outcome)}>{chosen === outcome ? <Check size={12} /> : outcome === 'washout' ? <CloudRain size={12} /> : null}{outcome === 'washout' ? 'Washout' : `${outcome === 'home' ? home.short_name : away.short_name} wins`}</button>)}</div>}
      </article>
    })}</div>
    {!fixtures.length && <div className="empty-state">No {view === 'results' ? 'completed' : view === 'remaining' ? 'remaining' : ''} fixtures match this view.{teamId && <button onClick={() => onTeam('')}>Show every team</button>}</div>}
    {fixtures.length > limit && <button className="load-more" onClick={() => setLimit((n) => n + 9)}>Show {Math.min(9, fixtures.length - limit)} more matches <span>({fixtures.length - limit} left)</span></button>}
  </section>
}

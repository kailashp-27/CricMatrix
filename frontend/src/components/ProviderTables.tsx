import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { CompetitionPredictions } from './CompetitionPredictions'

type Standing = { team_id: string; name: string; short_name: string | null; group: string | null; played: number; won: number; lost: number; tied: number; no_result: number; points: number | null; nrr: number | null }
type Competition = { id: string; name: string; rows: Standing[]; fetched_at: string | null; stale: boolean; status: string; error: string | null; points_available: boolean; nrr_available: boolean; missing_teams: string[] }
type Tables = { provider: string; poll_seconds: number; competitions: Competition[]; note: string }

export function ProviderTables() {
  const [data, setData] = useState<Tables | null>(null)
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let inFlight = false
    const load = async () => {
      if (inFlight || controller.signal.aborted) return
      inFlight = true; setLoading(true)
      try {
        const response = await fetch('/api/standings', { cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error('The provider tables could not be loaded. Please retry.')
        const next: Tables = await response.json()
        if (!controller.signal.aborted) { setData(next); setError('') }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message) }
      finally { inFlight = false; if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 60000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [refresh])
  const competitions = data?.competitions || []
  const current = competitions.find((c) => c.id === selected) || competitions[0]
  const groups = current?.rows.some((r) => r.group)
  return <section className="provider-standings table-panel" id="table" aria-label="Fetched tournament tables">
    <div className="live-heading"><div><span className="tiny-label">TOURNAMENT TABLES / CRICKETDATA</span><h2>Tables from the provider</h2></div><button disabled={loading} onClick={() => setRefresh((v) => v + 1)}><RefreshCw size={13} className={loading ? 'spin' : ''} />Refresh</button></div>
    <div className="provider-table-select"><label htmlFor="provider-tournament">Tournament / series</label><select id="provider-tournament" value={current?.id || ''} disabled={!competitions.length} onChange={(e) => setSelected(e.target.value)}>{!competitions.length && <option value="">No fetched competitions available</option>}{competitions.map((competition) => <option key={competition.id} value={competition.id}>{competition.name}</option>)}</select></div>
    {error && <p className="error" role="alert">{error}</p>}
    {current && <div className={`feed-status ${current.stale ? 'feed-stale' : ''}`} role="status"><strong>{current.rows.length ? current.stale ? 'Last fetched table / refresh delayed' : 'Fetched provider table' : 'Provider table unavailable'}</strong><span>{current.fetched_at ? `Retrieved ${new Date(current.fetched_at).toLocaleString()}` : 'Waiting for a successful provider response'}</span><span>Provider refresh: every {Math.ceil((data?.poll_seconds || 86400) / 3600)} hours</span></div>}
    {current?.rows.length ? <>
      {current.missing_teams.length > 0 && <p className="notice">Incomplete provider table: {current.missing_teams.join(', ')} appear in the fixtures but are missing from the table response.</p>}
      <div className="table-scroll"><table><caption className="sr-only">{current.name}. Team statistics fetched from CricketData. Row order is supplied by the provider, not a verified qualification ranking.</caption><thead><tr><th scope="col" className="team-cell">TEAM</th>{groups && <th scope="col">GROUP</th>}<th scope="col">P</th><th scope="col">W</th><th scope="col">L</th><th scope="col">T</th><th scope="col">NR</th><th scope="col">PTS</th><th scope="col">NRR</th></tr></thead><tbody>{current.rows.map((row) => <tr key={row.team_id}><th scope="row" className="team-cell"><span className="provider-team-name">{row.name}</span>{row.short_name && <span className="provider-team-short">{row.short_name}</span>}</th>{groups && <td>{row.group || '—'}</td>}<td>{row.played}</td><td>{row.won}</td><td>{row.lost}</td><td>{row.tied}</td><td>{row.no_result}</td><td className="points">{row.points ?? '—'}</td><td>{row.nrr === null ? '—' : row.nrr.toFixed(3)}</td></tr>)}</tbody></table></div>
      <p className="live-footnote">P: played · W: won · L: lost · T: tied · NR: no result. Row order comes from the provider.</p>
      {(!current.points_available || !current.nrr_available) && <p className="notice">{!current.points_available && 'Points are not supplied for this table. '}{!current.nrr_available && 'NRR is not supplied for this table. '}Missing values are shown as —.</p>}
    </> : <p className="live-description">{loading ? 'Loading fetched tournament tables…' : current?.error ? 'The provider request failed. No replacement table has been generated.' : 'CricketData has not supplied a table for this competition. No demonstration results are shown.'}</p>}
    <p className="live-footnote">{data?.note || 'Tables use fetched provider statistics only.'} Refresh reads the stored snapshot and does not spend another provider request.</p>
    {current && <CompetitionPredictions key={current.id} seriesId={current.id} refreshToken={refresh} />}
  </section>
}

import { useEffect, useState } from 'react'
import { ArrowUpRight, RefreshCw } from 'lucide-react'
import { getLiveFeed } from '../api'
import type { LiveFeed } from '../types'

export function LiveMatches() {
  const [feed, setFeed] = useState<LiveFeed | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [format, setFormat] = useState('all')
  const [competition, setCompetition] = useState('all')
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    let inFlight = false
    const load = async () => {
      if (inFlight || controller.signal.aborted) return
      inFlight = true; setLoading(true)
      try {
        const next = await getLiveFeed(controller.signal)
        if (!controller.signal.aborted) { setFeed(next); setError('') }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message) }
      finally { inFlight = false; if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load() }, 60000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [refresh])
  const matches = (feed?.matches || []).filter((match) =>
    (format === 'all' || match.format === format) &&
    (competition === 'all' || match.series_id === competition) &&
    `${match.title} ${match.series_name || ''} ${match.venue || ''} ${match.status}`.toLowerCase().includes(query.toLowerCase()))
  const formats = Array.from(new Set((feed?.matches || []).map((m) => m.format).filter(Boolean))) as string[]
  const competitions = Array.from(new Map((feed?.matches || []).filter((m) => m.series_id).map((m) => [m.series_id!, m.series_name || `Series ${m.series_id!.slice(0, 8)}`])).entries())
  const provider = feed?.provider === 'cricketdata' ? 'CricketData' : 'ESPNcricinfo RSS'
  return <section className="live-panel" aria-label="Matches across competitions">
    <div className="live-heading"><div><span className="tiny-label">AROUND THE GROUNDS</span><h2>Cricket across competitions</h2></div><button onClick={() => setRefresh((v) => v + 1)} disabled={loading}><RefreshCw size={13} className={loading ? 'spin' : ''} />Refresh</button></div>
    <p className="live-description">Follow the matches available from the score feed. Search teams and venues across domestic and international cricket.</p>
    <div className={`feed-status ${feed?.stale ? 'feed-stale' : ''}`} role="status">
      <strong>{!feed ? 'Loading score feed…' : !feed.enabled ? 'Score feed paused' : feed.stale ? 'Feed delayed / freshness unverified' : 'Score feed available'}</strong>
      {feed && <span>{provider}{feed.observed_at ? ` · ${feed.timestamp_basis === 'publisher' ? 'Published' : 'Retrieved'} ${new Date(feed.observed_at).toLocaleString()}` : ' · Waiting for the first successful fetch'}</span>}
      {feed?.error && <span>Refresh failed. Showing the last available scores.</span>}
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="live-filters"><label><span className="sr-only">Search score feed</span><input type="search" placeholder="Search team, venue or competition…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>{competitions.length > 0 && <label><span className="sr-only">Competition</span><select value={competition} onChange={(e) => setCompetition(e.target.value)}><option value="all">All competitions</option>{competitions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>}{formats.length > 0 && <label><span className="sr-only">Match format</span><select value={format} onChange={(e) => setFormat(e.target.value)}><option value="all">All formats</option>{formats.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}</select></label>}<span>{matches.length} matches</span></div>
    <div className="live-match-grid">{matches.map((match) => <article className="live-match" key={match.id}>
      <div className="live-meta"><span>{match.series_name || (match.series_id ? `Series ${match.series_id.slice(0, 8)}` : 'Competition not supplied')}</span><span>{feed?.stale ? 'DELAYED' : match.state === 'unknown' ? 'SCORE UPDATE' : match.state.toUpperCase()}</span></div>
      <h3>{match.title}</h3>{match.scores.map((score, index) => <p key={index} className="live-score">{score}</p>)}
      <p className="live-match-status">{match.status}</p>{match.venue && <p className="live-match-status">{match.venue}</p>}
      {match.url && <a href={match.url} target="_blank" rel="noopener noreferrer">Scorecard on ESPNcricinfo <ArrowUpRight size={12} /></a>}
    </article>)}</div>
    {!matches.length && !loading && <p className="live-description">{query || format !== 'all' || competition !== 'all' ? 'No matches match these filters.' : feed?.last_success_at ? 'The provider returned no matches. Coverage varies by competition.' : 'No score snapshot is available yet. The server will retry automatically.'}</p>}
    <p className="live-footnote">{feed?.coverage || 'Coverage depends on the score provider.'} {feed?.truncated && 'The configured page limit was reached; this list is partial.'} Score headlines do not establish full schedules, standings or qualification rules.</p>
  </section>
}

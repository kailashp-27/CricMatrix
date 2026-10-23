import { useState } from 'react'
import { ArrowDownLeft, ChevronDown, CircleDot, Copy, Download, FlaskConical, LoaderCircle, Radio, RefreshCw, Trophy, X } from 'lucide-react'
import { useDashboard } from './useDashboard'
import { tableCSV } from './domain'
import { StandingsTable } from './components/StandingsTable'
import { FixturePanel } from './components/FixturePanel'
import { TeamFocus } from './components/TeamFocus'
import { LiveMatches } from './components/LiveMatches'
import type { Scenario } from './types'

export default function App() {
  const d = useDashboard()
  const [focused, setFocused] = useState('')
  const [copied, setCopied] = useState(false)
  const { snapshot, sandbox, scenario, prediction } = d
  const tournament = d.catalog.find((t) => t.seasons.some((s) => s.stages.some((g) => g.id === d.stageId)))
  const season = tournament?.seasons.find((s) => s.stages.some((g) => g.id === d.stageId))
  const pending = snapshot?.fixtures.filter((f) => f.outcome === 'pending').length || 0
  const completed = (snapshot?.fixtures.length || 0) - pending
  const focus = d.rows.find((t) => t.id === focused)
  const focusId = focus?.id || ''
  const odds = prediction?.probabilities || []
  const leader = d.rows[0]
  const selectStage = (id: string) => { d.selectStage(id); setFocused(''); setCopied(false) }
  const share = async () => {
    if (!snapshot) return
    const value: Scenario = { version: 1, stageId: snapshot.stage_id, revision: snapshot.revision, overrides: sandbox ? scenario.overrides : {}, model: scenario.model, washoutProbability: scenario.washoutProbability }
    const url = new URL(window.location.href)
    url.hash = `scenario=${encodeURIComponent(JSON.stringify(value))}`
    try { await navigator.clipboard.writeText(url.toString()); setCopied(true); setTimeout(() => setCopied(false), 2500) }
    catch { d.setNotice('Clipboard access is unavailable. Your picks are still saved in this browser.') }
  }
  const exportCSV = () => {
    if (!snapshot) return
    const url = URL.createObjectURL(new Blob([tableCSV(d.rows, odds)], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a'); link.href = url; link.download = `cricmatrix-${snapshot.stage_id}-${sandbox ? 'scenario' : 'table'}.csv`; link.click(); URL.revokeObjectURL(url)
  }
  return <div className="app-shell"><header className="topbar"><a className="brand" href="/" aria-label="CricMatrix home"><span className="brand-mark"><i /><i /><i /></span>CricMatrix<span className="brand-dot">.</span></a></header>
    <main><div className="eyebrow"><span /> THE ROAD TO THE PLAYOFFS</div><section className="intro"><div><h1>Every match changes<br />the <em>picture.</em></h1><p>The table tells you where teams stand.<br className="mobile-break" /> We show you where they could go.</p></div><div className="intro-note"><span className="tiny-label">A LITTLE SCIENCE. A LOT OF CRICKET.</span><p>Explore the odds.<br />Make your calls.<br />Find the path.</p><ArrowDownLeft className="note-arrow" size={62} strokeWidth={1} /></div></section>
      <LiveMatches />
      <p className="qualification-label">QUALIFICATION EXPLORER · CONFIGURED SEASONS</p>
      <section className="control-bar" aria-label="Tournament and mode"><div className="selectors"><div className="select-wrap"><Trophy size={17} /><label className="sr-only" htmlFor="tournament">Tournament</label><select id="tournament" value={tournament?.id || ''} onChange={(e) => { const t = d.catalog.find((v) => v.id === e.target.value); if (t?.seasons[0]?.stages[0]) selectStage(t.seasons[0].stages[0].id) }}>{!d.catalog.length && <option>Loading tournaments...</option>}{d.catalog.map((t) => <option value={t.id} key={t.id}>{t.name}</option>)}</select><ChevronDown size={14} /></div>
        <div className="select-wrap stage-select"><label className="sr-only" htmlFor="season">Season</label><select id="season" value={season?.id || ''} onChange={(e) => { const s = tournament?.seasons.find((v) => v.id === e.target.value); if (s?.stages[0]) selectStage(s.stages[0].id) }}>{tournament?.seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><ChevronDown size={14} /></div>
        {(season?.stages.length || 0) > 1 && <div className="select-wrap"><label className="sr-only" htmlFor="stage">Group or stage</label><select id="stage" value={d.stageId} onChange={(e) => selectStage(e.target.value)}>{season?.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select><ChevronDown size={14} /></div>}</div>
        <div className="segmented"><button className={!sandbox ? 'selected' : ''} aria-pressed={!sandbox} onClick={() => scenario.setMode('reality')}><Radio size={14} />Reality</button><button className={sandbox ? 'selected' : ''} aria-pressed={sandbox} onClick={() => scenario.setMode('sandbox')}><FlaskConical size={14} />What if?</button></div></section>
      <div className={`demo-banner ${snapshot?.sync?.stale ? 'stale-banner' : ''}`}><CircleDot size={13} /><span><strong>{snapshot?.source === 'demo' ? 'Synthetic demo season' : snapshot?.sync?.configured ? 'Stored provider snapshot' : 'Manually configured season'}</strong> / {snapshot?.source === 'demo' ? 'Illustrative fixtures, results, ratings and NRR. Not connected to provider results.' : snapshot?.sync?.stale ? 'The last sync is stale or failed. Showing the last complete snapshot.' : 'Data is served from the database, never fetched by visitors.'}</span><button onClick={d.retry} disabled={d.refreshing} title="Refresh stored table"><RefreshCw size={12} className={d.refreshing ? 'spin' : ''} />Refresh</button></div>
      {d.notice && <div className="notice" role="status"><span>{d.notice}</span><button onClick={() => d.setNotice('')} aria-label="Dismiss notice"><X size={14} /></button></div>}
      {d.error && <div className="error" role="alert">{d.error}<button onClick={d.retry}>Retry <RefreshCw size={13} /></button></div>}
      {!snapshot && !d.error && <div className="loading-state"><LoaderCircle className="spin" size={22} />Loading the cricket picture...</div>}
      {snapshot && <>{!snapshot.rules.schedule_complete && <div className="notice">This stage has an incomplete schedule. Predictions are disabled until every fixture is configured.</div>}{snapshot.nrr_trusted === false && <div className="notice">NRR is not verified for the latest results. Qualification estimates model unresolved NRR ties, including ties in a fully played schedule.</div>}
        <section className="stats-grid" aria-label="Season overview"><article><span className="tiny-label">SEASON PROGRESS</span><div className="stat-value">{completed}<span> / {snapshot.fixtures.length}</span></div><div className="stat-bottom"><span>matches completed</span><div className="mini-progress"><i style={{ width: `${100 * completed / Math.max(1, snapshot.fixtures.length)}%` }} /></div></div></article><article><span className="tiny-label">THE FINISH LINE</span><div className="stat-value">Top {snapshot.rules.qualifying_spots}<Trophy size={22} /></div><div className="stat-bottom">{d.rows.length} teams / {snapshot.name}</div></article><article className="leader-stat"><span className="tiny-label">SETTING THE PACE</span><div className="stat-value">{leader?.short_name}<span className="team-dot" style={{ background: leader?.color }} /></div><div className="stat-bottom">{leader?.points} points <span className="stat-divider">/</span> {leader?.remaining} matches to go</div></article></section>
        <div className="dashboard-grid"><section className="table-panel" id="table"><div className="section-heading"><div><span className="section-number">01 /</span><h2>{sandbox ? 'Your projected table' : 'The current picture'}</h2></div><span className="status-text" aria-live="polite">{d.busy ? <><LoaderCircle className="spin" size={12} />Updating odds...</> : prediction ? <><span className="status-dot" />{prediction.iterations.toLocaleString()} simulations</> : 'No estimate yet'}</span></div>
          <div className="table-actions"><span>{sandbox ? `${Object.keys(scenario.overrides).length} picks / saved in this browser` : `Revision ${snapshot.revision} / points, then ${snapshot.rules.tie_breakers.join(', ')}`}</span><div><button onClick={share}><Copy size={12} />{copied ? 'Link copied' : 'Copy scenario'}</button><button onClick={exportCSV}><Download size={12} />CSV</button></div></div>
          {d.predictionError && <div className="error prediction-error" role="alert">{d.predictionError}<button onClick={d.retryPrediction}>Retry odds</button></div>}
          <StandingsTable rows={d.rows} baseline={snapshot.standings} probabilities={odds} spots={snapshot.rules.qualifying_spots} focused={focusId} busy={d.busy} onFocus={setFocused} />
          <section className="model-controls" aria-label="Simulation assumptions"><div><label htmlFor="model">Match model</label><div className="select-wrap"><select id="model" value={scenario.model} onChange={(e) => scenario.setModel(e.target.value as 'equal' | 'rating')}><option value="equal">Equal chance / 50:50</option><option value="rating">Configured Elo ratings</option></select><ChevronDown size={12} /></div></div><div><label htmlFor="rain">Washout chance <strong>{Math.round(scenario.washoutProbability * 100)}%</strong></label><input id="rain" type="range" min="0" max="50" step="1" value={Math.round(scenario.washoutProbability * 100)} onChange={(e) => scenario.setRain(Number(e.target.value) / 100)} /></div><p>Future NRR is approximated through random tie-breaks. These are model estimates, not match forecasts.</p></section>
        </section></div><section className="scenario-section" aria-label="Team analysis and scenario builder"><TeamFocus team={focus} probability={odds.find((p) => p.team_id === focusId)} sandbox={sandbox} onMode={() => scenario.setMode(sandbox ? 'reality' : 'sandbox')} /></section>
        <FixturePanel snapshot={snapshot} sandbox={sandbox} overrides={scenario.overrides} teamId={focusId} onTeam={setFocused} onPick={scenario.toggle} onReset={scenario.reset} />
        <section className="methodology" id="how-it-works"><span className="section-number">THE METHOD /</span><div><h3>Probabilities, with perspective.</h3><p>We run {sandbox ? '1,000' : '10,000'} simulations of the remaining schedule. World Cup groups are independent. Exact Top-k checks find points elimination, allowing favorable unresolved ties and washouts. A sampled 0% alone never earns an E.</p></div><div><h3>Results need more than a winner.</h3><p>Picks change points, not NRR. Confidence intervals describe sampling error, not the uncertainty of the match model. The table checks for stored updates every minute. Completed picks are removed when new results arrive.</p><span className="snapshot-time">Snapshot updated: {new Date(snapshot.updated_at).toLocaleString()} / {snapshot.sync?.last_success_at ? `Last sync: ${new Date(snapshot.sync.last_success_at).toLocaleString()}` : 'No successful provider sync'}</span></div></section>
      </>}<footer><a className="brand" href="/">CricMatrix<span className="brand-dot">.</span></a><span>Cricket is a game of possibilities.</span><span className="footer-build">QUALIFICATION LAB / V0.3</span></footer>
    </main></div>
}

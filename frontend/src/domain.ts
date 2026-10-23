import type { Outcome, Snapshot, Row, Scenario, Probability, Fixture } from './types.ts'

const outcomes = new Set(['home', 'away', 'washout'])
const idPattern = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$/

export function projectedTable(snapshot: Snapshot, overrides: Record<string, Outcome>): Row[] {
  const rows = Object.fromEntries(snapshot.standings.map((t) => [t.id, { ...t }]))
  for (const match of snapshot.fixtures) {
    const outcome = Object.hasOwn(overrides, match.id) ? overrides[match.id] : undefined
    if (!outcome || match.outcome !== 'pending') continue
    const home = rows[match.home_id], away = rows[match.away_id]
    for (const team of [home, away]) { team.played++; team.remaining-- }
    if (outcome === 'washout') {
      for (const team of [home, away]) { team.points += snapshot.rules.washout_points; team.washouts++ }
    } else {
      const [winner, loser] = outcome === 'home' ? [home, away] : [away, home]
      winner.points += snapshot.rules.win_points; winner.won++
      loser.points += snapshot.rules.loss_points; loser.lost++
    }
  }
  return Object.values(rows).sort((a, b) => {
    if (a.points !== b.points) return b.points - a.points
    for (const field of snapshot.rules.tie_breakers) {
      const difference = field === 'wins' ? b.won - a.won : b.nrr - a.nrr
      if (difference !== 0) return difference
    }
    return a.id.localeCompare(b.id)
  }).map((t, i) => ({ ...t, rank: i + 1, max_points: t.points + t.remaining * snapshot.rules.win_points }))
}

export function validPicks(snapshot: Snapshot, picks: Record<string, Outcome>): Record<string, Outcome> {
  const remaining = new Set(snapshot.fixtures.filter((f) => f.outcome === 'pending').map((f) => f.id))
  return Object.fromEntries(Object.entries(picks).filter(([id, value]) => remaining.has(id) && outcomes.has(value)))
}

export function parseScenario(value: string): Scenario | null {
  if (value.length > 30000) return null
  try {
    const data = JSON.parse(value) as Partial<Scenario>
    if (!data || data.version !== 1 || typeof data.stageId !== 'string' || !idPattern.test(data.stageId) || !Number.isInteger(data.revision) || data.revision! < 1) return null
    if (!data.overrides || typeof data.overrides !== 'object' || Array.isArray(data.overrides)) return null
    const entries = Object.entries(data.overrides)
    if (entries.length > 200 || entries.some(([id, outcome]) => !idPattern.test(id) || !outcomes.has(outcome))) return null
    if (!['equal', 'rating'].includes(data.model || '') || typeof data.washoutProbability !== 'number' || !Number.isFinite(data.washoutProbability) || data.washoutProbability < 0 || data.washoutProbability > 0.5) return null
    return { version: 1, stageId: data.stageId, revision: data.revision!, overrides: Object.fromEntries(entries), model: data.model!, washoutProbability: data.washoutProbability }
  } catch { return null }
}

export function predictionKey(stageId: string, revision: number, picks: Record<string, Outcome>, model: string, rain: number, iterations: number): string {
  return JSON.stringify([stageId, revision, Object.entries(picks).sort(([a], [b]) => a.localeCompare(b)), model, rain, iterations])
}

export function filterFixtures(fixtures: Fixture[], teamId: string, view: 'remaining' | 'results' | 'all'): Fixture[] {
  return fixtures.filter((m) => (!teamId || m.home_id === teamId || m.away_id === teamId) && (view === 'all' || (view === 'remaining' ? m.outcome === 'pending' : m.outcome !== 'pending')))
}

export function tableCSV(rows: Row[], probabilities: Probability[]): string {
  const byId = new Map(probabilities.map((p) => [p.team_id, p]))
  const cell = (value: string | number) => {
    const text = typeof value === 'string' && /^[=+@\-\t\r]/.test(value) ? `'${value}` : String(value)
    return `"${text.replaceAll('"', '""')}"`
  }
  const header = ['Rank', 'Team', 'Played', 'Won', 'Lost', 'No result', 'Points', 'Snapshot NRR', 'Maximum points', 'Qualification percent', '95% lower', '95% upper', 'Status']
  const values = rows.map((r) => { const p = byId.get(r.id); return [r.rank, r.name, r.played, r.won, r.lost, r.washouts, r.points, r.nrr, r.max_points, p?.qualification_pct ?? '', p?.interval_95[0] ?? '', p?.interval_95[1] ?? '', p?.status ?? 'pending'] })
  return [header, ...values].map((r) => r.map(cell).join(',')).join('\r\n')
}

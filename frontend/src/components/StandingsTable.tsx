import { ArrowDown, ArrowUpRight } from 'lucide-react'
import type { Probability, Row } from '../types'

export function StandingsTable({ rows, baseline, probabilities, spots, focused, busy, onFocus }: {
  rows: Row[]; baseline: Row[]; probabilities: Probability[]; spots: number; focused: string; busy: boolean; onFocus: (id: string) => void;
}) {
  const odds = new Map(probabilities.map((p) => [p.team_id, p]))
  const positions = new Map(baseline.map((r) => [r.id, r.rank]))
  return <><div className="table-scroll"><table><caption className="sr-only">Points table. Qualification estimates use the selected probability model.</caption>
    <thead><tr><th scope="col" className="rank-cell">#</th><th scope="col" className="team-cell">TEAM</th><th scope="col">P</th><th scope="col">W</th><th scope="col">L</th><th scope="col">NR</th><th scope="col">NRR*</th><th scope="col">PTS</th><th scope="col" className="chance-cell">QUALIFICATION</th></tr></thead>
    <tbody>{rows.map((team, i) => {
      const probability = odds.get(team.id)
      const movement = (positions.get(team.id) || team.rank) - team.rank
      return <tr key={team.id} className={`${i === spots - 1 ? 'cutoff-row' : ''} ${focused === team.id ? 'focused-row' : ''} ${probability?.status === 'eliminated' ? 'eliminated-row' : ''}`}>
        <td className="rank-cell">{team.rank}</td><th scope="row" className="team-cell"><button className="team-identity team-button" onClick={() => onFocus(focused === team.id ? '' : team.id)} aria-pressed={focused === team.id} title={`Focus on ${team.name}`}>
          <span className="team-monogram" style={{ color: team.color, borderColor: `${team.color}33`, background: `${team.color}10` }}>{team.short_name.slice(0, 3)}</span><span><span className="team-short">{team.short_name}
            {probability?.status === 'eliminated' && <abbr title="Mathematically eliminated under the points model" className="elimination">E</abbr>}
            {probability?.status === 'qualified' && <abbr title="Qualified in the resolved table" className="qualified">Q</abbr>}
            {probability?.status === 'unknown' && <abbr title="Additional tie-break rules or a larger exact search are needed" className="elimination">?</abbr>}
          </span><span className="team-full">{team.name}</span></span>
          {movement !== 0 && <span className={`movement ${movement > 0 ? 'up' : 'down'}`} aria-label={`${Math.abs(movement)} places ${movement > 0 ? 'up' : 'down'}`}>{movement > 0 ? <ArrowUpRight size={12} /> : <ArrowDown size={12} />}{Math.abs(movement)}</span>}
        </button></th><td>{team.played}</td><td>{team.won}</td><td>{team.lost}</td><td>{team.washouts}</td><td className="nrr">{team.nrr > 0 ? '+' : ''}{team.nrr.toFixed(3)}</td><td className="points">{team.points}</td>
        <td className="chance-cell">{probability ? <div className="probability" title={`95% sampling interval: ${probability.interval_95[0]} to ${probability.interval_95[1]} percent. Model status: ${probability.status}.`}><span className="probability-track"><i style={{ width: `${probability.qualification_pct}%`, background: probability.status === 'eliminated' ? '#6c736b' : undefined }} /></span><span>{probability.qualification_pct.toFixed(1)}<small>%</small></span></div> : <span className="pending-chance">{busy ? '...' : '\u2014'}</span>}</td>
      </tr>
    })}</tbody></table></div><div className="table-legend"><span><i className="legend-line" />Top {spots} cutoff</span><span><b>E</b> Eliminated</span><span><b>?</b> Unresolved</span><span>*Snapshot NRR, not projected NRR</span></div></>
}

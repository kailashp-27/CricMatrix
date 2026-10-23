import { ArrowRight, FlaskConical } from 'lucide-react'
import type { Probability, Row } from '../types'

export function TeamFocus({ team, probability, sandbox, onMode }: { team?: Row; probability?: Probability; sandbox: boolean; onMode: () => void }) {
  return <aside className="insights"><div className="insight-icon"><FlaskConical size={20} /></div><span className="tiny-label">{team ? 'A CLOSER LOOK' : 'SCENARIO BUILDER'}</span>
    {team ? <><h2 style={{ color: team.color }}>{team.name}</h2><div className="focus-chance">{probability ? `${probability.qualification_pct.toFixed(1)}%` : '\u2014'}<small>qualification estimate</small></div>
      {probability && <p className="interval">95% sampling interval: {probability.interval_95[0]}% to {probability.interval_95[1]}%</p>}
      <dl className="focus-facts"><div><dt>Current position</dt><dd>#{team.rank}</dd></div><div><dt>Points / maximum</dt><dd>{team.points} / {team.max_points}</dd></div><div><dt>Matches left</dt><dd>{team.remaining}</dd></div><div><dt>Points status</dt><dd>{probability?.status || 'Calculating'}</dd></div></dl><p>{probability?.status === 'eliminated' ? 'No qualifying path remains under the supported points model.' : probability?.status === 'qualified' ? 'This team qualifies in the resolved table.' : 'Alive means a points-feasible path allowing favorable ties, not guaranteed qualification.'}</p></> : <><h2>Explore the playoff race.</h2><p>Select a team above for qualification details, or enter What-if mode and choose match outcomes below.</p></>}
    <button className="primary-button" onClick={onMode}>{sandbox ? 'Back to reality' : 'Try a what-if scenario'}<ArrowRight size={15} /></button>
  </aside>
}

import test from 'node:test'
import assert from 'node:assert/strict'
import { filterFixtures, parseScenario, predictionKey, projectedTable, tableCSV, validPicks } from '../src/domain.ts'
import type { Snapshot, Scenario } from '../src/types.ts'

function snapshot(): Snapshot {
  const teams = ['a', 'b', 'c', 'd'].map((id, i) => ({ id, name: `Team ${id}`, short_name: id.toUpperCase(), color: '#abcdef', nrr: 0.4 - i * 0.1, rating: 1500 }))
  const standings = teams.map((t) => ({ ...t, rank: t.id === 'a' ? 1 : t.id === 'c' ? 2 : t.id === 'b' ? 3 : 4, played: ['a', 'c'].includes(t.id) ? 1 : 0, won: 0, lost: 0, washouts: ['a', 'c'].includes(t.id) ? 1 : 0, points: ['a', 'c'].includes(t.id) ? 1 : 0, remaining: 1, max_points: ['a', 'c'].includes(t.id) ? 3 : 2 }))
  return { stage_id: 'stage-1', name: 'Test', source: 'demo', revision: 1, updated_at: '2027-04-01T00:00:00Z', teams, standings,
    rules: { qualifying_spots: 2, win_points: 2, loss_points: 0, washout_points: 1, tie_breakers: ['nrr'], team_count: 4, matches_per_team: null, stage_format: 'group', schedule_complete: true, regulation_overs: 20 },
    fixtures: [{ id: 'ab', home_id: 'a', away_id: 'b', starts_at: '2027-04-01T00:00:00Z', venue: 'Test', outcome: 'pending' }, { id: 'cd', home_id: 'c', away_id: 'd', starts_at: '2027-04-01T00:00:00Z', venue: 'Test', outcome: 'pending' }, { id: 'ac', home_id: 'a', away_id: 'c', starts_at: '2027-04-01T00:00:00Z', venue: 'Test', outcome: 'washout' }] }
}

test('browser projection conserves points and never mutates a stored table', () => {
  const data = snapshot(), before = structuredClone(data)
  const rows = projectedTable(data, { ab: 'home', cd: 'washout' })
  assert.equal(rows.reduce((sum, r) => sum + r.points, 0), 6)
  assert.equal(rows.find((r) => r.id === 'a')!.points, 3)
  assert.equal(rows.find((r) => r.id === 'd')!.points, 1)
  assert.ok(rows.every((r) => r.remaining === 0))
  assert.deepEqual(data, before)
})
test('completed or foreign picks do not affect the browser table', () => {
  const data = snapshot()
  assert.deepEqual(projectedTable(data, { ac: 'home', foreign: 'away' }), projectedTable(data, {}))
})
test('fixture IDs matching object prototype names do not create implicit picks', () => {
  const data = snapshot()
  data.fixtures[0].id = 'constructor'
  assert.deepEqual(projectedTable(data, {}), projectedTable(snapshot(), {}))
})
test('a new database result prunes only invalid saved picks', () => {
  const data = snapshot()
  data.fixtures[0].outcome = 'away'
  assert.deepEqual(validPicks(data, { ab: 'home', cd: 'away', foreign: 'home' }), { cd: 'away' })
})
test('priority order is respected for wins and NRR', () => {
  const data = snapshot()
  for (const row of data.standings) { row.points = 2; row.won = row.id === 'd' ? 1 : 0 }
  data.rules.tie_breakers = ['wins', 'nrr']
  assert.equal(projectedTable(data, {})[0].id, 'd')
  data.rules.tie_breakers = ['nrr', 'wins']
  assert.equal(projectedTable(data, {})[0].id, 'a')
})
test('prediction identities include revision, picks and every model input', () => {
  const a = predictionKey('stage', 1, { ab: 'home', cd: 'away' }, 'equal', 0.03, 1000)
  assert.equal(a, predictionKey('stage', 1, { cd: 'away', ab: 'home' }, 'equal', 0.03, 1000))
  for (const b of [predictionKey('other', 1, {}, 'equal', 0.03, 1000), predictionKey('stage', 2, { ab: 'home', cd: 'away' }, 'equal', 0.03, 1000), predictionKey('stage', 1, { ab: 'home', cd: 'away' }, 'rating', 0.03, 1000), predictionKey('stage', 1, { ab: 'home', cd: 'away' }, 'equal', 0.2, 1000)]) assert.notEqual(a, b)
})
test('versioned shared scenarios round trip and reject malformed input', () => {
  const value: Scenario = { version: 1, stageId: 'stage-1', revision: 1, model: 'equal', washoutProbability: 0.03, overrides: { ab: 'home' } }
  assert.deepEqual(parseScenario(JSON.stringify(value)), value)
  for (const invalid of ['null', '[]', '{', JSON.stringify({ ...value, version: 2 }), JSON.stringify({ ...value, overrides: { ab: 'draw' } }), JSON.stringify({ ...value, stageId: '../other' }), JSON.stringify({ ...value, revision: -1 }), JSON.stringify({ ...value, washoutProbability: 2 }), JSON.stringify({ ...value, overrides: Object.fromEntries(Array.from({ length: 201 }, (_, i) => [`f${i}`, 'home'])) })]) assert.equal(parseScenario(invalid), null)
})
test('fixture filtering separates stored results and remaining matches', () => {
  const data = snapshot()
  assert.deepEqual(filterFixtures(data.fixtures, 'a', 'remaining').map((m) => m.id), ['ab'])
  assert.deepEqual(filterFixtures(data.fixtures, '', 'results').map((m) => m.id), ['ac'])
  assert.equal(filterFixtures(data.fixtures, '', 'all').length, 3)
})
test('CSV escapes quotes and spreadsheet formulas without changing numeric NRR', () => {
  const rows = projectedTable(snapshot(), {})
  rows[0].name = '=SUM(1,2) "Team"'; rows[0].nrr = -0.5
  const csv = tableCSV(rows, [])
  assert.ok(csv.includes('"\'=SUM(1,2) ""Team"""'))
  assert.ok(csv.includes('"-0.5"'))
  assert.ok(csv.includes('"pending"'))
})

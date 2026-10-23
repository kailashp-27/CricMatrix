"""Season/stage configuration. No official season regulations are implied."""
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select, update

from .models import Entry, Fixture, Season, Stage, StageRule
from .schemas import Rules


RULE_FIELDS = tuple(Rules.model_fields)
TEMPLATES = [
    {'id': 'ipl-example', 'label': 'IPL-style league example', 'rules': Rules(team_count=10, matches_per_team=14, qualifying_spots=4).model_dump()},
    {'id': 'bbl-example', 'label': 'BBL-style league example', 'rules': Rules(team_count=8, matches_per_team=10, qualifying_spots=4).model_dump()},
    {'id': 'psl-example', 'label': 'PSL-style league example', 'rules': Rules(team_count=6, matches_per_team=10, qualifying_spots=4).model_dump()},
    {'id': 'world-cup-group-example', 'label': 'Four-team World Cup group example', 'rules': Rules(team_count=4, matches_per_team=3, qualifying_spots=2, stage_format='group').model_dump()},
]


def rule_record(stage_id, rules):
    if rules.team_count is None:
        raise ValueError('Persisted rules require team_count')
    return StageRule(stage_id=stage_id, **rules.model_dump())


def get_rules(session, stage):
    record = session.get(StageRule, stage.id)
    if record is None:
        raise ValueError('Stage rules have not been initialized; run the configuration backfill or migrations')
    if record.schema_version != 1:
        raise ValueError('Unsupported stage rules schema version')
    return Rules.model_validate({name: getattr(record, name) for name in RULE_FIELDS})


def validate_schedule(rules, team_ids, fixtures):
    ids = set(team_ids)
    if rules.team_count != len(ids) or len(team_ids) != len(ids):
        raise ValueError('Unique stage memberships must match the configured team count')
    counts = Counter({team_id: 0 for team_id in ids})
    seen = set()
    for match in fixtures:
        if match['id'] in seen:
            raise ValueError('Fixture IDs must be unique')
        seen.add(match['id'])
        home, away = match['home_id'], match['away_id']
        if home == away or home not in ids or away not in ids:
            raise ValueError('Fixture opponents must be distinct members of this stage')
        counts[home] += 1
        counts[away] += 1
    if rules.matches_per_team is not None:
        if any(n > rules.matches_per_team for n in counts.values()):
            raise ValueError('Fixture schedule exceeds configured matches per team')
        if rules.schedule_complete and any(n != rules.matches_per_team for n in counts.values()):
            raise ValueError('Complete schedule must contain every configured match for every team')
    elif rules.schedule_complete and any(n == 0 for n in counts.values()):
        raise ValueError('Every team must have fixtures in a complete schedule')


def backfill_rules(session):
    """Upgrade legacy demo rows without changing any results or existing rules."""
    count = 0
    for stage in session.scalars(select(Stage)):
        if session.get(StageRule, stage.id) is not None:
            continue
        ids = list(session.scalars(select(Entry.team_id).where(Entry.stage_id == stage.id)))
        fixtures = list(session.scalars(select(Fixture).where(Fixture.stage_id == stage.id)))
        appearances = Counter({team_id: 0 for team_id in ids})
        for match in fixtures:
            appearances[match.home_id] += 1
            appearances[match.away_id] += 1
        uniform = set(appearances.values())
        season = session.get(Season, stage.season_id)
        values = {**stage.rules, 'team_count': len(ids), 'matches_per_team': next(iter(uniform)) if len(uniform) == 1 and 0 not in uniform else None,
                  'stage_format': 'group' if stage.name.lower().startswith('group') else 'league',
                  'schedule_complete': stage.rules.get('schedule_complete', season.source == 'demo' and bool(fixtures) and all(appearances.values()))}
        rules = Rules.model_validate(values)
        validate_schedule(rules, ids, [{'id': m.id, 'home_id': m.home_id, 'away_id': m.away_id} for m in fixtures])
        session.add(rule_record(stage.id, rules))
        count += 1
    session.flush()
    return count


def update_rules(session, stage_id, rules, expected_revision):
    stage = session.get(Stage, stage_id)
    if stage is None:
        raise KeyError(stage_id)
    if stage.revision != expected_revision:
        raise ValueError('Stage revision changed; reload before updating rules')
    ids = list(session.scalars(select(Entry.team_id).where(Entry.stage_id == stage_id)))
    fixtures = [{'id': m.id, 'home_id': m.home_id, 'away_id': m.away_id} for m in session.scalars(select(Fixture).where(Fixture.stage_id == stage_id))]
    validate_schedule(rules, ids, fixtures)
    current = get_rules(session, stage)
    if current == rules:
        return stage.revision, False
    claim = session.execute(update(Stage).where(Stage.id == stage_id, Stage.revision == expected_revision).values(
        revision=expected_revision + 1, updated_at=datetime.now(timezone.utc).isoformat(), rules=rules.model_dump()))
    if claim.rowcount != 1:
        raise ValueError('Concurrent update changed this stage')
    record = session.get(StageRule, stage_id)
    for field, value in rules.model_dump().items():
        setattr(record, field, value)
    session.flush()
    return expected_revision + 1, True

"""Validate and provision new tournaments/seasons without public write access."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from .models import Entry, Fixture, Season, Stage, Team, Tournament
from .rules import get_rules, rule_record, validate_schedule
from .schemas import Rules


Identifier = Annotated[str, Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', min_length=1, max_length=80)]
Name = Annotated[str, Field(min_length=1, max_length=160)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class TournamentConfig(StrictModel):
    id: Identifier
    name: Name
    country: Name


class TeamConfig(StrictModel):
    id: Identifier
    name: Name
    short_name: Annotated[str, Field(min_length=1, max_length=8)]
    color: Annotated[str, Field(pattern=r'^#[0-9a-fA-F]{6}$')]


class EntryConfig(StrictModel):
    team_id: Identifier
    nrr: float = 0
    rating: float = Field(default=1500, ge=0, le=4000)


class FixtureConfig(StrictModel):
    id: Identifier
    home_id: Identifier
    away_id: Identifier
    starts_at: datetime
    venue: Name
    outcome: Literal['pending', 'home', 'away', 'washout'] = 'pending'

    @model_validator(mode='after')
    def aware_time(self):
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() is None:
            raise ValueError('Fixture start time must include a timezone')
        return self


class StageConfig(StrictModel):
    id: Identifier
    name: Name
    rules: Rules
    entries: list[EntryConfig] = Field(min_length=2, max_length=16)
    fixtures: list[FixtureConfig] = Field(default_factory=list, max_length=800)

    @model_validator(mode='after')
    def valid_schedule(self):
        validate_schedule(self.rules, [e.team_id for e in self.entries], [f.model_dump() for f in self.fixtures])
        return self


class SeasonConfig(StrictModel):
    schema_version: Literal[1] = 1
    tournament: TournamentConfig
    id: Identifier
    name: Name
    source: Literal['demo', 'manual'] = 'manual'
    teams: list[TeamConfig] = Field(min_length=2, max_length=64)
    stages: list[StageConfig] = Field(min_length=1, max_length=32)

    @model_validator(mode='after')
    def references_and_unique_ids(self):
        team_ids = [t.id for t in self.teams]
        stage_ids = [s.id for s in self.stages]
        fixture_ids = [f.id for s in self.stages for f in s.fixtures]
        for values in (team_ids, stage_ids, fixture_ids):
            if len(values) != len(set(values)):
                raise ValueError('Team, stage and fixture IDs must each be unique')
        referenced = {entry.team_id for stage in self.stages for entry in stage.entries}
        if referenced != set(team_ids):
            raise ValueError('Every configured team must be referenced by a stage and every stage team must be declared')
        return self


def fixture_fields(fixture):
    return {**fixture.model_dump(exclude={'starts_at'}), 'starts_at': fixture.starts_at.astimezone(timezone.utc).isoformat()}


def provision_season(session, config):
    """Create atomically; repeat identical configuration without resetting results.

    Commit belongs to the caller. Existing seasons cannot be overwritten by
    provisioning; rule changes have a dedicated optimistic-revision operation.
    """
    tournament = session.get(Tournament, config.tournament.id)
    if tournament and (tournament.name, tournament.country) != (config.tournament.name, config.tournament.country):
        raise ValueError('Tournament ID already belongs to different metadata')
    for team in config.teams:
        existing = session.get(Team, team.id)
        if existing and any(getattr(existing, field) != value for field, value in team.model_dump().items()):
            raise ValueError(f'Team ID has conflicting metadata: {team.id}')
    season = session.get(Season, config.id)
    if season:
        if (season.tournament_id, season.name, season.source) != (config.tournament.id, config.name, config.source):
            raise ValueError('Existing season has conflicting metadata')
        existing_stages = list(session.scalars(select(Stage).where(Stage.season_id == config.id)))
        if {s.id for s in existing_stages} != {s.id for s in config.stages}:
            raise ValueError('Existing season has a different stage set')
        for definition in config.stages:
            stage = session.get(Stage, definition.id)
            members = set(session.scalars(select(Entry.team_id).where(Entry.stage_id == stage.id)))
            matches = list(session.scalars(select(Fixture).where(Fixture.stage_id == stage.id)))
            expected = {f.id: fixture_fields(f) for f in definition.fixtures}
            if stage.name != definition.name or get_rules(session, stage) != definition.rules or members != {e.team_id for e in definition.entries}:
                raise ValueError('Existing stage configuration differs; use revision-safe rule updates')
            if {m.id for m in matches} != expected.keys() or any(any(getattr(m, field) != value for field, value in expected[m.id].items() if field != 'outcome') for m in matches):
                raise ValueError('Existing fixture schedule differs')
        return False
    for stage in config.stages:
        if session.get(Stage, stage.id):
            raise ValueError(f'Stage ID is already in use: {stage.id}')
        for fixture in stage.fixtures:
            if session.get(Fixture, fixture.id):
                raise ValueError(f'Fixture ID is already in use: {fixture.id}')
    if tournament is None:
        session.add(Tournament(**config.tournament.model_dump()))
        session.flush()
    for team in config.teams:
        if session.get(Team, team.id) is None:
            session.add(Team(**team.model_dump()))
    session.add(Season(id=config.id, tournament_id=config.tournament.id, name=config.name, source=config.source))
    session.flush()
    for definition in config.stages:
        session.add(Stage(id=definition.id, season_id=config.id, name=definition.name, rules=definition.rules.model_dump(), updated_at=datetime.now(timezone.utc).isoformat()))
        session.flush()
        session.add(rule_record(definition.id, definition.rules))
        for entry in definition.entries:
            session.add(Entry(stage_id=definition.id, **entry.model_dump()))
        session.flush()
        for fixture in definition.fixtures:
            session.add(Fixture(stage_id=definition.id, **fixture_fields(fixture)))
    session.flush()
    return True

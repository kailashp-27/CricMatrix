from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Tournament(Base):
    __tablename__ = 'tournaments'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str]
    country: Mapped[str]


class Season(Base):
    __tablename__ = 'seasons'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tournament_id: Mapped[str] = mapped_column(ForeignKey('tournaments.id'), index=True)
    name: Mapped[str]
    source: Mapped[str] = mapped_column(default='demo')


class Stage(Base):
    __tablename__ = 'stages'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    season_id: Mapped[str] = mapped_column(ForeignKey('seasons.id'), index=True)
    name: Mapped[str]
    rules: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[str]


class StageRule(Base):
    __tablename__ = 'stage_rules'
    __table_args__ = (
        CheckConstraint('team_count >= 2 AND team_count <= 16', name='ck_rule_team_count'),
        CheckConstraint('qualifying_spots >= 1 AND qualifying_spots <= team_count', name='ck_rule_spots'),
        CheckConstraint('matches_per_team IS NULL OR matches_per_team >= 1', name='ck_rule_matches'),
        CheckConstraint('win_points = 2 AND loss_points = 0 AND washout_points = 1', name='ck_rule_scoring'),
        CheckConstraint("stage_format IN ('league', 'group')", name='ck_rule_format'),
        CheckConstraint('regulation_overs >= 1 AND regulation_overs <= 100', name='ck_rule_overs'),
    )
    stage_id: Mapped[str] = mapped_column(ForeignKey('stages.id'), primary_key=True)
    schema_version: Mapped[int] = mapped_column(default=1)
    team_count: Mapped[int]
    matches_per_team: Mapped[int | None]
    qualifying_spots: Mapped[int]
    win_points: Mapped[int] = mapped_column(default=2)
    loss_points: Mapped[int] = mapped_column(default=0)
    washout_points: Mapped[int] = mapped_column(default=1)
    tie_breakers: Mapped[list[str]] = mapped_column(JSON)
    stage_format: Mapped[str] = mapped_column(default='league')
    regulation_overs: Mapped[int] = mapped_column(default=20)
    schedule_complete: Mapped[bool] = mapped_column(default=True)


class Team(Base):
    __tablename__ = 'teams'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str]
    short_name: Mapped[str]
    color: Mapped[str]


class Entry(Base):
    __tablename__ = 'stage_entries'
    __table_args__ = (UniqueConstraint('stage_id', 'team_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    stage_id: Mapped[str] = mapped_column(ForeignKey('stages.id'), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey('teams.id'))
    nrr: Mapped[float] = mapped_column(default=0)
    rating: Mapped[float] = mapped_column(default=1500)


class Fixture(Base):
    __tablename__ = 'fixtures'
    __table_args__ = (
        CheckConstraint('home_id <> away_id', name='ck_fixture_opponents'),
        CheckConstraint("outcome IN ('pending', 'home', 'away', 'washout')", name='ck_fixture_outcome'),
        ForeignKeyConstraint(['stage_id', 'home_id'], ['stage_entries.stage_id', 'stage_entries.team_id'], name='fk_fixture_home_entry'),
        ForeignKeyConstraint(['stage_id', 'away_id'], ['stage_entries.stage_id', 'stage_entries.team_id'], name='fk_fixture_away_entry'),
    )
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    stage_id: Mapped[str] = mapped_column(ForeignKey('stages.id'), index=True)
    home_id: Mapped[str] = mapped_column(ForeignKey('teams.id'))
    away_id: Mapped[str] = mapped_column(ForeignKey('teams.id'))
    starts_at: Mapped[str]
    venue: Mapped[str]
    # pending | home | away | washout. In-progress fixtures remain unresolved.
    outcome: Mapped[str] = mapped_column(default='pending')


class SyncSource(Base):
    __tablename__ = 'sync_sources'
    stage_id: Mapped[str] = mapped_column(ForeignKey('stages.id'), primary_key=True)
    provider: Mapped[str]
    configuration: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(default=False)
    interval_seconds: Mapped[int] = mapped_column(default=43200)
    next_attempt: Mapped[float] = mapped_column(default=0)
    lease_until: Mapped[float] = mapped_column(default=0)
    lease_token: Mapped[str | None]
    status: Mapped[str] = mapped_column(default='idle')
    error_code: Mapped[str | None]
    last_attempt_at: Mapped[str | None]
    last_success_at: Mapped[str | None]
    last_observed_at: Mapped[str | None]
    nrr_verified_revision: Mapped[int | None]


class SyncRun(Base):
    __tablename__ = 'sync_runs'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    stage_id: Mapped[str] = mapped_column(ForeignKey('stages.id'), index=True)
    started_at: Mapped[str]
    finished_at: Mapped[str | None]
    status: Mapped[str]
    changed: Mapped[bool] = mapped_column(default=False)
    error_code: Mapped[str | None]


class ProviderQuota(Base):
    __tablename__ = 'provider_quotas'
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    used: Mapped[int] = mapped_column(default=0)

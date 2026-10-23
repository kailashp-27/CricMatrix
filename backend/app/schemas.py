from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Outcome = Literal['home', 'away', 'washout']


class Rules(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qualifying_spots: int = Field(ge=1, le=16)
    win_points: Literal[2] = 2
    loss_points: Literal[0] = 0
    washout_points: Literal[1] = 1
    tie_breakers: list[Literal['wins', 'nrr']] = Field(default_factory=lambda: ['nrr'], min_length=1, max_length=2)
    team_count: int | None = Field(default=None, ge=2, le=16)
    matches_per_team: int | None = Field(default=None, ge=1, le=100)
    stage_format: Literal['league', 'group'] = 'league'
    regulation_overs: int = Field(default=20, ge=1, le=100)
    schedule_complete: bool = True

    @model_validator(mode='after')
    def coherent_rules(self):
        if len(set(self.tie_breakers)) != len(self.tie_breakers):
            raise ValueError('Tie-breakers must be unique and in priority order')
        if self.team_count is not None:
            if self.qualifying_spots > self.team_count:
                raise ValueError('Qualifying spots cannot exceed the stage team count')
            if self.matches_per_team is not None and self.team_count * self.matches_per_team % 2:
                raise ValueError('Team count × matches per team must be even')
        return self


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    overrides: dict[str, Outcome] = Field(default_factory=dict, max_length=200)
    iterations: int = Field(default=1000, ge=100, le=10000)
    model: Literal['equal', 'rating'] = 'equal'
    washout_probability: float = Field(default=0.03, ge=0, le=0.5)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)

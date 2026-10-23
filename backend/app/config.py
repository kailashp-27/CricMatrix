from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./crease.db'
    redis_url: str = 'redis://localhost:6379/0'
    job_mode: Literal['local', 'celery'] = 'local'
    cors_origins: str = 'http://localhost:5173,http://127.0.0.1:5173'
    demo_seed: bool = True
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    cricketdata_api_key: SecretStr = SecretStr('')
    provider_daily_budget: int = Field(default=0, ge=0, le=100000)
    cricketdata_base_url: str = 'https://api.cricapi.com/v1'
    live_feed_enabled: bool = True
    live_feed_provider: Literal['espn_rss', 'cricketdata'] = 'espn_rss'
    live_feed_url: str = 'https://static.espncricinfo.com/rss/livescores.xml'
    live_poll_seconds: int = Field(default=120, ge=60, le=86400)
    live_max_pages: int = Field(default=4, ge=1, le=20)

    @model_validator(mode='after')
    def validate_runtime(self):
        if self.database_url.startswith('postgresql://'):
            self.database_url = self.database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
        if self.job_mode == 'celery' and not self.database_url.startswith(('postgresql://', 'postgresql+psycopg://')):
            raise ValueError('Celery deployment mode requires PostgreSQL; use JOB_MODE=local for SQLite development')
        if self.job_mode == 'celery' and not self.redis_url.startswith(('redis://', 'rediss://')):
            raise ValueError('Celery deployment mode requires a Redis broker URL')
        self.cors_origins = ','.join(origin.strip() for origin in self.cors_origins.split(',') if origin.strip())
        return self


settings = Settings()

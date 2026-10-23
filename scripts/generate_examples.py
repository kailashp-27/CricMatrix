"""Regenerate synthetic season configuration examples and their JSON Schema."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.configuration import SeasonConfig
from app.schemas import Rules
from app.seed import LEAGUES, demo_schedule

destination = ROOT / 'examples'
destination.mkdir(exist_ok=True)
for code, name, country, spots, members in LEAGUES:
    season_id = f'{code}-phase2-example'
    teams = [{'id': f'{code}-{short}', 'name': full, 'short_name': short, 'color': color} for short, full, color in members]
    groups = [teams] if code != 'wc' else [teams[:4], teams[4:]]
    stages = []
    for i, group in enumerate(groups):
        stage_id = f'{season_id}-{i}'
        matches_per_team = {'ipl': 14, 'bbl': 10, 'psl': 10, 'wc': 3}[code]
        rules = Rules(team_count=len(group), matches_per_team=matches_per_team, qualifying_spots=spots, stage_format='group' if code == 'wc' else 'league')
        matches = demo_schedule([t['id'] for t in group], matches_per_team)
        stages.append({'id': stage_id, 'name': f'Group {chr(65 + i)}' if code == 'wc' else 'League stage', 'rules': rules.model_dump(),
                       'entries': [{'team_id': t['id']} for t in group],
                       'fixtures': [{'id': f'{stage_id}-m{j + 1}', 'home_id': home, 'away_id': away, 'starts_at': (datetime(2027, 4, 1, 14, tzinfo=timezone.utc) + timedelta(days=j)).isoformat(), 'venue': 'Synthetic Example Ground', 'outcome': 'pending'} for j, (home, away) in enumerate(matches)]})
    config = SeasonConfig.model_validate({'tournament': {'id': code, 'name': name, 'country': country}, 'id': season_id, 'name': 'Phase 2 example season', 'source': 'demo', 'teams': teams, 'stages': stages})
    (destination / f'{code}-season.json').write_text(config.model_dump_json(indent=2), encoding='utf-8')
(destination / 'season-config.schema.json').write_text(json.dumps(SeasonConfig.model_json_schema(), indent=2), encoding='utf-8')
print('Wrote four validated demo season configurations and their JSON Schema.')

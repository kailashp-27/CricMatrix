"""Synthetic, reproducible demo seasons. These are not official fixtures or rules."""
from datetime import datetime, timedelta, timezone
from random import Random

from sqlalchemy import select

from .models import Entry, Fixture, Season, Stage, Team, Tournament
from .rules import backfill_rules


LEAGUES = [
    ('ipl', 'Indian Premier League', 'India', 4, [
        ('CSK', 'Chennai Super Kings', '#f7ce45'), ('MI', 'Mumbai Indians', '#5297ff'),
        ('RCB', 'Royal Challengers Bengaluru', '#fa6574'), ('KKR', 'Kolkata Knight Riders', '#b799ff'),
        ('SRH', 'Sunrisers Hyderabad', '#ff9a50'), ('RR', 'Rajasthan Royals', '#ef8cce'),
        ('DC', 'Delhi Capitals', '#5ecae8'), ('PBKS', 'Punjab Kings', '#e88c8c'),
        ('GT', 'Gujarat Titans', '#91b7c8'), ('LSG', 'Lucknow Super Giants', '#96d3a5')]),
    ('bbl', 'Big Bash League', 'Australia', 4, [
        ('SIX', 'Sydney Sixers', '#f882bc'), ('SCO', 'Perth Scorchers', '#ff9a50'),
        ('HEA', 'Brisbane Heat', '#63d2c8'), ('STA', 'Melbourne Stars', '#86cb80'),
        ('THU', 'Sydney Thunder', '#cef15b'), ('REN', 'Melbourne Renegades', '#fa6574'),
        ('HUR', 'Hobart Hurricanes', '#b799ff'), ('STR', 'Adelaide Strikers', '#5297ff')]),
    ('psl', 'Pakistan Super League', 'Pakistan', 4, [
        ('ISU', 'Islamabad United', '#fa6574'), ('MS', 'Multan Sultans', '#63d2c8'),
        ('LQ', 'Lahore Qalandars', '#cef15b'), ('PZ', 'Peshawar Zalmi', '#f7ce45'),
        ('QG', 'Quetta Gladiators', '#b799ff'), ('KK', 'Karachi Kings', '#5297ff')]),
    ('wc', 'T20 World Cup', 'International', 2, [
        ('IND', 'India', '#5297ff'), ('AUS', 'Australia', '#f7ce45'),
        ('ENG', 'England', '#fa6574'), ('SA', 'South Africa', '#86cb80'),
        ('NZ', 'New Zealand', '#b4bac9'), ('PAK', 'Pakistan', '#63d2c8'),
        ('WI', 'West Indies', '#b799ff'), ('SL', 'Sri Lanka', '#ff9a50')]),
]


def demo_schedule(team_ids, matches_per_team):
    """Even-team circle schedule; repeat rounds to reach the configured count."""
    wheel = list(team_ids)
    rounds = []
    for _ in range(len(wheel) - 1):
        rounds.append([(wheel[i], wheel[-1 - i]) for i in range(len(wheel) // 2)])
        wheel = [wheel[0], wheel[-1], *wheel[1:-1]]
    return [pair for i in range(matches_per_team) for pair in rounds[i % len(rounds)]]


def seed_demo(session):
    if session.scalar(select(Tournament.id).limit(1)):
        backfill_rules(session)
        session.commit()
        return
    rng = Random(73)
    for code, name, country, spots, team_data in LEAGUES:
        session.add(Tournament(id=code, name=name, country=country))
        session.flush()
        season_id = f'{code}-demo'
        session.add(Season(id=season_id, tournament_id=code, name='Demo season', source='demo'))
        session.flush()
        for short, full, color in team_data:
            session.add(Team(id=f'{code}-{short}', name=full, short_name=short, color=color))
        session.flush()
        groups = [team_data] if code != 'wc' else [team_data[:4], team_data[4:]]
        for gi, members in enumerate(groups):
            stage_id = f'{season_id}-{gi}'
            session.add(Stage(id=stage_id, season_id=season_id, name='League stage' if code != 'wc' else f'Group {chr(65 + gi)}',
                              rules={'qualifying_spots': spots, 'win_points': 2, 'loss_points': 0, 'washout_points': 1, 'tie_breakers': ['nrr']},
                              updated_at=datetime.now(timezone.utc).isoformat()))
            session.flush()
            for i, (short, _, _) in enumerate(members):
                session.add(Entry(stage_id=stage_id, team_id=f'{code}-{short}', nrr=round(rng.uniform(-0.9, 1.1), 3), rating=1620 - i * 27))
            session.flush()
            matches_per_team = {'ipl': 14, 'bbl': 10, 'psl': 10, 'wc': 3}[code]
            pairs = demo_schedule([f'{code}-{t[0]}' for t in members], matches_per_team)
            rng.shuffle(pairs)
            # Synthetic schedule matching example counts, not official fixtures.
            completed = int(len(pairs) * (0.68 if code != 'wc' else 0.5))
            for i, (home, away) in enumerate(pairs):
                outcome = rng.choices(['home', 'away', 'washout'], [0.53, 0.44, 0.03])[0] if i < completed else 'pending'
                session.add(Fixture(id=f'{stage_id}-m{i + 1}', stage_id=stage_id, home_id=home, away_id=away,
                                    starts_at=(datetime(2027, 4, 1, 14, tzinfo=timezone.utc) + timedelta(days=i)).isoformat(),
                                    venue='Demo Cricket Ground', outcome=outcome))
    session.flush()
    backfill_rules(session)
    session.commit()

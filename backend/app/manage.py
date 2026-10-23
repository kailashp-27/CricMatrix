"""Operator commands. Configuration writes are never public API operations."""
import argparse
import json
from pathlib import Path

from .configuration import SeasonConfig, provision_season
from .database import Base, SessionLocal, engine
from .rules import backfill_rules, update_rules
from .schemas import Rules


def main():
    parser = argparse.ArgumentParser(description='Manage Crease configuration')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init-demo', help='Create local demo tables and backfill legacy rules')
    commands.add_parser('backfill-rules', help='Populate missing dedicated rule records without changing results')
    for command in ('validate-config', 'apply-config'):
        sub = commands.add_parser(command)
        sub.add_argument('file', type=Path)
    sub = commands.add_parser('set-rules')
    sub.add_argument('stage_id')
    sub.add_argument('file', type=Path)
    sub.add_argument('--expected-revision', type=int, required=True)
    commands.add_parser('export-schema', help='Print the season configuration JSON Schema')
    args = parser.parse_args()
    try:
        if args.command == 'export-schema':
            print(json.dumps(SeasonConfig.model_json_schema(), indent=2))
            return
        if args.command == 'init-demo':
            from .seed import seed_demo
            Base.metadata.create_all(engine)
            with SessionLocal() as session:
                seed_demo(session)
            print(json.dumps({'status': 'initialized', 'database': engine.dialect.name}))
            return
        if args.command == 'backfill-rules':
            with SessionLocal.begin() as session:
                count = backfill_rules(session)
            print(json.dumps({'created_rule_records': count}))
            return
        data = args.file.read_text(encoding='utf-8')
        if args.command in ('validate-config', 'apply-config'):
            config = SeasonConfig.model_validate_json(data)
            created = False
            if args.command == 'apply-config':
                with SessionLocal.begin() as session:
                    created = provision_season(session, config)
            print(json.dumps({'valid': True, 'season_id': config.id, 'stages': len(config.stages), 'created': created}))
        elif args.command == 'set-rules':
            rules = Rules.model_validate_json(data)
            with SessionLocal.begin() as session:
                revision, changed = update_rules(session, args.stage_id, rules, args.expected_revision)
            print(json.dumps({'stage_id': args.stage_id, 'revision': revision, 'changed': changed}))
    except (ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()

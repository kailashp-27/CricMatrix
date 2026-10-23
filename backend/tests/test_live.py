"""Exercise the production HTTP client against local provider contract fixtures."""
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.live import parse_matches, parse_rss, read_feed, refresh_feed, refresh_series, refresh_match_series
from app.models import LiveFeed, ProviderQuota
from app.sync import SourceConfig, SyncFailure, fetch_cricketdata
from app.provider_tables import parse_points, refresh_tables, read_tables, table_key


def rss(published=None, title='Team A 123/4 * v Team B'):
    published = published or format_datetime(datetime.now(timezone.utc))
    return f'''<rss><channel><pubDate>{published}</pubDate><item><title>{title}</title>
    <link>http://www.cricinfo.com/ci/engine/match/123.html?CMP=OTC-RSS</link></item></channel></rss>'''.encode()


class LiveTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'artifacts'
        root.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=root, ignore_cleanup_errors=True)
        self.engine = create_engine('sqlite:///' + (Path(self.directory.name) / 'live.db').as_posix())
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        self.responses = {}; self.calls = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import urlparse, parse_qs
                url = urlparse(self.path); params = parse_qs(url.query)
                owner.calls.append((url.path, params))
                response = owner.responses.get((url.path, params.get('offset', ['0'])[0]), (501, b'Unmodeled request'))
                self.send_response(response[0]); self.end_headers(); self.wfile.write(response[1])

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.config = patch.multiple(settings, live_feed_enabled=True, live_feed_provider='espn_rss',
            live_feed_url=self.base + '/rss', cricketdata_base_url=self.base,
            cricketdata_api_key=type(settings.cricketdata_api_key)('test-private-key'),
            provider_daily_budget=20, live_poll_seconds=120, live_max_pages=4)
        self.config.start()

    def tearDown(self):
        self.config.stop(); self.server.shutdown(); self.server.server_close()
        self.thread.join(); self.engine.dispose(); self.directory.cleanup()

    def due(self):
        with self.factory.begin() as session:
            for feed in session.scalars(select(LiveFeed)):
                feed.next_attempt = 0

    def test_rss_http_fetch_cache_and_reads_do_not_fetch(self):
        self.responses[('/rss', '0')] = (200, rss())
        self.assertEqual(refresh_feed(self.factory)['matches'], 1)
        self.assertEqual(refresh_feed(self.factory)['status'], 'not_due_or_running')
        with self.factory() as session:
            feed = read_feed(session)
            self.assertFalse(feed['stale']); self.assertEqual(feed['matches'][0]['state'], 'unknown')
            self.assertTrue(feed['matches'][0]['url'].startswith('https://www.espncricinfo.com/'))
            self.assertFalse(feed['qualification_ready'])
        self.assertEqual(len(self.calls), 1)

    def test_old_publisher_timestamp_never_masquerades_as_live(self):
        self.responses[('/rss', '0')] = (200, rss('Mon, 01 Jan 2024 00:00:00 +0000'))
        refresh_feed(self.factory)
        with self.factory() as session:
            self.assertTrue(read_feed(session)['stale'])

    def test_http_failure_and_malformed_xml_preserve_last_good_snapshot(self):
        self.responses[('/rss', '0')] = (200, rss()); refresh_feed(self.factory)
        for response in ((500, b'<html>Failure test-private-key</html>'), (200, b'invalid xml')):
            self.due(); self.responses[('/rss', '0')] = response
            self.assertEqual(refresh_feed(self.factory)['status'], 'failed')
            with self.factory() as session:
                result = read_feed(session)
                self.assertEqual(len(result['matches']), 1); self.assertTrue(result['stale'])
                self.assertNotIn('test-private-key', json.dumps(result))

    def test_regressed_snapshot_is_rejected_and_lease_prevents_duplicate(self):
        self.responses[('/rss', '0')] = (200, rss()); refresh_feed(self.factory)
        self.due(); self.responses[('/rss', '0')] = (200, rss('Mon, 01 Jan 2024 00:00:00 +0000'))
        self.assertEqual(refresh_feed(self.factory)['error'], 'stale_provider_payload')
        with self.factory.begin() as session:
            feed = session.get(LiveFeed, 'espn_rss'); feed.next_attempt = 0; feed.lease_until = time.time() + 120
        count = len(self.calls)
        self.assertEqual(refresh_feed(self.factory)['status'], 'not_due_or_running')
        self.assertEqual(len(self.calls), count)

    def test_reject_xml_entities_and_untrusted_links(self):
        for content in (b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>', rss().replace(b'www.cricinfo.com', b'evil.example')):
            with self.assertRaises(SyncFailure): parse_rss(content)

    def row(self):
        return {'id': str(uuid4()), 'series_id': str(uuid4()), 'name': 'A vs B', 'teams': ['A', 'B'],
                'dateTimeGMT': '2026-10-23T10:00:00', 'status': 'A batting', 'matchStarted': True,
                'matchEnded': False, 'matchType': 'test', 'score': [{'inning': 'A Inning 1', 'r': 210, 'w': 5, 'o': 62.1}]}

    def json_response(self, rows, total):
        return (200, json.dumps({'apikey': 'test-private-key', 'status': 'success', 'data': rows, 'info': {'totalRows': total}}).encode())

    def test_cricketdata_real_http_pagination_quota_and_multi_format_scores(self):
        settings.live_feed_provider = 'cricketdata'
        rows = [self.row(), self.row()]; rows[1]['matchType'] = 'odi'
        self.responses[('/currentMatches', '0')] = self.json_response(rows[:1], 2)
        self.responses[('/currentMatches', '1')] = self.json_response(rows[1:], 2)
        self.assertEqual(refresh_feed(self.factory)['matches'], 2)
        with self.factory() as session:
            result = read_feed(session)
            self.assertEqual([m['format'] for m in result['matches']], ['test', 'odi'])
            self.assertEqual(result['matches'][0]['state'], 'live')
            self.assertIn('62.1 ov', result['matches'][0]['scores'][0])
            self.assertNotIn('test-private-key', json.dumps(result))
            self.assertEqual(session.scalars(select(ProviderQuota)).one().used, 2)
        self.assertEqual([c[1]['offset'][0] for c in self.calls], ['0', '1'])

    def test_page_cap_is_explicit_and_exhausted_budget_prevents_request(self):
        settings.live_feed_provider = 'cricketdata'; settings.live_max_pages = 1
        self.responses[('/currentMatches', '0')] = self.json_response([self.row()], 100)
        refresh_feed(self.factory)
        with self.factory() as session: self.assertTrue(read_feed(session)['truncated'])
        self.due(); settings.provider_daily_budget = 1
        self.assertEqual(refresh_feed(self.factory)['error'], 'daily_budget_exhausted')
        self.assertEqual(len(self.calls), 1)

    def test_rate_limit_and_credentials_missing_are_sanitized(self):
        settings.live_feed_provider = 'cricketdata'
        self.responses[('/currentMatches', '0')] = (429, b'test-private-key')
        self.assertEqual(refresh_feed(self.factory)['error'], 'provider_rate_limited')
        self.due(); settings.cricketdata_api_key = type(settings.cricketdata_api_key)('')
        self.assertEqual(refresh_feed(self.factory)['error'], 'provider_credentials_or_budget_missing')
        self.assertEqual(len(self.calls), 1)

    def test_absent_flags_are_unknown_and_invalid_identity_rejected(self):
        row = self.row(); del row['matchStarted']; del row['matchEnded']
        self.assertEqual(parse_matches([row])[0]['state'], 'unknown')
        row['id'] = 'not-a-uuid'
        with self.assertRaises(SyncFailure): parse_matches([row])

    def table_row(self):
        return {'teamname': 'Nigeria', 'shortname': 'NGA', 'matches': 3, 'wins': 3, 'loss': 0, 'ties': 0, 'nr': 0}

    def test_fetched_table_preserves_provider_counters_without_inventing_points_or_nrr(self):
        settings.live_feed_provider = 'cricketdata'
        self.responses[('/currentMatches', '0')] = self.json_response([self.row()], 1)
        self.responses[('/series_points', '0')] = self.json_response([self.table_row()], 1)
        refresh_feed(self.factory); refresh_tables(self.factory); refresh_tables(self.factory)
        with self.factory() as session:
            table = read_tables(session)['competitions'][0]
            self.assertEqual(table['rows'][0]['won'], 3)
            self.assertEqual(table['rows'][0]['played'], 3)
            self.assertIsNone(table['rows'][0]['points']); self.assertIsNone(table['rows'][0]['nrr'])
            self.assertFalse(table['points_available']); self.assertFalse(table['nrr_available'])
            self.assertFalse(read_tables(session)['qualification_available'])
            series_id = table['id']
        with self.factory.begin() as session:
            from app.live import series_cache_key
            session.add(LiveFeed(provider=series_cache_key(series_id), payload={'team_names': ['Nigeria', 'Mozambique']}))
        with self.factory() as session:
            self.assertEqual(read_tables(session)['competitions'][0]['missing_teams'], ['Mozambique'])
        self.assertEqual([c[0] for c in self.calls], ['/currentMatches', '/series_points'])

    def test_empty_provider_table_never_falls_back_to_seeded_standings(self):
        from app.seed import seed_demo
        settings.live_feed_provider = 'cricketdata'
        with self.factory() as session: seed_demo(session)
        self.responses[('/currentMatches', '0')] = self.json_response([self.row()], 1)
        self.responses[('/series_points', '0')] = self.json_response([], 0)
        refresh_feed(self.factory); refresh_tables(self.factory)
        with self.factory() as session:
            result = read_tables(session)
            self.assertEqual(len(result['competitions']), 1)
            self.assertEqual(result['competitions'][0]['rows'], [])
            self.assertEqual(result['competitions'][0]['status'], 'unavailable')
            self.assertNotIn('RCB', json.dumps(result))

    def test_table_failure_preserves_last_provider_table_and_marks_stale(self):
        settings.live_feed_provider = 'cricketdata'
        self.responses[('/currentMatches', '0')] = self.json_response([self.row()], 1)
        self.responses[('/series_points', '0')] = self.json_response([self.table_row()], 1)
        refresh_feed(self.factory); refresh_tables(self.factory); self.due()
        self.responses[('/series_points', '0')] = (500, b'test-private-key')
        refresh_tables(self.factory)
        with self.factory() as session:
            result = read_tables(session)
            self.assertEqual(result['competitions'][0]['rows'][0]['name'], 'Nigeria')
            self.assertTrue(result['competitions'][0]['stale'])
            self.assertEqual(result['competitions'][0]['status'], 'failed')
            self.assertNotIn('test-private-key', json.dumps(result))

    def test_table_validation_keeps_optional_metrics_and_rejects_bad_totals(self):
        row = self.table_row(); row.update(points=6, nrr=1.234)
        parsed = parse_points([row])[0]
        self.assertEqual(parsed['points'], 6); self.assertEqual(parsed['nrr'], 1.234)
        for invalid in ([row, row], [{**row, 'wins': 4}], [{**row, 'nrr': float('nan')}], [{**row, 'matches': -1}]):
            with self.assertRaises(SyncFailure): parse_points(invalid)

    def test_series_discovery_resolves_competition_names_and_caches_daily(self):
        settings.live_feed_provider = 'cricketdata'
        row = self.row()
        self.responses[('/currentMatches', '0')] = self.json_response([row], 1)
        self.responses[('/series', '0')] = self.json_response([{'id': row['series_id'], 'name': 'International Women Championship'}], 1)
        refresh_feed(self.factory); self.assertEqual(refresh_series(self.factory)['series'], 1)
        self.assertEqual(refresh_series(self.factory)['status'], 'not_due_or_running')
        with self.factory() as session:
            result = read_feed(session)
            self.assertEqual(result['matches'][0]['series_name'], 'International Women Championship')
            self.assertEqual(len(result['series']), 1)
        self.assertEqual([c[0] for c in self.calls], ['/currentMatches', '/series'])

    def test_repeated_provider_page_is_rejected_instead_of_claiming_full_coverage(self):
        settings.live_feed_provider = 'cricketdata'
        row = self.row()
        self.responses[('/currentMatches', '0')] = self.json_response([row], 3)
        self.responses[('/currentMatches', '1')] = self.json_response([row], 3)
        self.assertEqual(refresh_feed(self.factory)['error'], 'provider_pagination_repeated')
        with self.factory() as session: self.assertEqual(read_feed(session)['matches'], [])

    def test_current_series_names_resolve_when_catalog_only_contains_future_tours(self):
        settings.live_feed_provider = 'cricketdata'
        row = self.row()
        self.responses[('/currentMatches', '0')] = self.json_response([row], 1)
        self.responses[('/series', '0')] = self.json_response([{'id': str(uuid4()), 'name': 'Future tour'}], 1)
        self.responses[('/series_info', '0')] = (200, json.dumps({'status': 'success', 'data': {
            'info': {'id': row['series_id'], 'name': 'Current qualifier', 'startdate': '2026-10-20'}, 'matchList': []}}).encode())
        refresh_feed(self.factory); refresh_series(self.factory)
        refresh_match_series(self.factory); refresh_match_series(self.factory)
        with self.factory() as session:
            feed = read_feed(session)
            self.assertEqual(feed['matches'][0]['series_name'], 'Current qualifier')
            self.assertIn('Future tour', [s['name'] for s in feed['series']])
        self.assertEqual([c[0] for c in self.calls].count('/series_info'), 1)

    def test_stage_result_sync_uses_generic_match_info_and_bounds_catch_up(self):
        series = uuid4(); ids = [uuid4() for _ in range(3)]
        config = SourceConfig(stage_id='real-group', provider='cricketdata', series_id=series,
            fixture_map={identity: f'm{i}' for i, identity in enumerate(ids)},
            team_names={'A': 'a', 'B': 'b'}, max_calls_per_run=2)
        fixtures = [{'id': f'm{i}', 'home_id': 'a', 'away_id': 'b', 'starts_at': '2020-01-01T00:00:00+00:00', 'outcome': 'pending'} for i in range(3)]
        # Each request targets a different match ID. Return the actual requested
        # identity in the fixture server, preserving the production identity check.
        class MatchHandler(BaseHTTPRequestHandler):
            def do_GET(inner):
                from urllib.parse import urlparse, parse_qs
                url = urlparse(inner.path); params = parse_qs(url.query)
                self.calls.append((url.path, params))
                inner.send_response(200); inner.end_headers()
                inner.wfile.write(json.dumps({'status': 'success', 'data': {'id': params['id'][0],
                    'series_id': str(series), 'teams': ['A', 'B'], 'matchWinner': 'B'}}).encode())

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), MatchHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with patch.object(settings, 'cricketdata_base_url', f'http://127.0.0.1:{server.server_port}'):
                result = fetch_cricketdata(config, fixtures, self.factory)
            self.assertEqual(result.outcomes, {'m0': 'away', 'm1': 'away'})
            self.assertEqual([call[0] for call in self.calls], ['/match_info', '/match_info'])
        finally:
            server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__':
    unittest.main()

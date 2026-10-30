import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import demand_probe as module
except ImportError:
    module = None


class DemandProbeTests(unittest.TestCase):
    def test_all_platforms_and_argument_vectors(self):
        self.assertIsNotNone(module, 'demand_probe.py is missing')
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"url": "https://example.com/" + argv[0], "title": "Demand", "commentsCount": 3}]))
        rows = module.probe("task tracker", runner=runner)
        self.assertEqual({r['platform'] for r in rows if 'url' in r}, {'github', 'reddit', 'twitter'})
        self.assertTrue(any(r['platform'] == 'v2ex' and 'error' in r for r in rows))
        self.assertTrue(all(isinstance(argv, list) and kwargs.get('timeout') == 30 and not kwargs.get('shell') for argv, kwargs in calls))
        self.assertTrue(all(r['title'] == 'Demand' and r['fetched_at'] for r in rows if 'url' in r))

    def test_missing_command(self):
        self.assertIsNotNone(module, 'demand_probe.py is missing')
        def runner(argv, **kwargs):
            raise FileNotFoundError(argv[0])
        rows = module.probe('query', runner=runner)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all('error' in row for row in rows))

    def test_twitter_cli_response(self):
        self.assertIsNotNone(module, 'demand_probe.py is missing')
        def runner(argv, **kwargs):
            payload = {'ok': True, 'data': [{'id': '123', 'author': {'screenName': 'person'}, 'text': 'Need this', 'metrics': {'likes': 8}}]} if argv[0] == 'twitter' else []
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload))
        row = module.probe('query', runner=runner)[0]
        self.assertEqual((row['url'], row['engagement']), ('https://x.com/person/status/123', 8))

    def test_invalid_urls_are_dropped(self):
        self.assertIsNotNone(module, 'demand_probe.py is missing')
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, json.dumps([{'url': 'http://example.com'}, {'url': 'javascript:alert(1)'}, {'url': 'https://example.com/post', 'title': 'valid'}]))
        rows = module.probe('query', runner=runner)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row['url'] == 'https://example.com/post' for row in rows if 'url' in row))

    def test_duplicate_url_once_per_idea(self):
        self.assertIsNotNone(module, 'demand_probe.py is missing')
        with tempfile.TemporaryDirectory() as tmp:
            with sqlite3.connect(Path(tmp) / 'test.sqlite') as conn:
                conn.execute('CREATE TABLE ideas (id INTEGER PRIMARY KEY)')
                module.init_table(conn)
                row = {'platform': 'github', 'url': 'https://example.com/1', 'title': 'A', 'engagement': 1, 'fetched_at': 'today'}
                module.store(conn, 1, [row, row])
                module.store(conn, 2, [row])
                self.assertEqual(conn.execute('SELECT count(*) FROM demand').fetchone()[0], 2)

    def test_unparseable_response_is_error(self):
        self.assertIsNotNone(module, 'demand_probe.py is missing')
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, '<html>not search results</html>')
        self.assertTrue(all('error' in r for r in module.probe('query', runner=runner)))

    def test_worker_stores_and_api_exposes_rows(self):
        self.assertIsNotNone(module, 'demand_probe.py is missing')
        from unittest.mock import patch
        from test_hub_intake import HubIntakeTests
        fixture = HubIntakeTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        status, result = fixture.api('/api/ingest', {'url': 'https://youtu.be/example'})
        self.assertEqual(status, 200)
        idea_id = result['id']
        with fixture.app.db() as conn:
            conn.execute("UPDATE ideas SET video_title='Task tracker', eval_status='done' WHERE id=?", (idea_id,))
        row = {'platform': 'github', 'url': 'https://example.com/post', 'title': 'Requested', 'engagement': 2, 'fetched_at': 'today'}
        with patch.object(fixture.app, 'evaluate_job', return_value=True), patch.object(module, 'probe', return_value=[row]) as search:
            self.assertTrue(fixture.app.handle_job({'kind': 'evaluate', 'idea_id': idea_id}))
        search.assert_called_once_with('Task tracker')
        _, payload = fixture.api('/api/ideas?dismissed=1')
        self.assertEqual(payload['ideas'][0]['demand'][0]['url'], row['url'])
        with fixture.app.db() as conn:
            self.assertEqual(conn.execute("SELECT detail FROM events WHERE kind='demand'").fetchone()[0], 'demand: 1 posts from 1 platforms')


if __name__ == '__main__':
    unittest.main()

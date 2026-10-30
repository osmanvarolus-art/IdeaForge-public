"""Offline hub intake, durable factory decisions and page rendering checks."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FactoryHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with sqlite3.connect(self.server.database) as conn:
            recorded = conn.execute("SELECT COUNT(*) FROM decisions WHERE action='send' AND status='pending'").fetchone()[0]
        self.server.calls.append((self.path, payload, recorded))
        body = json.dumps(self.server.payload).encode()
        self.send_response(self.server.status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class HubIntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.hub = self.root / 'candidates.jsonl'
        self.hub.write_text('')
        self.goals = self.root / 'goals'
        self.goals.mkdir()
        self.factory = self.server(FactoryHandler)
        self.factory.calls = []
        self.factory.status = 202
        self.factory.payload = {'task': 'goal-20261017-fixture'}
        self.factory.database = str(self.root / 'ideas.db')
        self.env = patch.dict(os.environ, {
            'PATH': os.defpath, 'HOME': str(self.root), 'IDEAFORGE_ALLOW_NO_AI': '1',
            'IDEAFORGE_HUB_FILE': str(self.hub), 'IDEAFORGE_GOALS_DIR': str(self.goals),
            'IDEAFORGE_NORTH_STAR': f'http://127.0.0.1:{self.factory.server_port}',
            'IDEAFORGE_HUB_MAX_PER_RUN': '2',
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        loader = importlib.machinery.SourceFileLoader('ideaforge_hub_fixture', str(ROOT / 'ideaforge'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.app = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'dotenv': types.SimpleNamespace(load_dotenv=lambda *_: None)}):
            loader.exec_module(self.app)
        self.app.DB_PATH = self.factory.database
        self.app.DATA_DIR = str(self.root / 'data')
        self.app.init_db()
        self.app.JOBQ = queue.Queue()
        class QuietHandler(self.app.Handler):
            def log_message(self, *_):
                pass
        self.http = self.server(QuietHandler)

    def server(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        return server

    def api(self, path, body=None):
        request = Request(f'http://127.0.0.1:{self.http.server_port}' + path,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def rows(self, rows):
        self.hub.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')

    def candidate(self, identifier, kind='video', seen='2026-10-17T10:00:00Z', history=False):
        return {'id': identifier, 'kind': kind, 'title': 'Idea ' + identifier, 'summary': 'Useful technique',
                'url': 'https://youtu.be/' + identifier if kind == 'video' else 'https://example.org/' + identifier,
                'source': ['notebook-ideas', 'funnel'], 'seen_at': seen,
                'techniques': ['youtube-history'] if history else []}

    def sync(self):
        status, result = self.api('/api/hub/sync', {})
        self.assertEqual(status, 200, 'hub sync unavailable')
        self.assertTrue(result['ok'])
        return result

    def cards(self):
        status, result = self.api('/api/hub/cards')
        self.assertEqual(status, 200, 'hub cards unavailable')
        return result['cards']

    def test_history_priority_video_identity_cap_and_read_only_hub(self):
        self.api('/api/ingest', {'url': 'https://www.youtube.com/watch?v=existing&list=abc'})
        self.app.JOBQ.get_nowait()
        existing = self.candidate('existing')
        older = self.candidate('history-old', seen='2026-10-16T20:00:00Z', history=True)
        newer = self.candidate('history-new', seen='2026-10-17T12:30:00+02:00', history=True)
        regular = self.candidate('regular', seen='2026-10-18T10:00:00Z')
        alias = {**newer, 'id': 'alias', 'url': 'https://www.youtube.com/shorts/history-new'}
        self.rows([regular, existing, older, newer, alias])
        before = self.hub.read_bytes()
        counts = self.sync()
        self.assertEqual((counts['queued'], counts['skipped_duplicate']), (2, 2))
        jobs = [self.app.JOBQ.get_nowait(), self.app.JOBQ.get_nowait()]
        self.assertEqual([j['url'] for j in jobs], [newer['url'], older['url']])
        self.assertTrue(all(j['kind'] == 'extract' and not j['chain'] for j in jobs))
        self.assertTrue(self.app.JOBQ.empty())
        self.assertEqual(self.sync()['queued'], 1)
        self.assertEqual(self.sync()['queued'], 0)
        self.assertEqual(self.hub.read_bytes(), before, 'hub was written')
        status, repeated = self.api('/api/ingest', {'url': 'https://youtube.com/embed/history-new'})
        self.assertEqual((status, repeated['status']), (200, 'existing'))
        self.assertEqual(len(self.api('/api/ideas')[1]['ideas']), 4)

    def test_default_cap_cards_all_kinds_and_concurrent_sync(self):
        del os.environ['IDEAFORGE_HUB_MAX_PER_RUN']
        rows = [self.candidate('video-' + str(i)) for i in range(21)]
        rows += [self.candidate(kind, kind) for kind in ('repo', 'paper', 'article', 'idea', 'model')]
        rows += [[], {'id': 'invalid'}, self.candidate('bad-host') | {'url': 'https://youtube.com.evil/video'}]
        self.rows(rows)
        before = self.hub.read_bytes()
        result = self.sync()
        self.assertEqual((result['queued'], result['cards_added']), (20, 5))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.sync(), range(2)))
        self.assertEqual(sum(r['queued'] for r in results), 1, 'concurrent duplicate video')
        self.assertEqual(sum(r['cards_added'] for r in results), 0)
        self.assertEqual(len(self.cards()), 5)
        self.assertEqual(self.app.JOBQ.qsize(), 21, 'non-video was ingested')
        self.assertEqual(self.hub.read_bytes(), before)

    def test_send_records_intent_goal_status_and_deduplicates_clicks(self):
        self.rows([self.candidate('repo', 'repo')])
        self.sync()
        item = {'item': 'hub:repo', 'action': 'send'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.api('/api/factory/decision', item), range(2)))
        self.assertTrue(any(result[1]['ok'] for result in results))
        self.assertEqual(len(self.factory.calls), 1, 'duplicate send')
        path, body, recorded = self.factory.calls[0]
        self.assertEqual(path, '/api/goals')
        self.assertEqual(body, {'text': 'Harvested idea: Idea repo. Source: IdeaForge; found by: notebook-ideas, funnel. '
            'Link: https://example.org/repo. Summary: Useful technique. Evaluation: not evaluated, fit not available.'})
        self.assertEqual(recorded, 1, 'send before decision persisted')
        with self.app.db() as conn:
            self.assertEqual(conn.execute("SELECT item, action, goal, status FROM decisions").fetchone(),
                             ('hub:repo', 'send', 'goal-20261017-fixture', 'accepted'))
        goal_dir = self.goals / 'goal-20261017-fixture'
        goal_dir.mkdir()
        goal_file = goal_dir / 'goal.json'
        goal_file.write_text(json.dumps({'status': 'COLLECTED'}))
        before = goal_file.read_bytes()
        self.assertEqual(self.cards()[0]['factory']['goal_status'], 'COLLECTED')
        self.assertEqual(goal_file.read_bytes(), before)
        self.assertTrue(self.api('/api/factory/decision', item)[1]['ok'])
        self.assertEqual(len(self.factory.calls), 1)

    def test_errors_dismiss_restore_and_evaluated_idea_request(self):
        self.rows([self.candidate('repo', 'repo')])
        self.sync()
        self.factory.status, self.factory.payload = 503, {'error': 'Factory busy'}
        status, result = self.api('/api/factory/decision', {'item': 'hub:repo', 'action': 'send'})
        self.assertEqual(status, 502)
        self.assertIn('Factory busy', result['error'])
        self.assertIn('Factory busy', self.cards()[0]['factory']['error'])
        for action, hidden in [('dismiss', True), ('restore', False)]:
            self.assertTrue(self.api('/api/factory/decision', {'item': 'hub:repo', 'action': action})[1]['ok'])
            self.assertEqual(self.cards()[0]['factory']['dismissed'], hidden)
        idea_id = self.api('/api/ingest', {'url': 'https://youtu.be/evaluated'})[1]['id']
        item = {'item': f'idea:{idea_id}', 'action': 'send'}
        self.assertEqual(self.api('/api/factory/decision', item)[0], 400, 'unevaluated idea sent')
        with self.app.db() as conn:
            conn.execute("UPDATE ideas SET eval_status='done', eval_verdict='BUILD', eval_fit_score=81, "
                         "video_title='Local automation', nlm_summary='A source summary', intake_source='jev-trend' WHERE id=?", (idea_id,))
        self.factory.status, self.factory.payload = 202, {'task': 'goal-20261017-evaluated'}
        self.assertTrue(self.api('/api/factory/decision', item)[1]['ok'])
        self.assertEqual(self.factory.calls[-1][1]['text'], 'Harvested idea: Local automation. Source: IdeaForge; '
            'found by: jev-trend. Link: https://youtu.be/evaluated. Summary: A source summary. Evaluation: BUILD, fit 81.')
        self.api('/api/factory/decision', {**item, 'action': 'dismiss'})
        self.assertEqual(self.api('/api/ideas')[1]['ideas'], [])
        self.assertTrue(self.api('/api/ideas?dismissed=1')[1]['ideas'][0]['factory']['dismissed'])
        self.api('/api/factory/decision', {**item, 'action': 'restore'})
        self.assertEqual(len(self.api('/api/ideas')[1]['ideas']), 1)

    def test_ambiguous_acceptance_does_not_resend_or_read_other_paths(self):
        self.rows([self.candidate('repo', 'repo')])
        self.sync()
        self.factory.payload = {'task': '../outside'}
        item = {'item': 'hub:repo', 'action': 'send'}
        status, result = self.api('/api/factory/decision', item)
        self.assertEqual(status, 502)
        self.assertEqual(result['status'], 'uncertain')
        self.assertIsNone(result['goal'])
        self.api('/api/factory/decision', item)
        self.assertEqual(len(self.factory.calls), 1)
        with self.app.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM decisions WHERE action='send'").fetchone()[0], 1)

    def test_hourly_scheduler_and_worker_use_production_sync(self):
        # Endpoint assertion keeps replay against the old implementation an AssertionError.
        self.sync()
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        with patch.object(self.app, 'STOP', stop), patch.object(self.app, 'scan_due_subscriptions') as scans:
            self.app.radar_loop()
        stop.wait.assert_called_once_with(3600)
        scans.assert_called_once_with()
        job = self.app.JOBQ.get_nowait()
        self.assertEqual(job['kind'], 'hub_sync')
        with patch.object(self.app, 'hub_sync') as sync:
            self.assertTrue(self.app.handle_job(job))
        sync.assert_called_once_with()

    def test_page_actions_source_filter_and_escaping(self):
        page = (ROOT / 'index.html').read_text()
        self.assertIn('data-factory-action', page, 'factory controls missing')
        node = shutil.which('node')
        self.assertTrue(node, 'node required for rendering check')
        functions = page[page.index('function factoryActions('):page.index("document.addEventListener('click', async function(event)")]
        functions += page[page.index('function renderHubCards('):page.index('async function loadNotebooks()')]
        functions += next(line for line in page.splitlines() if line.startswith('function esc('))
        script = "const assert = require('node:assert/strict');\n" + functions + """
const nodes = {'hub-source': {value: 'funnel'}, 'show-dismissed': {checked: false}, 'hub-cards': {innerHTML: ''}};
const document = {getElementById: id => nodes[id]};
let hubCards = [
 {id: 'one', source: 'funnel, notebook-ideas', title: '<img onerror=bad>', summary: '<script>bad</script>', kind: 'repo', seen_at: 'today', url: 'javascript:bad', factory: {}},
 {id: 'two', source: 'funnel', title: 'Hidden', summary: '', kind: 'idea', seen_at: 'today', url: '', factory: {dismissed: true}},
 {id: 'three', source: 'other', title: 'Other source', summary: '', kind: 'paper', seen_at: 'today', url: '', factory: {}}
];
renderHubCards();
assert(nodes['hub-cards'].innerHTML.includes('&lt;img'));
assert(!nodes['hub-cards'].innerHTML.includes('<script>'));
assert(!nodes['hub-cards'].innerHTML.includes('href="javascript:'));
assert(!nodes['hub-cards'].innerHTML.includes('Hidden'));
assert(!nodes['hub-cards'].innerHTML.includes('Other source'));
nodes['show-dismissed'].checked = true; renderHubCards();
assert(nodes['hub-cards'].innerHTML.includes('Restore'));
assert(!factoryActions('idea:1', {}, false).includes('Send to factory'));
assert(factoryActions('idea:1', {status:'accepted', goal:'goal-fixture', goal_status:'COLLECTED'}, true).includes('disabled'));
assert(factoryActions('hub:1', {error:'<bad>'}, true).includes('&lt;bad&gt;'));
"""
        result = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        for script in re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', page, re.S):
            parsed = subprocess.run([node, '--check'], input=script, capture_output=True, text=True, timeout=10)
            self.assertEqual(parsed.returncode, 0, parsed.stderr[-500:])


if __name__ == '__main__':
    unittest.main()

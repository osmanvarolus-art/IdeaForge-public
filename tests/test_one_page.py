"""Offline checks for the consolidated idea page, reusing the intake HTTP fixture."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import test_hub_intake as fixtures


class OnePageTests(unittest.TestCase):
    setUp = fixtures.HubIntakeTests.setUp
    server = fixtures.HubIntakeTests.server
    api = fixtures.HubIntakeTests.api

    def idea(self):
        status, result = self.api('/api/ingest', {'url': 'https://youtu.be/one-page'})
        self.assertEqual(status, 200)
        identifier = result['id']
        evaluation = self.root / 'evaluation.json'
        evaluation.write_text(json.dumps({'top_idea': {'one_sentence': 'Useful core', 'problem': 'Lost work'},
                                         'execution': {'architecture': 'Local service', 'suggested_stack': ['Python', 'SQLite']}}))
        with self.app.db() as conn:
            conn.execute("UPDATE ideas SET video_title='A useful idea', eval_status='done', eval_verdict='BUILD', "
                         "eval_fit_score=82, eval_complexity=2, nlm_summary='Source summary', evaluation_path=? WHERE id=?",
                         (str(evaluation), identifier))
        return 'idea:' + str(identifier)

    def favourite(self, item, action='favourite'):
        status, result = self.api('/api/factory/decision', {'item': item, 'action': action})
        self.assertEqual(status, 200, 'favourite unavailable')
        self.assertTrue(result['ok'])

    def test_scout_history_outcome_and_missing_are_read_only(self):
        import os
        history = self.root / 'scout' / 'history.jsonl'
        history.parent.mkdir()
        os.environ['IDEAFORGE_SCOUT_HISTORY'] = str(history)
        status, result = self.api('/api/scout')
        self.assertEqual(status, 200, 'scout unavailable')
        self.assertEqual(result['runs'], [])
        rows = [{'id': 'run-one', 'stage': 'monitor', 'data': {'decide': {'decision': 'build', 'winner': 'workshop-card', 'reasons': ['Supported pilot']}}},
                {'id': 'run-two', 'stage': 'decide', 'result': {'decision': 'none', 'winner': 'other', 'reasons': ['Low confidence']}},
                {'id': '../escape', 'stage': 'monitor'}]
        history.write_text('\n'.join(json.dumps(row) for row in rows) + '\ninvalid\n')
        run = history.parent / 'run-one'
        run.mkdir()
        outcome = run / 'outcome.json'
        outcome.write_text(json.dumps({'product_id': 'workshop-card', 'outcome': 'simulation-pending', 'live': True}))
        before = {p: p.read_bytes() for p in (history, outcome)}
        status, result = self.api('/api/scout')
        self.assertEqual(status, 200)
        self.assertEqual([r['id'] for r in result['runs']], ['run-two', 'run-one'])
        self.assertEqual(result['runs'][0]['decision'], 'none')
        self.assertEqual(result['runs'][0]['reason'], ['Low confidence'])
        self.assertEqual(result['runs'][1]['stage'], 'monitor')
        self.assertEqual(result['runs'][1]['decision'], 'BUILD')
        self.assertEqual(result['runs'][1]['product'], 'workshop-card')
        self.assertEqual(result['runs'][1]['product_state'], 'simulation-pending')
        self.assertTrue(result['runs'][1]['outcome']['live'])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_favourite_and_undo_preserve_other_decisions(self):
        item = self.idea()
        self.favourite(item)
        self.api('/api/factory/decision', {'item': item, 'action': 'dismiss'})
        _, data = self.api('/api/ideas?dismissed=1')
        self.assertTrue(data['ideas'][0]['factory']['favourite'])
        self.assertTrue(data['ideas'][0]['factory']['dismissed'])
        self.favourite(item, 'unfavourite')
        _, data = self.api('/api/ideas?dismissed=1')
        self.assertFalse(data['ideas'][0]['factory']['favourite'])
        self.assertTrue(data['ideas'][0]['factory']['dismissed'])
        with self.app.db() as conn:
            self.assertEqual([r[0] for r in conn.execute('SELECT action FROM decisions ORDER BY id')],
                             ['favourite', 'dismiss', 'unfavourite'])
        self.assertEqual(self.factory.calls, [])

    def test_markdown_card_and_favourite_download(self):
        item = self.idea()
        status, result = self.api('/api/markdown?item=' + item)
        self.assertEqual(status, 200, 'markdown unavailable')
        for value in ('A useful idea', 'https://youtu.be/one-page', 'BUILD', 'Source summary', 'Useful core', 'Lost work', 'Python'):
            self.assertIn(value, result['markdown'])
        self.assertEqual(self.api('/api/markdown?favourites=1')[1]['markdown'], '')
        self.favourite(item)
        self.assertEqual(self.api('/api/markdown?favourites=1')[1]['markdown'], result['markdown'])
        self.favourite(item, 'unfavourite')
        self.assertEqual(self.api('/api/markdown?favourites=1')[1]['markdown'], '')

    def test_hub_favourites_and_export(self):
        with self.app.db() as conn:
            conn.execute("INSERT INTO hub_cards VALUES ('paper', 'paper', 'Research card', 'Research summary', 'https://example.org/paper', 'research', 'today')")
        self.favourite('hub:paper')
        _, result = self.api('/api/hub/cards')
        self.assertTrue(result['cards'][0]['factory']['favourite'])
        _, result = self.api('/api/markdown?favourites=1')
        for value in ('Research card', 'Research summary', 'https://example.org/paper', 'Not evaluated'):
            self.assertIn(value, result['markdown'])
        self.favourite('hub:paper', 'unfavourite')
        self.assertEqual(self.api('/api/markdown?favourites=1')[1]['markdown'], '')

    def test_details_and_history_filter_provenance(self):
        self.idea()
        self.hub.write_text(json.dumps({'kind': 'video', 'url': 'https://youtube.com/watch?v=one-page', 'techniques': ['youtube-history']}) + '\n')
        before = self.hub.read_bytes()
        _, result = self.api('/api/ideas')
        idea = result['ideas'][0]
        self.assertIn('details', idea, 'card details missing')
        self.assertEqual(idea['details'], {'core': 'Useful core', 'problem': 'Lost work', 'architecture': 'Local service', 'stack': ['Python', 'SQLite']})
        self.assertTrue(idea['youtube_history'])
        self.assertEqual(self.hub.read_bytes(), before)
        self.hub.write_text(json.dumps({'kind': 'video', 'url': 'https://youtu.be/other-video', 'techniques': ['youtube-history']}) + '\n')
        self.assertFalse(self.api('/api/ideas')[1]['ideas'][0]['youtube_history'])

    def test_page_controls_and_common_filters(self):
        page = (ROOT / 'index.html').read_text()
        for control in ('scout-panel', 'verdict-filter', 'only-favourites', 'only-sent', 'show-dismissed', 'hub-source', 'Copy as Markdown', 'Download favourites as Markdown', 'Favourite'):
            self.assertIn(control, page, 'one-page control missing')
        functions = page[page.index('function matchesCard('):page.index('function renderAllCards(')]
        functions += page[page.index('function ideaDetailFields('):page.index('async function loadNotebooks()')]
        functions += next(line for line in page.splitlines() if line.startswith('function esc('))
        script = "const assert = require('node:assert/strict');\n" + functions + """
const nodes = {'hub-source': {value: ''}, 'verdict-filter': {value:'all'}, 'only-favourites':{checked:false}, 'only-sent':{checked:false}, 'show-dismissed':{checked:false}};
const document = {getElementById: id => nodes[id]};
const idea = {intake_source:'history, collector', youtube_history:true, eval_verdict:'BUILD', factory:{favourite:true, goal:'goal-test'}};
const hub = {source:'collector', factory:{}};
assert(matchesCard(idea, 'idea')); assert(matchesCard(hub, 'hub'));
const detail = ideaDetailFields({...idea, eval_fit_score:82, eval_complexity:2, nlm_summary:'<Source summary>', details:{core:'Useful core', problem:'Lost work', stack:['Python']}});
assert(detail.includes('Fit: 82')); assert(detail.includes('Complexity: 2'));
assert(detail.includes('Lost work')); assert(detail.includes('&lt;Source summary&gt;'));
assert(!detail.includes('<Source summary>'));
nodes['hub-source'].value='__history__'; assert(matchesCard(idea,'idea')); assert(!matchesCard(hub,'hub'));
nodes['hub-source'].value='__hub__'; assert(!matchesCard(idea,'idea')); assert(matchesCard(hub,'hub'));
nodes['hub-source'].value='other'; assert(!matchesCard(idea,'idea')); assert(!matchesCard(hub,'hub'));
nodes['hub-source'].value='collector'; assert(matchesCard(idea,'idea')); assert(matchesCard(hub,'hub'));
nodes['verdict-filter'].value='BUILD'; assert(matchesCard(idea,'idea')); assert(!matchesCard(hub,'hub'));
nodes['verdict-filter'].value='pending'; assert(!matchesCard(idea,'idea')); assert(matchesCard(hub,'hub'));
nodes['verdict-filter'].value='all'; nodes['only-favourites'].checked=true;
assert(matchesCard(idea,'idea')); assert(!matchesCard(hub,'hub'));
nodes['only-favourites'].checked=false; nodes['only-sent'].checked=true;
assert(matchesCard(idea,'idea')); assert(!matchesCard(hub,'hub'));
idea.factory.dismissed=true; assert(!matchesCard(idea,'idea'));
nodes['show-dismissed'].checked=true; assert(matchesCard(idea,'idea'));
"""
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])


if __name__ == '__main__':
    unittest.main()

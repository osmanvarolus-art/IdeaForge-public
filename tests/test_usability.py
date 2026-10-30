"""Offline regressions for evaluation quality, bounded queues and filtered rendering."""
import copy
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_llm_backend as relay_fixture
import test_hub_intake as hub_fixture


class EvaluationUsabilityTests(unittest.TestCase):
    setUp = relay_fixture.BackendTests.setUp
    start_server = relay_fixture.BackendTests.start_server
    load_app = relay_fixture.BackendTests.load_app
    seed_evaluation = relay_fixture.BackendTests.seed_evaluation

    def answer(self, value):
        return (200, {'choices': [{'message': {'content': json.dumps(value)}}]})

    def test_placeholder_retries_and_records_actual_model(self):
        valid = self.seed_evaluation()
        invalid = copy.deepcopy(valid)
        invalid['top_idea']['one_sentence'] = '...'
        self.relay.replies = {'first': self.answer(invalid), 'second': self.answer(valid)}
        original = self.app.llm_call
        def call(*args, **kwargs):
            result = original(*args, **kwargs)
            self.app.MODEL = 'another-concurrent-call'
            return result
        with patch.object(self.app, 'llm_call', call), patch.object(self.app, 'refresh_brief_counters'):
            self.assertTrue(self.app.evaluate_job(1))
        calls = [r[2]['model'] for r in self.relay.requests if r[2]]
        self.assertEqual(calls, ['first', 'second'], 'placeholder accepted')
        with self.app.db() as conn:
            self.assertEqual(conn.execute('SELECT eval_model, eval_verdict FROM ideas').fetchone(), ('second', 'PARK'))
            detail = json.loads(conn.execute("SELECT detail FROM events WHERE kind='eval:done'").fetchone()[0])
        self.assertEqual((detail['model'], detail['fit_score'], detail['verdict']), ('second', 63, 'PARK'))

    def test_all_placeholder_answers_fail_once_without_done(self):
        invalid = self.seed_evaluation()
        invalid['top_idea']['one_sentence'] = ' . … . '
        self.relay.content = json.dumps(invalid)
        self.assertFalse(self.app.evaluate_job(1), 'placeholder marked done')
        with self.app.db() as conn:
            self.assertEqual(conn.execute('SELECT eval_status,last_error,eval_verdict FROM ideas').fetchone(),
                ('failed', 'evaluation copied the template placeholders', None))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='eval:done'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='eval:failed'").fetchone()[0], 1)
        self.assertEqual(len([r for r in self.relay.requests if r[2]]), 2, 'extra fallback')
        self.assertFalse((self.root / 'data/1/evaluation.json').exists())

    def test_nested_placeholders_and_real_content_controls(self):
        valid = self.seed_evaluation()
        for sentence in ('', ' ', '...', '…', '. . .', None):
            invalid = copy.deepcopy(valid)
            invalid['top_idea']['one_sentence'] = sentence
            with self.subTest(sentence=sentence), self.assertRaisesRegex(ValueError, 'copied the template'):
                self.app.parse_evaluation(json.dumps(invalid))
        invalid = copy.deepcopy(valid)
        invalid['why_now'] = '...'
        invalid['mvp_scope'] = ['actual feature', ' ... ']
        with self.assertRaisesRegex(ValueError, 'copied the template'):
            self.app.parse_evaluation(json.dumps(invalid))
        valid['why_now'] = '...'
        valid['mvp_scope'] = ['Uses ... in a meaningful sentence']
        self.assertEqual(self.app.parse_evaluation(json.dumps(valid)), valid)
        with self.assertRaisesRegex(ValueError, 'no parseable JSON verdict'):
            self.app.parse_evaluation('{"top_idea":{"one_sentence":"Real"}}')


class ApiUsabilityTests(unittest.TestCase):
    setUp = hub_fixture.HubIntakeTests.setUp
    server = hub_fixture.HubIntakeTests.server
    api = hub_fixture.HubIntakeTests.api

    def seed_cards(self):
        with self.app.db() as conn:
            for i in range(65):
                source = 'Rare, IdeaForge' if i >= 60 else 'ideaforge'
                conn.execute('INSERT INTO hub_cards VALUES (?,?,?,?,?,?,?)',
                    (f'card-{i:03}', 'repo', f'Card {i}', 'Useful summary', 'https://example.org', source, '2026-10-17'))
        self.api('/api/factory/decision', {'item': 'hub:card-064', 'action': 'favourite'})
        self.api('/api/factory/decision', {'item': 'hub:card-063', 'action': 'dismiss'})
        self.api('/api/factory/decision', {'item': 'hub:card-062', 'action': 'send'})

    def test_paging_and_all_filters_precede_slice(self):
        self.seed_cards()
        status, result = self.api('/api/hub/cards')
        self.assertEqual(len(result['cards']), 30, 'unbounded initial cards')
        self.assertEqual(status, 200)
        self.assertEqual(result['total'], 65)
        self.assertEqual(result['sources'], ['ideaforge', 'rare'])
        status, result = self.api('/api/hub/cards?limit=2&offset=1&source=RARE&dismissed=0')
        self.assertEqual(status, 200)
        self.assertEqual([c['id'] for c in result['cards']], ['card-061', 'card-062'])
        self.assertEqual(result['total'], 4)
        for filters, expected in [('favourites=1', ['card-064']), ('sent=1', ['card-062']),
                                  ('source=rare&verdict=BUILD', []), ('source=__history__', [])]:
            status, result = self.api('/api/hub/cards?limit=30&' + filters)
            self.assertEqual(status, 200)
            self.assertEqual([c['id'] for c in result['cards']], expected)
        status, result = self.api('/api/hub/cards?limit=30&offset=60&dismissed=1&verdict=pending')
        self.assertEqual([c['id'] for c in result['cards']], [f'card-{i:03}' for i in range(60,65)])
        for query in ('limit=-1', 'offset=-1', 'limit=nope'):
            self.assertEqual(self.api('/api/hub/cards?' + query)[0], 400)

    def test_model_counts_use_last_50_snapshots_not_current_idea(self):
        with self.app.db() as conn:
            for i in range(55):
                self.app.log_event(conn, None, 'eval:done', json.dumps({
                    'model': 'collapsed' if i >= 30 else 'varied',
                    'verdict': 'BUILD' if i >= 30 else 'PARK', 'fit_score': 68 if i >= 30 else i}))
            self.app.log_event(conn, None, 'eval:failed', 'not an evaluation')
        status, result = self.api('/api/evaluation-models')
        self.assertEqual(status, 200, 'model insights unavailable')
        self.assertEqual(result['evaluations'], 50)
        rows = {r['model']: r for r in result['models']}
        self.assertEqual((rows['collapsed']['count'], rows['collapsed']['verdicts']['BUILD'],
                          rows['collapsed']['fit_min'], rows['collapsed']['fit_max'], rows['collapsed']['fit_distinct']),
                         (25, 25, 68, 68, 1))
        self.assertEqual((rows['varied']['fit_min'], rows['varied']['fit_max']), (5, 29))
        with self.app.db() as conn:
            conn.execute('DELETE FROM events')
            self.app.log_event(conn, None, 'eval:done', '{}')
        unknown = self.api('/api/evaluation-models')[1]['models'][0]
        self.assertEqual((unknown['model'], unknown['fit_min'], unknown['verdicts']['unknown']), ('Unknown', None, 1))
        with self.app.db() as conn:
            conn.execute('DELETE FROM events')
        self.assertEqual(self.api('/api/evaluation-models')[1]['models'], [])

    def test_backlog_cap_oldest_disabled_and_hourly_sync(self):
        self.app.ai_backend = 'openai-compatible'
        with self.app.db() as conn:
            for i in range(30):
                conn.execute('INSERT INTO ideas(id,youtube_url,eval_status,created_at,updated_at) VALUES (?,?,?,?,?)',
                    (i + 1, f'https://youtu.be/{i}', 'disabled' if i >= 4 else ['done','failed','running','queued'][i], f'{30-i:02}', 'now'))
        status, result = self.api('/api/evaluate-backlog', {'limit': 2})
        self.assertEqual(status, 200, 'backlog unavailable')
        self.assertEqual(result['queued'], 2)
        self.assertEqual([self.app.JOBQ.get_nowait()['idea_id'] for _ in range(2)], [30, 29])
        self.assertEqual(self.api('/api/evaluate-backlog', {})[1]['queued'], 20)
        ids = [self.app.JOBQ.get_nowait()['idea_id'] for _ in range(20)]
        self.assertEqual(ids, list(range(28, 8, -1)))
        with patch.object(self.app, 'hub_sync', return_value={}) as sync:
            self.app.handle_job({'kind': 'hub_sync'})
            sync.assert_called_once()
        self.assertEqual([self.app.JOBQ.get_nowait()['idea_id'] for _ in range(4)], [8, 7, 6, 5])
        self.assertEqual(self.api('/api/evaluate-backlog', {})[1]['queued'], 0)
        self.assertTrue(self.app.JOBQ.empty())
        self.assertEqual(self.api('/api/evaluate-backlog', {'limit': -1})[0], 400)
        self.assertEqual(self.api('/api/evaluate-backlog', {'limit': True})[0], 400)
        with self.app.db() as conn:
            self.assertEqual([r[0] for r in conn.execute('SELECT eval_status FROM ideas WHERE id<=4 ORDER BY id')],
                             ['done', 'failed', 'running', 'queued'])


class PageUsabilityTests(unittest.TestCase):
    def node(self, code):
        self.assertIsNotNone(shutil.which('node'), 'Node required for production rendering checks')
        result = subprocess.run(['node', '-e', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr[-900:])

    def test_page_order_collapsed_summary_and_focus(self):
        page = (ROOT / 'index.html').read_text()
        self.assertLess(page.index('id="ideas-list"'), page.index('id="scout-panel"'), 'Scout precedes ideas')
        self.assertLess(page.index('id="page-filters"'), page.index('id="scout-panel"'))
        self.assertIn('<details id="scout-details">', page)
        self.assertIn('id="scout-summary"', page)
        self.assertIn('.main-tab:focus-visible', page)
        self.assertIn('.discovery-glow.main-tab::after { content: none; }', page)
        self.assertIn('padding-bottom: 80px', page)
        self.assertIn('id="ideas-more"', page)
        self.assertIn('id="hub-more"', page)
        self.assertIn('id="evaluation-models"', page)

    def test_production_field_formatting_and_instruction_guard(self):
        page = (ROOT / 'index.html').read_text()
        code = page[page.index('function ideaDetailFields('):page.index('async function loadEvaluationModels(')] if 'async function loadEvaluationModels(' in page else page[page.index('function ideaDetailFields('):page.index('async function loadNotebooks(')]
        code += page[page.index('async function loadAllSections()'):page.index('async function copySection(')]
        code += next(line for line in page.splitlines() if line.startswith('function esc('))
        self.node("const assert=require('node:assert/strict');\n" + code + r'''
const html=ideaDetailFields({details:{core:'...',problem:'',architecture:' . . ',stack:['Python','...', 'SQLite']},eval_model:'actual-model'});
assert(!html.includes('Core idea'), 'dots core visible');
assert(!html.includes('Architecture'), 'dots architecture visible');
assert(html.includes('Python, SQLite'), 'stack is not plain text');
assert(html.includes('actual-model'), 'model missing');
let currentIdeaId=1, ideaCache=[{id:1,instr_status:'pending'}], calls=[];
const document={getElementById:()=>({textContent:''})};
const fetch=async url=>{calls.push(url);return {ok:false}};
(async()=>{await loadAllSections();assert(!calls.some(url=>url.endsWith('/instruction')), 'unavailable instruction fetched');
ideaCache[0].instr_status='done';await loadAllSections();assert.equal(calls.filter(url=>url.endsWith('/instruction')).length,1)})();
''')

    def test_production_paging_and_normalized_sources(self):
        page = (ROOT / 'index.html').read_text()
        self.assertIn('function showMoreIdeas()', page, 'paging unavailable')
        code = page[page.index('async function loadHubCards()'):page.index('function renderHubCards()')]
        code += page[page.index('function matchesCard('):page.index('function renderAllCards(')]
        code += page[page.index('function renderIdeas('):page.index('function renderStepper(')]
        code += next(line for line in page.splitlines() if line.startswith('function esc('))
        self.node("const assert=require('node:assert/strict');\n" + code + r'''
const nodes={};const document={getElementById:id=>nodes[id]??=( {value:'',checked:false,innerHTML:'',classList:{add(){},remove(){},toggle(){}},replaceChildren(...options){this.options=options}})};
document.getElementById('verdict-filter').value='all';
const Option=function(label,value){this.label=label;this.value=value};
let hubCards=[],hubVisible=30,ideaVisible=30,hubRequest=0;
const ideaCache=Array.from({length:65},(_,i)=>({id:i,video_title:'Idea '+i,intake_source:i%2?'IdeaForge':'ideaforge',eval_verdict:i>=60?'PARK':'BUILD',factory:{favourite:i===64}}));
const selectedIdeas=new Set(),postRenderHooks=[],thumbnailUrl=()=>'',factoryActions=()=>'',ideaDetailFields=()=>'',renderHubCards=()=>{};
let requests=[];const fetch=async url=>{requests.push(url);return {ok:true,json:async()=>({cards:[],total:65,sources:['IDEAFORGE','ideaforge','Later source']})}};
(async()=>{
renderIdeas(ideaCache);assert.equal((nodes['ideas-list'].innerHTML.match(/class="idea-card-visual"/g)||[]).length,30);
showMoreIdeas();assert.equal((nodes['ideas-list'].innerHTML.match(/class="idea-card-visual"/g)||[]).length,60);
nodes['verdict-filter'].value='PARK';ideaVisible=30;renderIdeas(ideaCache);
assert.equal((nodes['ideas-list'].innerHTML.match(/class="idea-card-visual"/g)||[]).length,5,'late-page matches hidden');
nodes['only-favourites'].checked=true;renderIdeas(ideaCache);assert(nodes['ideas-list'].innerHTML.includes('Idea 64'));
await loadHubCards();assert.equal(nodes['hub-source'].options.filter(o=>o.value==='ideaforge').length,1);
assert(nodes['hub-source'].options.some(o=>o.value==='later source'));
assert(requests[0].includes('limit=30'));assert(requests[0].includes('favourites=1'));assert(requests[0].includes('verdict=PARK'));
showMoreHubCards();assert(requests[1].includes('limit=60'));
})();
''')


if __name__ == '__main__':
    unittest.main()

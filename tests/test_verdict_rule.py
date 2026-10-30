"""Offline evidence gate and re-scoring regression checks."""
import io
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class VerdictRuleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {'HOME': str(self.root), 'PATH': os.defpath,
                                    'IDEAFORGE_ALLOW_NO_AI': '1'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        with patch.dict(sys.modules, {'dotenv': types.SimpleNamespace(load_dotenv=lambda *_: None)}):
            self.app = runpy.run_path(str(ROOT / 'ideaforge'), run_name='verdict_fixture')
        self.globals = self.app['db'].__globals__
        self.globals.update(DB_PATH=str(self.root / 'ideas.db'), DATA_DIR=str(self.root / 'data'))
        self.app['init_db']()

    def evaluation(self, score=85, signal='', verdict='BUILD'):
        return {'top_idea': {'one_sentence': 'A customer support tool'},
                'fit': {'fit_score_0_100': score, 'complexity_1_5': 2},
                'build_recommendation': {'verdict': verdict},
                'evidence_hooks': [{'claim': 'Observed demand', 'transcript_support': signal}]}

    def seed(self, evaluation):
        path = self.root / 'evaluation.json'
        path.write_text(json.dumps(evaluation))
        transcript = self.root / 'transcript.txt'
        transcript.write_text('Fixture evidence')
        with self.app['db']() as conn:
            conn.execute("INSERT INTO ideas(id,youtube_url,eval_status,eval_verdict,eval_fit_score,"
                         "evaluation_path,transcript_clean_path,created_at,updated_at) "
                         "VALUES(1,'','done','BUILD',?,?,?,'now','now')",
                         (evaluation['fit']['fit_score_0_100'], str(path), str(transcript)))
        return path

    def test_live_evaluation_demotes_unsupported_build(self):
        answer = self.evaluation(signal='High demand and clear pain, but no evidence.')
        self.seed(answer)
        with patch.dict(self.globals, ai_backend='openai-compatible',
                        llm_call=lambda *a, **kw: (json.dumps(answer), 1, 1),
                        refresh_brief_counters=lambda *_: None):
            self.assertTrue(self.app['evaluate_job'](1), 'evaluation failed')
        with self.app['db']() as conn:
            verdict = conn.execute('SELECT eval_verdict FROM ideas WHERE id=1').fetchone()[0]
            self.assertEqual(verdict, 'PARK', 'unsupported BUILD persisted')
            self.assertEqual(conn.execute('SELECT eval_raw_verdict FROM ideas').fetchone()[0], 'BUILD')

    def test_shared_rule_threshold_and_concrete_signals(self):
        self.assertTrue('evidence_verdict' in self.app, 'evidence rule missing')
        rule = self.app['evidence_verdict']
        for score, signal, expected in (
            (85, 'Acme reports 120 paying customers.', 'BUILD'),
            (85, 'High demand; users need this.', 'PARK'),
            (6, 'Acme reports 120 paying customers.', 'PARK'),
            (85, 'We could reach 120 paying customers.', 'PARK'),
            (85, 'No evidence of 120 paying customers.', 'PARK'),
            (85, '0 paying customers.', 'PARK'),
            (85, '200 stars today; open issues: not visible', 'BUILD'),
            (85, 'Customers paid $40 for Acme.', 'BUILD'),
            (85, 'Customer requested CSV export: https://example.org/issues/7', 'BUILD'),
        ):
            with self.subTest(signal=signal):
                self.assertEqual(rule('BUILD', score, self.evaluation(score, signal), 7), expected)
        self.assertEqual(rule('BUILD', 85, self.evaluation(signal='120 paying customers'), 90), 'PARK')
        self.assertEqual(rule('SKIP', 99, self.evaluation(signal='120 paying customers'), 7), 'SKIP')
        self.assertEqual(rule('BUILD', None, self.evaluation(signal='120 paying customers'), 7), 'PARK')
        self.assertEqual(rule('BUILD', 85, {'evidence_hooks': None}, 7), 'PARK')

    def test_evaluation_uses_effective_threshold(self):
        answer = self.evaluation(signal='Acme reports 120 paying customers.')
        self.seed(answer)
        with patch.dict(self.globals, ai_backend='openai-compatible',
                        llm_call=lambda *a, **kw: (json.dumps(answer), 1, 1),
                        compute_patterns=lambda: {'effective_threshold': 90},
                        refresh_brief_counters=lambda *_: None):
            self.assertTrue(self.app['evaluate_job'](1))
        with self.app['db']() as conn:
            self.assertEqual(conn.execute('SELECT eval_verdict FROM ideas').fetchone()[0], 'PARK',
                             'calibrated threshold ignored')

    def test_unreadable_evaluation_never_retains_build(self):
        path = self.seed(self.evaluation(signal='Acme reports 120 paying customers.'))
        self.assertTrue('rescore' in self.app, 'rescore missing')
        path.write_text('not JSON')
        with redirect_stdout(io.StringIO()):
            result = self.app['rescore']()
        self.assertEqual(result['after'], {'PARK': 1})
        self.assertEqual(result['unreadable_evaluations'], 1)
        path.write_text(json.dumps({'build_recommendation': [], 'evidence_hooks': None}))
        with redirect_stdout(io.StringIO()):
            result = self.app['rescore']()
        self.assertEqual(result['after'], {'PARK': 1})

    def test_rescore_dry_run_and_apply_preserve_raw_and_owner_data(self):
        path = self.seed(self.evaluation())
        self.assertTrue('rescore' in self.app, 'rescore missing')
        with self.app['db']() as conn:
            before = '\n'.join(conn.iterdump())
        output = io.StringIO()
        with patch.dict(self.globals, llm_call=lambda *_a, **_kw: self.fail('model called')):
            with redirect_stdout(output):
                summary = self.app['rescore']()
            with self.app['db']() as conn:
                self.assertEqual('\n'.join(conn.iterdump()), before, 'dry run wrote data')
            self.assertEqual(summary['before']['BUILD'], 1)
            self.assertEqual(summary['after']['PARK'], 1)
            self.assertIn('before', output.getvalue())
            self.assertIn('after', output.getvalue())
            original = path.read_bytes()
            with redirect_stdout(io.StringIO()):
                self.app['rescore'](apply=True)
                self.app['rescore'](apply=True)
        with self.app['db']() as conn:
            self.assertEqual(conn.execute('SELECT eval_verdict,eval_raw_verdict FROM ideas').fetchone(),
                             ('PARK', 'BUILD'))
            self.assertEqual(conn.execute('SELECT outcome,outcome_notes,outcome_at FROM ideas').fetchone(),
                             (None, None, None), 'owner columns changed')
        self.assertEqual(path.read_bytes(), original, 'raw evaluation overwritten')

    def test_rescore_legacy_schema_and_cli(self):
        self.seed(self.evaluation())
        self.assertTrue('rescore' in self.app, 'rescore missing')
        with sqlite3.connect(self.globals['DB_PATH']) as conn:
            conn.execute('ALTER TABLE ideas DROP COLUMN eval_raw_verdict')
            before = '\n'.join(conn.iterdump())
        with patch.dict(sys.modules, {'dotenv': types.SimpleNamespace(load_dotenv=lambda *_: None)}), \
             patch.object(sys, 'argv', ['ideaforge', 'rescore', '--dry-run', '--db', self.globals['DB_PATH']]), \
             redirect_stdout(io.StringIO()) as output:
            runpy.run_path(str(ROOT / 'ideaforge'), run_name='__main__')
        self.assertEqual(json.loads(output.getvalue())['after']['PARK'], 1)
        with sqlite3.connect(self.globals['DB_PATH']) as conn:
            self.assertEqual('\n'.join(conn.iterdump()), before, 'legacy dry run migrated schema')

    def test_backfill_uses_evidence_rule(self):
        self.seed(self.evaluation())
        with self.app['db']() as conn:
            conn.execute('UPDATE ideas SET eval_verdict=NULL')
        self.app['backfill_verdicts']()
        with self.app['db']() as conn:
            self.assertEqual(conn.execute('SELECT eval_verdict FROM ideas').fetchone()[0], 'PARK',
                             'backfill bypassed evidence rule')


if __name__ == '__main__':
    unittest.main()

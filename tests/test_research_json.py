"""Network-free research reply regressions using actual function definitions."""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

def functions():
    tree = ast.parse((ROOT / 'ideaforge').read_text())
    names = {'parse_json_object', 'research_planner', 'research_rerank', 'research_json_call'}
    namespace = dict(json=json, re=re, log=lambda *args: None, MODEL='fixture',
                     compute_patterns=lambda: {}, EVAL_PROFILE=dict.fromkeys(
                         ['developer_profile', 'budget', 'domain_advantage', 'style'], 'fixture'))
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), 'ideaforge', 'exec'), namespace)
    return namespace

class ResearchJSON(unittest.TestCase):
    def test_planner_prose_and_validation_fallback(self):
        app = functions()
        attempts = []
        def call(*args, validate=None, model_info=None, **kwargs):
            for name, text in [('bad', 'no structured reply'), ('good', 'The user wants a JSON object... {"queries":["one","two","three"]}')]:
                attempts.append(name)
                if model_info is not None: model_info['model'] = name
                try:
                    if validate: validate(text)
                except ValueError:
                    continue
                return text, 0, 0
            raise ValueError('invalid models')
        app['llm_call'] = call
        self.assertEqual(app['research_planner']('brief')['queries'], ['one','two','three'], 'planner lost JSON')
        self.assertEqual(attempts, ['bad','good'])

    def test_invalid_schema_keeps_existing_fallbacks(self):
        app = functions()
        logs = []
        app['log'] = logs.append
        def call(*args, validate=None, model_info=None, **kwargs):
            if model_info is not None: model_info['model'] = 'invalid-fixture'
            if validate: validate('{"queries":[]}')
            return '{"queries":[]}', 0, 0
        app['llm_call'] = call
        self.assertEqual(app['research_planner']('brief')['queries'], ['brief'])
        self.assertEqual(app['research_rerank']([{'title':'fixture'}], {}, 'brief')[0]['score'], 50)
        self.assertTrue(any('model=invalid-fixture' in line for line in logs))

    def test_reranker_array_and_wrapper(self):
        for response in ['[{"index":0,"score":87}]', '{"results":[{"index":0,"score":87}]}']:
            app = functions()
            def call(*args, validate=None, **kwargs):
                if validate: validate(response)
                return response, 0, 0
            app['llm_call'] = call
            try:
                result = app['research_rerank']([{'title':'fixture'}], {}, 'brief')
            except (TypeError, ValueError):
                self.fail('reranker rejected JSON wrapper')
            self.assertEqual(result[0]['score'], 87, 'reply score lost')

if __name__ == '__main__':
    unittest.main()

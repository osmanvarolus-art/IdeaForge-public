#!/usr/bin/env python3
"""Factory observations stay separate from owner outcomes."""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FactoryOutcomeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.goals = self.root / "goals"
        self.goals.mkdir()
        (self.root / "hub.jsonl").write_text("")
        env = patch.dict(os.environ, {
            "PATH": os.defpath, "HOME": str(self.root), "IDEAFORGE_ALLOW_NO_AI": "1",
            "IDEAFORGE_GOALS_DIR": str(self.goals),
            "IDEAFORGE_HUB_FILE": str(self.root / "hub.jsonl"),
        }, clear=True)
        env.start()
        self.addCleanup(env.stop)
        with patch.dict(sys.modules, {"dotenv": types.SimpleNamespace(load_dotenv=lambda *_: None)}):
            self.app = runpy.run_path(str(ROOT / "ideaforge"), run_name="factory_outcome_test")
        self.app["db"].__globals__["DB_PATH"] = str(self.root / "ideas.db")
        self.app["init_db"]()
        with self.app["db"]() as conn:
            for idea_id in (3, 4, 5, 6, 7, 33):
                conn.execute("INSERT INTO ideas (id, youtube_url, eval_status, eval_verdict, "
                             "eval_fit_score, created_at, updated_at) VALUES (?, ?, 'done', 'BUILD', 70, ?, ?)",
                             (idea_id, f"https://youtu.be/{idea_id}", "2026-10-17", "2026-10-17"))
            conn.execute("UPDATE ideas SET outcome='shipped', outcome_notes='owner proof', "
                         "outcome_at='2026-10-18' WHERE id=6")

    def goal(self, stamp, idea_text, status):
        goal_id = f"goal-20261018{stamp}-1111111111"
        path = self.goals / goal_id
        path.mkdir()
        (path / "goal.json").write_text(json.dumps({
            "goal": idea_text, "status": status,
            "submitted_at": f"2026-10-18T{stamp[:2]}:{stamp[2:]}:00+00:00",
        }))
        return goal_id

    def seed_evidence(self):
        older = self.goal("0001", "Draft ideaforge:3", "QUEUED")
        merged = self.goal("0002", "Build ideaforge:3", "MERGED")
        queued = self.goal("0003", "Build ideaforge:33", "QUEUED")
        parked = self.goal("0004", "Sent through IdeaForge", "PARKED")
        failed = self.goal("0005", "Build ideaforge:6", "FAILED")
        with self.app["db"]() as conn:
            conn.execute("INSERT INTO decisions (item, action, goal, at) VALUES "
                         "('idea:4', 'send', ?, '2026-10-18T00:04:00Z')", (parked,))
            conn.execute("INSERT INTO decisions (item, action, at) VALUES "
                         "('idea:5', 'dismiss', '2026-10-18T00:06:00Z')")
        return older, merged, queued, parked, failed

    def test_goal_statuses_exact_citations_dismissal_and_owner_columns(self):
        self.seed_evidence()
        self.assertTrue("refresh_factory_outcomes" in self.app, "factory refresh missing")
        with self.app["db"]() as conn:
            before = conn.execute("SELECT id, outcome, outcome_notes, outcome_at FROM ideas ORDER BY id").fetchall()
        self.app["refresh_factory_outcomes"]()
        with self.app["db"]() as conn:
            rows = dict((idea_id, (result, goal, status, evidence, at)) for idea_id, result, goal,
                        status, evidence, at in conn.execute(
                            "SELECT idea_id, result, goal, goal_status, evidence, at FROM factory_outcomes"))
            after = conn.execute("SELECT id, outcome, outcome_notes, outcome_at FROM ideas ORDER BY id").fetchall()
        self.assertEqual(before, after, "owner outcome changed")
        self.assertEqual({key: row[0] for key, row in rows.items()},
                         {3: "shipped", 33: "in_progress", 4: "abandoned",
                          5: "dismissed", 6: "abandoned"})
        self.assertNotIn(7, rows)
        self.assertEqual(rows[3][2], "MERGED")
        self.assertEqual(rows[33][2], "QUEUED")
        self.assertIn(rows[3][1], rows[3][3])
        self.assertIn("dismissed 2026-10-18T00:06:00Z", rows[5][3])
        self.app["refresh_factory_outcomes"]()
        with self.app["db"]() as conn:
            self.assertEqual(rows, dict((idea_id, (result, goal, status, evidence, at))
                for idea_id, result, goal, status, evidence, at in conn.execute(
                    "SELECT idea_id, result, goal, goal_status, evidence, at FROM factory_outcomes")))

    def test_api_and_calibration_prefer_owner_outcome(self):
        self.seed_evidence()
        self.assertTrue("refresh_factory_outcomes" in self.app, "factory refresh missing")
        handler = type("QuietHandler", (self.app["Handler"],),
                       {"log_message": lambda *_: None})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        with urlopen(f"http://127.0.0.1:{server.server_port}/api/ideas?dismissed=1") as response:
            ideas = {idea["id"]: idea for idea in json.load(response)["ideas"]}
        self.assertEqual(ideas[3]["factory_result"], "shipped")
        self.assertIn("MERGED", ideas[3]["factory_evidence"])
        self.assertEqual(ideas[33]["factory_result"], "in_progress")
        self.assertEqual(ideas[5]["factory_result"], "dismissed")
        self.assertEqual(ideas[6]["outcome"], "shipped")
        calibration = self.app["compute_calibration"]()
        self.assertEqual((calibration["owner_n"], calibration["factory_n"],
                          calibration["total_with_outcome"]), (1, 4, 5))
        self.assertEqual(calibration["build_ship_rate"], 0.4, "owner outcome not preferred")
        patterns = self.app["compute_patterns"]()
        self.assertEqual((patterns["owner_n"], patterns["factory_n"],
                          patterns["total_outcomes"]), (1, 4, 5))

    def test_page_names_both_sources_and_factory_chip(self):
        page = (ROOT / "index.html").read_text()
        self.assertTrue("owner outcomes" in page, "owner outcomes label missing")
        self.assertTrue("factory outcomes" in page, "factory outcomes label missing")
        self.assertTrue("Factory: " in page, "factory chip missing")
        self.assertTrue("owner_n" in page, "owner count missing")
        self.assertTrue("factory_n" in page, "factory count missing")

    def test_outcome_cohort_excludes_untouched_builds(self):
        self.seed_evidence()
        with self.app['db']() as conn:
            for idea_id, verdict in ((8, 'PARK'), (9, 'BUILD'), (10, 'BUILD')):
                conn.execute("INSERT INTO ideas(id,youtube_url,eval_status,eval_verdict,created_at,updated_at) "
                             "VALUES(?,?,'done',?,'now','now')", (idea_id, str(idea_id), verdict))
            for item, action, goal in (('idea:8', 'favourite', None), ('idea:9', 'send', None),
                                      ('idea:10', 'favourite', None), ('idea:10', 'unfavourite', None)):
                conn.execute("INSERT INTO decisions(item,action,goal,at) VALUES(?,?,?,'now')", (item, action, goal))
        handler = type('QuietHandler', (self.app['Handler'],), {'log_message': lambda *_: None})
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/ideas?dismissed=1') as response:
            data = json.load(response)
        self.assertTrue('outcome_counts' in data, 'outcome cohort missing')
        counts = data['outcome_counts']
        self.assertEqual((counts['total_eligible'], counts['build_waiting']), (6, 3))
        eligible = {i['id'] for i in data['ideas'] if i['outcome_eligible']}
        self.assertEqual(eligible, {3, 4, 5, 6, 8, 33})
        with urlopen(f'http://127.0.0.1:{server.server_port}/api/calibration') as response:
            calibration = json.load(response)['calibration']
        self.assertEqual(calibration['total_eligible'], 6)
        self.assertEqual(calibration['build_waiting'], 3)
        self.assertEqual(self.app['compute_calibration']()['total_eligible'], 6)

        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable for outcome UI check; API cohort verified')
        page = (ROOT / 'index.html').read_text()
        script = page[page.index('async function loadOutcomes()'):page.index('function renderOutcomesList(')]
        program = """
const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const progress = {innerHTML: ''};
global.document = {getElementById: () => progress};
global.fetch = async () => ({json: async () => data.payload});
let pending;
global.renderOutcomesList = items => { pending = items.map(i => i.id); };
eval(data.script);
loadOutcomes().then(() => console.log(JSON.stringify({html: progress.innerHTML, pending})));
"""
        result = subprocess.run([node, '-e', program], input=json.dumps({'payload': data, 'script': script}),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, 'outcome UI failed')
        rendered = json.loads(result.stdout)
        self.assertTrue('1 of 6 owner outcomes' in rendered['html'], 'wrong owner base')
        self.assertTrue('5 of 6 factory outcomes' in rendered['html'], 'wrong factory base')
        self.assertTrue('BUILD ideas waiting: 3' in rendered['html'], 'waiting count missing')
        self.assertEqual(set(rendered['pending']), {3, 4, 5, 8, 33})

    def test_rescore_preserves_existing_owner_ground_truth(self):
        self.assertTrue('rescore' in self.app, 'rescore missing')
        with self.app['db']() as conn:
            before = conn.execute('SELECT id,outcome,outcome_notes,outcome_at FROM ideas ORDER BY id').fetchall()
        self.app['rescore'](apply=True)
        with self.app['db']() as conn:
            after = conn.execute('SELECT id,outcome,outcome_notes,outcome_at FROM ideas ORDER BY id').fetchall()
        self.assertEqual(before, after, 'owner ground truth changed')

    def test_ten_combined_outcomes_activate_calibration(self):
        self.seed_evidence()
        with self.app["db"]() as conn:
            for idea_id in range(8, 13):
                conn.execute("INSERT INTO ideas (id, youtube_url, eval_status, eval_verdict, "
                             "eval_fit_score, created_at, updated_at) VALUES "
                             "(?, ?, 'done', 'BUILD', 70, ?, ?)",
                             (idea_id, f"https://youtu.be/{idea_id}", "2026-10-17", "2026-10-17"))
                conn.execute("INSERT INTO decisions (item, action, at) VALUES "
                             "(?, 'dismiss', '2026-10-18T01:00:00Z')", (f"idea:{idea_id}",))
        self.app["refresh_factory_outcomes"]()
        patterns = self.app["compute_patterns"]()
        self.assertTrue(patterns["ready"])
        self.assertEqual((patterns["total_outcomes"], patterns["owner_n"], patterns["factory_n"]),
                         (10, 1, 9))
        self.assertEqual(self.app["compute_calibration"]()["total_with_outcome"], 10)


if __name__ == "__main__":
    unittest.main()

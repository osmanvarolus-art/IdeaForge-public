"""Offline GitHub Trending intake and product analysis checks."""
import io
import json
from pathlib import Path
import sys
import unittest
from urllib.request import urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_hub_intake as fixtures

class GitHubTrendingTests(unittest.TestCase):
    def setUp(self):
        fixtures.HubIntakeTests.setUp(self)
        self.assertTrue(hasattr(self.app, "parse_github_trending"), "trending parser missing")
        self.sample = (ROOT / "tests/fixtures/github-trending-sample.html").read_bytes()

    server = fixtures.HubIntakeTests.server
    api = fixtures.HubIntakeTests.api

    def test_documented_evidence_boundary(self):
        readme = (ROOT / "README.md").read_text()
        for text in ("Probabilistic product analysis", "description is missing",
                     "Numeric demand facts come from the collector"):
            self.assertTrue(text in readme, "GitHub evidence boundary undocumented")

    def test_missing_description_keeps_repository(self):
        self.assertTrue(hasattr(self.app, "parse_github_trending"), "trending parser missing")
        html = ('<article class="Box-row"><h2><a href="/owner/project">Project</a></h2>'
                '<a href="/owner/project/stargazers">42</a><span>3 stars today</span></article>')
        repos = self.app.parse_github_trending(html)
        self.assertEqual(len(repos), 1, "description-less repository dropped")
        self.assertEqual(repos[0]["description"], "not visible")

    def test_numbers_cannot_leak_through_main_idea(self):
        self.assertTrue(hasattr(self.app, "parse_github_evaluation"), "GitHub validation missing")
        answer = {"top_idea": {"one_sentence": "Customers pay $42 monthly"},
                  "fit": {"fit_score_0_100": 55, "complexity_1_5": 2},
                  "build_recommendation": {"verdict": "PARK"},
                  "product_reverse_engineering": {
                      "problem_solved": "Helps developers review changes",
                      "who_pays_and_how": "not visible", "why_trending_now": "not visible",
                      "distribution": "GitHub", "demand_signal": "not visible",
                      "confidence": "LOW: description only",
                      "build_options": ["Build a guide.", "Build an audit tool.", "Build a report."]}}
        # A real star count must not license an invented price with the same number.
        for claim in ("Customers pay $42 monthly", "Customers pay forty dollars monthly"):
            answer["top_idea"]["one_sentence"] = claim
            with self.subTest(claim=claim), self.assertRaises(ValueError, msg="unsupported price accepted"):
                self.app.parse_github_evaluation(json.dumps(answer), "Total stars: 42")

    def test_parser_and_source_detection(self):
        self.assertTrue(hasattr(self.app, "parse_github_trending"), "trending parser missing")
        repos = self.app.parse_github_trending(self.sample.decode())
        self.assertGreaterEqual(len(repos), 20, "too few fixture repositories")
        for repo in repos:
            self.assertRegex(repo["name"], r"^[^/]+/[^/]+$")
            self.assertTrue(repo["description"], "missing description")
            self.assertIsInstance(repo["stars_today"], int)
            self.assertIsInstance(repo["total_stars"], int)
        weekly_sample = self.sample.decode().replace("stars today", "stars this week")
        with patch.object(self.app.urllib.request, "urlopen",
                          return_value=io.BytesIO(weekly_sample.encode())) as fetch:
            weekly = self.app.fetch_github_trending("weekly")
        self.assertGreaterEqual(len(weekly), 20)
        self.assertTrue(all(repo["stars_period"] == "this week" for repo in weekly))
        self.assertIn("since=weekly", fetch.call_args.args[0].full_url)
        self.assertEqual(self.app.detect_source_kind("https://github.com/Example/Project"),
                         ("github_repo", "https://github.com/example/project"))
        self.assertEqual(self.app.detect_source_kind("https://youtu.be/test")[0], "youtube")
        self.assertEqual(self.app.detect_source_kind("https://example.com/feed.xml")[0], "rss")
        pdf = self.root / "paper.pdf"
        pdf.write_bytes(b"%PDF")
        self.assertEqual(self.app.detect_source_kind(str(pdf))[0], "pdf")
        with self.app.db() as conn:
            conn.execute("INSERT INTO ideas(youtube_url, source_kind, source_path, created_at, updated_at) "
                         "VALUES('', 'text', 'https://github.com/example/project', 'now', 'now')")
        existing, added = self.app.ingest_idea("https://github.com/Example/Project",
                                                "github_repo")
        self.assertFalse(added, "cross-source repository duplicate")
        self.assertEqual(existing, 1)

    def test_default_subscription_and_repeat_scan(self):
        with self.app.db() as conn:
            rows = conn.execute("SELECT id, name, target, frequency_hours, max_items FROM subscriptions "
                                "WHERE kind='github_trending'").fetchall()
        self.assertEqual(len(rows), 1, "default subscription missing")
        sub_id, name, target, frequency, maximum = rows[0]
        self.assertEqual((name, target, frequency, maximum),
                         ("GitHub trending daily", "daily", 24, 25))
        self.app.init_db()
        with self.app.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM subscriptions "
                                          "WHERE kind='github_trending'").fetchone()[0], 1)
        with patch.object(self.app.urllib.request, "urlopen", return_value=io.BytesIO(self.sample)):
            self.app.radar_scan_subscription(sub_id)
            self.app.radar_scan_subscription(sub_id)
        with self.app.db() as conn:
            self.assertEqual(conn.execute("SELECT new_ideas FROM subscription_runs "
                                          "WHERE sub_id=? ORDER BY id", (sub_id,)).fetchall()[-1][0], 0)
            rows = conn.execute("SELECT source_path, intake_source, transcript_preview "
                                "FROM ideas WHERE source_kind='github_repo'").fetchall()
        self.assertGreaterEqual(len(rows), 20)
        self.assertTrue(all(row[1] == "github_trending" and "stars today" in row[2].lower()
                            for row in rows))
        ideas = self.api("/api/ideas")[1]["ideas"]
        self.assertTrue(all(idea["intake_source"] == "github_trending" for idea in ideas))
        with urlopen(f"http://127.0.0.1:{self.http.server_port}/", timeout=5) as response:
            page = response.read().decode()
        self.assertIn("sourceBadge(i) + esc(i.video_title", page, "source badge not rendered")

    def test_product_evaluation_marks_unseen_revenue(self):
        self.assertTrue(hasattr(self.app, "parse_github_trending"), "trending parser missing")
        repo = self.app.parse_github_trending(self.sample.decode())[0]
        idea_id, added = self.app.ingest_idea(repo["url"], "github_repo", title=repo["name"],
                                               source="github_trending",
                                               content=self.app.github_repo_text(repo))
        self.assertTrue(added)
        self.app.handle_job(self.app.JOBQ.get_nowait())  # Local evidence extraction.
        self.app.ai_backend = "openai-compatible"
        answer = {
            "top_idea": {"one_sentence": "A useful adjacent product"},
            "fit": {"fit_score_0_100": 55, "complexity_1_5": 2},
            "build_recommendation": {"verdict": "PARK"},
            "product_reverse_engineering": {
                "problem_solved": "Helps developers manage work",
                "who_pays_and_how": "Customers pay $999 monthly",
                "why_trending_now": "not visible",
                "distribution": "GitHub",
                "build_options": ["Build an audit tool.", "Build a hosted guide.", "Build a local report."],
                "demand_signal": "999999 open issues",
                "confidence": "LOW: description only",
            },
        }
        prompts = []
        def fake_model(prompt, **kwargs):
            prompts.append(prompt)
            return json.dumps(answer), 20, 30
        with patch.object(self.app, "llm_call", side_effect=fake_model), \
             patch.object(self.app, "refresh_brief_counters"):
            self.assertTrue(self.app.evaluate_job(idea_id), "repo evaluation failed")
        for heading in ("Problem solved", "Who pays and how", "Why it is trending now",
                        "How it spreads", "What we would build differently or adjacent",
                        "Demand signal", "Confidence"):
            self.assertIn(heading, prompts[0])
        with self.app.db() as conn:
            path = conn.execute("SELECT evaluation_path FROM ideas WHERE id=?", (idea_id,)).fetchone()[0]
        result = json.loads(Path(path).read_text())["product_reverse_engineering"]
        self.assertEqual(result["who_pays_and_how"], "not visible")
        self.assertIn(str(repo["stars_today"]), result["demand_signal"])
        self.assertNotIn("999999", result["demand_signal"])
        evaluation = json.loads(Path(path).read_text())
        self.assertTrue(evaluation["top_idea"]["one_sentence"].startswith(
            "Probabilistic product analysis:"), "visible analysis label missing")

    def test_github_build_uses_collected_demand_and_preserves_raw(self):
        repo = self.app.parse_github_trending(self.sample.decode())[0]
        idea_id, _ = self.app.ingest_idea(repo['url'], 'github_repo', title=repo['name'],
                                        content=self.app.github_repo_text(repo))
        self.app.handle_job(self.app.JOBQ.get_nowait())
        answer = {'top_idea': {'one_sentence': 'A useful adjacent product'},
                  'fit': {'fit_score_0_100': 85, 'complexity_1_5': 2},
                  'build_recommendation': {'verdict': 'BUILD'},
                  'product_reverse_engineering': {
                      'problem_solved': 'Helps developers', 'who_pays_and_how': 'not visible',
                      'why_trending_now': 'not visible', 'distribution': 'GitHub',
                      'demand_signal': '999999 paying customers', 'confidence': 'LOW',
                      'build_options': ['Build a guide.', 'Build an audit.', 'Build a report.']}}
        self.app.ai_backend = 'openai-compatible'
        with patch.object(self.app, 'llm_call', return_value=(json.dumps(answer), 1, 1)), \
             patch.object(self.app, 'refresh_brief_counters'):
            # Collector stars are a concrete adoption signal; model numbers are discarded.
            self.assertTrue(self.app.evaluate_job(idea_id))
            with self.app.db() as conn:
                self.assertEqual(conn.execute('SELECT eval_verdict FROM ideas WHERE id=?',
                                             (idea_id,)).fetchone()[0], 'BUILD')
                path = conn.execute('SELECT transcript_clean_path FROM ideas WHERE id=?',
                                    (idea_id,)).fetchone()[0]
            Path(path).write_text('Description: Developer utility\nNo observed demand metadata')
            self.assertTrue(self.app.evaluate_job(idea_id))
        with self.app.db() as conn:
            verdict = conn.execute('SELECT eval_verdict FROM ideas WHERE id=?', (idea_id,)).fetchone()[0]
            self.assertEqual(verdict, 'PARK', 'invented GitHub demand accepted')
            self.assertEqual(conn.execute('SELECT eval_raw_verdict FROM ideas WHERE id=?',
                                         (idea_id,)).fetchone()[0], 'BUILD')


if __name__ == "__main__":
    unittest.main()

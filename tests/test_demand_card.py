import io
import importlib.machinery
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import demand_card as module
except (ImportError, ModuleNotFoundError):
    module = None

try:
    sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda _path: None))
    _loader = importlib.machinery.SourceFileLoader(
        "ideaforge_route_fixture", str(Path(__file__).parents[1] / "ideaforge"))
    _spec = importlib.util.spec_from_loader("ideaforge_route_fixture", _loader)
    app = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(app)
except (ImportError, ModuleNotFoundError, OSError):
    app = None


class DemandCardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, "demand_card.py is missing")
        self.idea = {"video_title": "Evidence tool", "problem": "Builders need demand proof. They need a build brief."}

    def rows(self, count=3):
        return [{"platform": f"site-{i}", "url": f"https://example.com/{i}",
                 "title": f"People need tool {i}", "engagement": i + 1,
                 "fetched_at": f"2026-10-{20 + i:02d}T12:00:00+00:00"} for i in range(count)]

    def test_duplicate_url_and_title_collapse_and_non_https_drops(self):
        rows = self.rows(3)
        rows += [dict(rows[0], platform="copy", title="Different title")]
        rows += [dict(rows[1], url="https://other.example/cross", title=rows[1]["title"].upper())]
        rows += dict(rows[2], url="http://insecure.example/3"),
        card = module.build_card(self.idea, rows, "BUILD")
        self.assertEqual(len(card["sources"]), 3)
        self.assertEqual([source["url"] for source in card["sources"]],
                         ["https://example.com/0", "https://example.com/1", "https://example.com/2"])

    def test_three_sources_and_build_verdict(self):
        card = module.build_card(self.idea, self.rows(), "BUILD")
        self.assertEqual(card["verdict"], "BUILD")
        self.assertEqual(card["independent_sources"], 3)

    def test_two_sources_park_with_count_reason(self):
        card = module.build_card(self.idea, self.rows(2), "BUILD")
        self.assertEqual(card["verdict"], "PARK")
        self.assertEqual(card["reason"], "only 2 independent outside posts")

    def test_model_park_stays_park(self):
        card = module.build_card(self.idea, self.rows(3), "PARK")
        self.assertEqual(card["verdict"], "PARK")
        self.assertEqual(card["reason"], "model verdict PARK")

    def test_titles_are_stored_prefixes_cut_at_200(self):
        title = "x" * 250
        card = module.build_card(self.idea, [{"platform": "forum", "url": "https://example.com/x",
                                              "title": title, "engagement": 9,
                                              "fetched_at": "2026-10-29T00:00:00Z"}], "PARK")
        self.assertEqual(card["sources"][0]["title"], title[:200])

    def test_markdown_and_brief_contain_links_and_evidence_date(self):
        card = module.build_card(self.idea, self.rows(), "BUILD")
        markdown = module.to_markdown(card)
        brief = module.to_agent_brief(card)
        for row in card["sources"]:
            self.assertIn(row["url"], markdown)
            self.assertIn(row["url"], brief)
        self.assertIn("Demand evidence: 3 independent posts, checked 2026-10-22", brief)
        self.assertIn("They need a build brief.", brief)

    def test_card_markdown_route_reads_fixture_and_returns_404_for_unknown(self):
        self.assertIsNotNone(module, "demand_card.py is missing")
        self.assertIsNotNone(app, "ideaforge route module is missing")
        with tempfile.TemporaryDirectory() as directory:
            old_db = app.DB_PATH
            self.addCleanup(setattr, app, "DB_PATH", old_db)
            app.DB_PATH = str(Path(directory) / "fixture.sqlite")
            app.init_db()
            with app.db() as conn:
                now = "2026-10-30T12:00:00+00:00"
                cursor = conn.execute(
                    "INSERT INTO ideas (youtube_url, video_title, created_at, updated_at, eval_verdict) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("https://video.example/1", "Fixture idea", now, now, "BUILD"),
                )
                idea_id = cursor.lastrowid
                conn.execute(
                    "INSERT INTO demand (idea_id, platform, url, title, engagement, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (idea_id, "forum", "https://forum.example/post", "Stored demand title", "7", now),
                )

            def call(path):
                handler = object.__new__(app.Handler)
                handler.path = path
                handler.wfile = io.BytesIO()
                status, headers = [], []
                handler.send_response = status.append
                handler.send_header = lambda name, value: headers.append((name, value))
                handler.end_headers = lambda: None
                handler.do_GET()
                return status[0], dict(headers), handler.wfile.getvalue().decode("utf-8")

            status, headers, body = call(f"/api/card/{idea_id}.md")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "text/markdown; charset=utf-8")
            self.assertIn("https://forum.example/post", body)
            self.assertIn("Stored demand title", body)
            status, _, body = call("/api/card/999999.md")
            self.assertEqual(status, 404)
            self.assertIn("idea not found", body)


if __name__ == "__main__":
    unittest.main()

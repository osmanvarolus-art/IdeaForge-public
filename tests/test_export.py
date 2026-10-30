"""End-to-end tests for the separate IdeaForge HTTP exporter."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "ideaforge_export.py"


def ideas_fixture():
    return [
        {
            "id": 41,
            "video_title": "YouTube candidate",
            "youtube_url": "https://www.youtube.com/watch?v=video-123",
            "source_kind": "youtube",
            "source_path": "/tmp/ignored.mp4",
            "eval_fit_score": 0.82,
            "eval_one_sentence": "Strong systems engineering idea.",
            "transcript_preview": "Long transcript content.",
            "outcome": None,
            "created_at": "2026-10-03T08:00:00Z",
            "updated_at": "2026-10-03T10:00:00+02:00",
        },
        {
            "id": 42,
            "video_title": "Web source candidate",
            "youtube_url": None,
            "source_kind": "article",
            "source_path": "https://example.org/research/42",
            "eval_fit_score": "0.71",
            "eval_one_sentence": "",
            "transcript_preview": "Preview " + "x" * 240,
            "outcome": "shipped",
            "created_at": "2026-10-02T09:30:00Z",
        },
        {
            "id": 43,
            "video_title": "",
            "youtube_url": "https://youtu.be/no-title",
            "source_path": None,
        },
        {
            "id": 44,
            "video_title": "Local-only file",
            "youtube_url": None,
            "source_path": "/home/test/video.mp4",
        },
    ]


class IdeaHandler(BaseHTTPRequestHandler):
    ideas = []
    requests = []
    posts = []

    def do_GET(self):
        type(self).requests.append(self.path)
        body = json.dumps({"ideas": type(self).ideas}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        type(self).posts.append((self.path, payload))
        if not self.path.startswith("/api/outcome/"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        idea_id = self.path.rsplit("/", 1)[-1]
        for idea in type(self).ideas:
            if str(idea.get("id")) == idea_id:
                idea["outcome"] = payload.get("outcome")
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "hub-input.jsonl"
        self.hub = self.root / "fake-hub"
        self.hub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "data = sys.stdin.read()\n"
            "with open(os.environ['FAKE_HUB_CAPTURE'], 'a', encoding='utf-8') as f:\n"
            "    f.write(data)\n"
            "rows = [line for line in data.splitlines() if line.strip()]\n"
            "print(json.dumps({'written': len(rows), 'merged': 0, 'refused': []}))\n",
            encoding="utf-8",
        )
        self.hub.chmod(0o755)
        self.env = os.environ.copy()
        self.env["IDEAFORGE_HUB_BIN"] = str(self.hub)
        self.env["FAKE_HUB_CAPTURE"] = str(self.capture)
        self.env["IDEAFORGE_DECISIONS"] = str(self.root / "missing-decisions.jsonl")

    def write_decisions(self, *rows):
        path = self.root / "decisions.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        self.env["IDEAFORGE_DECISIONS"] = str(path)

    def run_export(self, base_url, timeout=20):
        env = dict(self.env, IDEAFORGE_URL=base_url)
        return subprocess.run(
            [sys.executable, "-B", str(EXPORTER)], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=timeout,
        )

    def start_server(self, ideas):
        IdeaHandler.ideas = ideas
        IdeaHandler.requests = []
        IdeaHandler.posts = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), IdeaHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        return server, f"http://127.0.0.1:{server.server_port}"

    def test_exports_only_titled_web_ideas_in_hub_contract(self):
        server, base_url = self.start_server(ideas_fixture())
        result = self.run_export(base_url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ideaforge-export: sent 2, refused 0, skipped 0 rejected")
        self.assertEqual(IdeaHandler.requests, ["/api/ideas"])

        lines = self.capture.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        rows = [json.loads(line) for line in lines]
        self.assertEqual([row["id"] for row in rows], ["youtube:video-123", "ideaforge:42"])
        self.assertEqual([row["source"] for row in rows], ["ideaforge", "ideaforge"])
        self.assertEqual([row["kind"] for row in rows], ["video", "idea"])
        self.assertEqual(rows[0]["url"], "https://www.youtube.com/watch?v=video-123")
        self.assertEqual(rows[1]["url"], "https://example.org/research/42")
        self.assertEqual(set(rows[0]["signals"]), {"fit"})
        self.assertAlmostEqual(rows[0]["signals"]["fit"], 0.0082)
        self.assertEqual(rows[1]["signals"], {"shipped": 1})
        self.assertEqual(rows[0]["seen_at"], "2026-10-03T08:00:00Z")
        self.assertEqual(rows[1]["summary"], "Preview " + "x" * 212)
        server.shutdown()

    def test_rejected_ideas_and_fit_verdict_signals(self):
        ideas = [
            {"id": 52, "video_title": "Rejected", "source_path": "https://example.org/rejected",
             "eval_verdict": "rEjEcT", "eval_fit_score": 100},
            {"id": 53, "video_title": "Build", "source_path": "https://example.org/build",
             "eval_verdict": "bUiLd", "eval_fit_score": 85},
            {"id": 54, "video_title": "No verdict", "source_path": "https://example.org/no-verdict",
             "eval_fit_score": 14},
            {"id": 55, "video_title": "Invalid fit", "source_path": "https://example.org/invalid-fit",
             "eval_fit_score": "n/a"},
        ]
        server, base_url = self.start_server(ideas)
        result = self.run_export(base_url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped 1 rejected", result.stdout)
        rows = [json.loads(line) for line in self.capture.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertNotIn("ideaforge:52", [row["id"] for row in rows])
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id["ideaforge:53"]["signals"].get("fit"), 0.85)
        self.assertEqual(by_id["ideaforge:54"]["signals"].get("fit"), 0.14)
        self.assertNotIn("fit", by_id["ideaforge:55"]["signals"])
        self.assertEqual(by_id["ideaforge:53"]["signals"].get("verdict"), 1)
        self.assertNotIn("verdict", by_id["ideaforge:54"]["signals"])
        self.assertNotIn("verdict", by_id["ideaforge:55"]["signals"])
        server.shutdown()

    def test_idea_forge_unavailable_never_calls_hub(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        result = self.run_export(f"http://127.0.0.1:{port}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("IdeaForge request failed", result.stderr)
        self.assertFalse(self.capture.exists())

    def test_exporter_does_not_import_ideaforge_program(self):
        source = EXPORTER.read_text(encoding="utf-8")
        self.assertNotIn("import ideaforge", source)

    GOAL = "goal-20261004181540-4c9e51bc59"

    def test_send_decision_writes_in_progress_with_goal_notes(self):
        ideas = [{"id": 61, "video_title": "Sendable idea", "youtube_url": None,
                  "source_path": "https://example.org/sendable", "outcome": None}]
        server, base_url = self.start_server(ideas)
        self.write_decisions({"candidate": "ideaforge:61", "action": "send",
                              "at": "2026-10-04T18:00:00Z", "goal": self.GOAL})
        result = self.run_export(base_url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(IdeaHandler.posts), 1, "send posted no outcome")
        path, body = IdeaHandler.posts[0]
        self.assertEqual(path, "/api/outcome/61")
        self.assertEqual(body.get("outcome"), "in_progress")
        self.assertEqual(body.get("notes"), f"hub send {self.GOAL}")
        server.shutdown()

    def test_dismiss_and_restore_write_nothing(self):
        ideas = [{"id": 62, "video_title": "Dismissed", "youtube_url": None,
                  "source_path": "https://example.org/dismissed", "outcome": None},
                 {"id": 63, "video_title": "Restored", "youtube_url": None,
                  "source_path": "https://example.org/restored", "outcome": None}]
        server, base_url = self.start_server(ideas)
        self.write_decisions({"candidate": "ideaforge:62", "action": "dismiss",
                              "at": "2026-10-04T18:00:00Z", "goal": self.GOAL},
                             {"candidate": "ideaforge:63", "action": "restore",
                              "at": "2026-10-04T18:00:01Z", "goal": self.GOAL})
        result = self.run_export(base_url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(IdeaHandler.posts), 0, "dismiss or restore posted")
        server.shutdown()

    def test_existing_outcome_is_left_alone(self):
        ideas = [{"id": 64, "video_title": "Shipped", "youtube_url": None,
                  "source_path": "https://example.org/shipped", "outcome": "shipped"},
                 {"id": 65, "video_title": "In progress", "youtube_url": None,
                  "source_path": "https://example.org/progress", "outcome": "in_progress"}]
        server, base_url = self.start_server(ideas)
        self.write_decisions({"candidate": "ideaforge:64", "action": "send",
                              "at": "2026-10-04T18:00:00Z", "goal": self.GOAL},
                             {"candidate": "ideaforge:65", "action": "send",
                              "at": "2026-10-04T18:00:02Z", "goal": self.GOAL})
        result = self.run_export(base_url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(IdeaHandler.posts), 0, "existing outcome overwritten")
        server.shutdown()

    def test_second_run_posts_nothing(self):
        ideas = [{"id": 66, "video_title": "Once only", "youtube_url": None,
                  "source_path": "https://example.org/once", "outcome": None}]
        server, base_url = self.start_server(ideas)
        self.write_decisions({"candidate": "ideaforge:66", "action": "send",
                              "at": "2026-10-04T18:00:00Z", "goal": self.GOAL})
        first = self.run_export(base_url)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(len(IdeaHandler.posts), 1, "send posted no outcome")
        second = self.run_export(base_url)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(IdeaHandler.posts), 1, "second run posted again")
        server.shutdown()

    def test_youtube_decision_resolves_to_idea(self):
        ideas = [{"id": 67, "video_title": "Youtube sendable",
                  "youtube_url": "https://www.youtube.com/watch?v=vid-777",
                  "source_path": None, "outcome": None}]
        server, base_url = self.start_server(ideas)
        self.write_decisions({"candidate": "youtube:vid-777", "action": "send",
                              "at": "2026-10-04T18:00:00Z", "goal": self.GOAL})
        result = self.run_export(base_url)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(IdeaHandler.posts), 1, "youtube send posted no outcome")
        path, body = IdeaHandler.posts[0]
        self.assertEqual(path, "/api/outcome/67")
        self.assertEqual(body.get("notes"), f"hub send {self.GOAL}")
        server.shutdown()


if __name__ == "__main__":
    unittest.main()

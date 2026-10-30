"""Offline NotebookLM CLI contract and per-idea summary checks."""
import json
import os
from pathlib import Path
import runpy
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


class NotebookAdapterTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.calls = self.root / "calls.jsonl"
        self.cli = self.root / "notebooklm"
        self.cli.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['FAKE_NLM_CALLS'], 'a') as log:\n"
            "    log.write(json.dumps(args) + '\\n')\n"
            "if args[:2] == ['source', 'add'] and os.environ.get('FAKE_NLM_FAIL_ADD'):\n"
            "    print('Video has no captions', file=sys.stderr); sys.exit(1)\n"
            "if args[:2] == ['source', 'wait'] and os.environ.get('FAKE_NLM_FAIL_WAIT'):\n"
            "    print('Private video', file=sys.stderr); sys.exit(1)\n"
            "if args[0] == 'create': print(json.dumps({'notebook': {'id': 'nb-fixture'}}))\n"
            "elif args[:2] == ['source', 'add']: print(json.dumps({'source': {'id': 'src-fixture'}}))\n"
            "elif args[:2] == ['source', 'wait']: print(json.dumps({'source_id': 'src-fixture', 'status': 'ready'}))\n"
            "elif args[:2] == ['source', 'guide']: print(json.dumps({'summary': 'A useful video summary.', 'keywords': ['agents', 'tests']}))\n"
            "elif args[0] == 'generate': print(json.dumps({'status': 'completed', 'artifact': {'id': 'art-fixture'}}))\n"
            "elif args[:2] == ['auth', 'check']: print(json.dumps({'authenticated': True}))\n"
            "elif args[0] == 'list': print(json.dumps([{'id': 'nb-fixture'}]))\n"
            "elif args[0] == 'download':\n"
            "    Path(args[2]).write_text('artifact')\n"
            "    print(json.dumps({'path': args[2]}))\n"
            "else: print('Unexpected command', file=sys.stderr); sys.exit(2)\n",
            encoding="utf-8",
        )
        self.cli.chmod(0o755)
        self.env = patch.dict(os.environ, {
            "IDEAFORGE_ALLOW_NO_AI": "1", "IDEAFORGE_NLM_PATH": str(self.cli),
            "FAKE_NLM_CALLS": str(self.calls), "PATH": f"{self.root}:{os.environ.get('PATH', '')}",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        with patch.dict(sys.modules, {"dotenv": types.SimpleNamespace(load_dotenv=lambda *_: None)}):
            self.app = runpy.run_path(str(ROOT / "ideaforge"), run_name="nlm_adapter_test")
        self.app["db"].__globals__["DB_PATH"] = str(self.root / "ideas.db")
        self.app["db"].__globals__["DATA_DIR"] = str(self.root / "data")
        self.app["init_db"]()
        with self.app["db"]() as conn:
            self.idea_id = conn.execute(
                "INSERT INTO ideas (youtube_url, video_title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("https://www.youtube.com/watch?v=abc123", "Test video", "2026-10-17T10:00:00Z", "2026-10-17T10:00:00Z"),
            ).lastrowid

    def commands(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def start_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.app["Handler"])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def test_push_uses_json_cli_and_shows_source_guide(self):
        self.assertEqual(self.app["NLM_PATH"], str(self.cli), "configured CLI missing")
        self.assertTrue(self.app["NLM_AVAILABLE"], "configured CLI unavailable")
        result = self.app["nlm_push_idea"](self.idea_id)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.commands(), [
            ["create", "Test video", "--json"],
            ["source", "add", "-n", "nb-fixture", "https://www.youtube.com/watch?v=abc123", "--json"],
            ["source", "wait", "src-fixture", "-n", "nb-fixture", "--timeout", "600", "--json"],
            ["source", "guide", "src-fixture", "-n", "nb-fixture", "--json"],
        ], "NotebookLM CLI argv")
        with self.app["db"]() as conn:
            summary = conn.execute("SELECT nlm_summary FROM ideas WHERE id=?", (self.idea_id,)).fetchone()[0]
        self.assertIn("A useful video summary.", summary)
        self.assertIn("agents, tests", summary)
        base = self.start_server()
        with urlopen(base + "/api/ideas") as response:
            idea = json.load(response)["ideas"][0]
        self.assertEqual(idea["nlm_summary"], summary, "API summary missing")
        with urlopen(base + "/") as response:
            page = response.read().decode()
        self.assertIn("NotebookLM summary", page, "summary absent from idea page")
        self.assertIn("nlm_summary", page, "page ignores summary data")
        self.assertFalse(any("delete" in call or "--new" in call for call in self.commands()))

    def test_failed_ingest_records_error_and_never_retries(self):
        with patch.dict(os.environ, {"FAKE_NLM_FAIL_ADD": "1"}):
            first = self.app["nlm_push_idea"](self.idea_id)
            calls = self.commands()
            second = self.app["nlm_push_idea"](self.idea_id)
        self.assertFalse(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(self.commands(), calls, "failed ingest retried")
        with self.app["db"]() as conn:
            error = conn.execute("SELECT last_error FROM ideas WHERE id=?", (self.idea_id,)).fetchone()[0]
        self.assertIn("Video has no captions", error)
        self.assertFalse(any("delete" in call or "--new" in call for call in calls))

    def test_status_and_list_use_installed_cli(self):
        self.assertTrue(self.app["nlm_check_auth"]()["authenticated"])
        self.assertEqual(self.app["nlm_list_notebooks"](), [{"id": "nb-fixture"}])
        self.assertEqual(self.commands(), [["auth", "check", "--json"], ["list", "--json"]])

    def test_failed_wait_is_recorded_and_skipped_by_batch(self):
        with patch.dict(os.environ, {"FAKE_NLM_FAIL_WAIT": "1"}):
            result = self.app["nlm_push_idea"](self.idea_id)
        self.assertFalse(result["ok"])
        self.assertIn("Private video", result["error"])
        calls = self.commands()
        with self.app["db"]() as conn:
            notebook_id = conn.execute(
                "INSERT INTO notebooks (name, created_at, updated_at) VALUES (?, ?, ?)",
                ("Retry", "2026-10-17T10:00:00Z", "2026-10-17T10:00:00Z"),
            ).lastrowid
            conn.execute("INSERT INTO idea_notebooks (idea_id, notebook_id) VALUES (?, ?)",
                         (self.idea_id, notebook_id))
        self.assertFalse(self.app["notebook_create_job"](notebook_id))
        self.assertEqual(self.commands(), calls, "failed source retried by batch")

    def test_linked_notebook_and_generation_use_new_cli(self):
        with self.app["db"]() as conn:
            notebook_id = conn.execute(
                "INSERT INTO notebooks (name, created_at, updated_at, artifact_type) VALUES (?, ?, ?, ?)",
                ("Linked videos", "2026-10-17T10:00:00Z", "2026-10-17T10:00:00Z", "audio"),
            ).lastrowid
            conn.execute("INSERT INTO idea_notebooks (idea_id, notebook_id) VALUES (?, ?)",
                         (self.idea_id, notebook_id))
        self.assertTrue(self.app["notebook_create_job"](notebook_id), "linked notebook ingest failed")
        self.assertTrue(self.app["notebook_generate_job"](notebook_id), "notebook generation failed")
        calls = self.commands()
        self.assertEqual(calls[:4], [
            ["create", "Linked videos", "--json"],
            ["source", "add", "-n", "nb-fixture", "https://www.youtube.com/watch?v=abc123", "--json"],
            ["source", "wait", "src-fixture", "-n", "nb-fixture", "--timeout", "600", "--json"],
            ["source", "guide", "src-fixture", "-n", "nb-fixture", "--json"],
        ])
        self.assertEqual(calls[4], ["generate", "audio", "-n", "nb-fixture", "--wait", "--timeout", "600", "--json"])
        self.assertEqual(calls[5][:2], ["download", "audio"])
        self.assertEqual(calls[5][3:], ["-n", "nb-fixture", "--json"])
        self.assertFalse(any("delete" in call or "--new" in call for call in calls))


if __name__ == "__main__":
    unittest.main()

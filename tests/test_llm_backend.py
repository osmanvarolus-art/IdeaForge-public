"""Exercise the relay and existing backends without credentials or external calls."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class RelayHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.reply()

    def do_POST(self):
        self.reply()

    def reply(self):
        relay = self.server
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        relay.requests.append((self.path, self.headers.get("Authorization"), payload))
        if self.path == "/v1/models":
            status, data = 200, {"data": [{"id": model} for model in relay.models]}
        elif self.path == "/v1/chat/completions":
            status, data = relay.replies.get(payload["model"], (200, {
                "choices": [{"message": {"content": relay.content}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8}}))
        else:
            status, data = 404, {}
        encoded = json.dumps(data).encode()
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "/redirected")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        pass


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = "fixture-" + os.urandom(16).hex()
        self.key_file = self.root / "credential.json"
        self.key_file.write_text(json.dumps({"apiKey": self.key}))
        self.relay = self.start_server(RelayHandler)
        self.relay.requests = []
        self.relay.models = ["second", "first"]
        self.relay.replies = {}
        self.relay.content = "answer"
        self.env = {
            "IDEAFORGE_OPENAI_BASE_URL": f"http://127.0.0.1:{self.relay.server_port}/v1",
            "IDEAFORGE_OPENAI_KEY_FILE": str(self.key_file),
            "IDEAFORGE_OPENAI_MODELS": "missing, first, second, first",
            "IDEAFORGE_ALLOW_NO_AI": "1",
            # Selection must not instantiate either paid client, even if configured.
            "GEMINI_API_KEY": "fixture-gemini", "ANTHROPIC_API_KEY": "fixture-anthropic",
        }
        self.environment = patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.genai = types.ModuleType("google.genai")
        self.genai.Client = Mock()
        google = types.ModuleType("google")
        google.genai = self.genai
        self.anthropic = types.ModuleType("anthropic")
        self.anthropic.Anthropic = Mock()
        dotenv = types.ModuleType("dotenv")
        dotenv.load_dotenv = lambda *args, **kwargs: None  # Never read a host .env.
        self.modules = patch.dict(sys.modules, {
            "dotenv": dotenv, "google": google, "google.genai": self.genai,
            "anthropic": self.anthropic,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.app = self.load_app()

    def start_server(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        return server

    def load_app(self):
        loader = importlib.machinery.SourceFileLoader("ideaforge_fixture", str(ROOT / "ideaforge"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        app = importlib.util.module_from_spec(spec)
        loader.exec_module(app)
        app.DB_PATH = str(self.root / "ideas.db")
        app.DATA_DIR = str(self.root / "data")
        return app

    def require_relay(self):
        self.assertEqual(self.app.ai_backend, "openai-compatible", "relay not selected")
        self.genai.Client.assert_not_called()
        self.anthropic.Anthropic.assert_not_called()

    def http_get(self, server, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5) as response:
            return json.load(response)

    def seed_evaluation(self):
        self.app.init_db()
        transcript = self.root / "transcript.txt"
        transcript.write_text("A local automation idea.")
        with self.app.db() as conn:
            conn.execute("INSERT INTO ideas(id, youtube_url, video_title, transcript_clean_path, created_at, updated_at) "
                         "VALUES(1, '', 'Local idea', ?, '2026-10-17', '2026-10-17')", (str(transcript),))
        return {"top_idea": {"one_sentence": 'A tool with {braces} and "quotes".'},
                "fit": {"fit_score_0_100": 63, "complexity_1_5": 2},
                "build_recommendation": {"verdict": "PARK"}}

    def test_research_planner_falls_back_after_two_non_json_responses(self):
        diagnostics = io.StringIO()
        with patch.object(self.app, "compute_patterns", return_value={}), \
                patch.object(self.app, "llm_call", side_effect=[("not JSON", 0, 0)] * 2) as call, \
                contextlib.redirect_stderr(diagnostics):
            try:
                plan = self.app.research_planner("some brief")
            except NameError as error:
                self.fail(f"planner fallback raised {error}")
        self.assertEqual(call.call_count, 2, "planner repair count changed")
        self.assertIsInstance(plan, dict)
        self.assertEqual(plan["queries"], ["some brief"])
        self.assertEqual(plan["max_per_query"], 10)
        self.assertIn("fallback plan", plan["_error"])
        self.assertEqual(len(diagnostics.getvalue().splitlines()), 2, "planner diagnostics missing")
        self.assertEqual(self.relay.requests, [], "fallback contacted relay")

    def test_research_reranker_keeps_one_failed_batch_with_default_scores(self):
        candidates = [{"title": "First", "url": "https://example.org/first"},
                      {"title": "Second", "url": "https://example.org/second"}]
        diagnostics = io.StringIO()
        with patch.object(self.app, "compute_patterns", return_value={}), \
                patch.object(self.app, "llm_call", return_value=("not JSON", 0, 0)) as call, \
                contextlib.redirect_stderr(diagnostics):
            try:
                ranked = self.app.research_rerank(candidates, {}, "some brief")
            except NameError as error:
                self.fail(f"reranker fallback raised {error}")
        self.assertEqual(call.call_count, 1, "reranker batch count changed")
        self.assertEqual([row["title"] for row in ranked], ["First", "Second"])
        self.assertEqual([row["score"] for row in ranked], [50, 50])
        self.assertTrue(all(row["reason"] == "Scoring failed - parse error" for row in ranked))
        self.assertEqual(len(diagnostics.getvalue().splitlines()), 2, "reranker diagnostics missing")
        self.assertEqual(self.relay.requests, [], "fallback contacted relay")

    def test_research_log_is_one_timestamped_stderr_line(self):
        logger = getattr(self.app, "log", None)
        self.assertTrue(callable(logger), "research logger missing")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.app, "now_iso", return_value="2026-10-18T13:09:00+02:00"), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            logger("first line\nsecond line\r\n")
        self.assertEqual(stdout.getvalue(), "", "diagnostics leaked to stdout")
        self.assertEqual(stderr.getvalue(),
                         "[ideaforge] 2026-10-18T13:09:00+02:00 first line second line\n")

    def test_reasoning_evaluation_and_instruction_input(self):
        verdict = self.seed_evaluation()
        for prefix in ("Thinking Process:\nConsider the idea.\n", "<think>Consider the idea.</think>\n",
                       '{invalid: {"nested": true}}\n```json\n', ""):
            with self.subTest(prefix=prefix), patch.object(self.app, "refresh_brief_counters"):
                self.relay.content = prefix + json.dumps(verdict) + "\n```\nDone."
                self.assertTrue(self.app.evaluate_job(1), "reasoning evaluation failed")
                with self.app.db() as conn:
                    row = conn.execute("SELECT eval_status, eval_verdict, eval_fit_score, eval_complexity, "
                                       "evaluation_path FROM ideas WHERE id=1").fetchone()
                self.assertEqual(row[:4], ("done", "PARK", 63, 2), "missing parsed verdict")
                self.assertEqual(json.loads(Path(row[4]).read_text()), verdict)
                self.assertEqual(self.relay.requests[-1][2]["max_tokens"], 4000)

        # Historical evaluation files can still contain reasoning and fences.
        Path(row[4]).write_text("<think>Old reasoning.</think>\n" + json.dumps(verdict))
        self.relay.content = "# 1. Project Definition\nBuild the local tool."
        self.assertTrue(self.app.instruct_job(1), "valid instruction rejected")
        request = self.relay.requests[-1][2]
        self.assertEqual(request["max_tokens"], 4000)
        self.assertNotIn("<think>", request["messages"][0]["content"])
        Path(row[4]).write_text("Thinking Process: no verdict")
        before = len(self.relay.requests)
        self.assertFalse(self.app.instruct_job(1), "invalid evaluation used for instruction")
        self.assertEqual(len(self.relay.requests), before)
        with self.app.db() as conn:
            self.assertEqual(conn.execute("SELECT instr_status, last_error FROM ideas").fetchone(),
                             ("failed", "evaluation had no parseable JSON verdict"))

    def test_invalid_evaluation_retries_next_model_once_then_fails(self):
        verdict = self.seed_evaluation()
        self.relay.models.append("third")
        os.environ["IDEAFORGE_OPENAI_MODELS"] = "first,second,third,first"
        for invalid in ("Thinking Process: token budget exhausted", "{}",
                        '{"build_recommendation":{"verdict":null}}',
                        '{"build_recommendation":{"verdict":"MAYBE"}}', ""):
            with self.subTest(invalid=invalid), patch.object(self.app, "refresh_brief_counters"):
                self.relay.requests.clear()
                self.relay.content = invalid
                self.assertFalse(self.app.evaluate_job(1), "invalid verdict marked done")
                self.assertEqual([r[2]["model"] for r in self.relay.requests if r[2]], ["first", "second"])
                with self.app.db() as conn:
                    self.assertEqual(conn.execute("SELECT eval_status, last_error, eval_verdict FROM ideas").fetchone(),
                                     ("failed", "evaluation had no parseable JSON verdict", None))
                    self.assertIn("eval:failed", "\n".join(conn.iterdump()))
                    self.assertNotIn("eval:done", "\n".join(conn.iterdump()))
                self.assertFalse((Path(self.app.DATA_DIR) / "1" / "evaluation.json").exists())

        self.relay.requests.clear()
        self.relay.replies["first"] = (200, {"choices": [{"message": {"content": "Thinking Process: unfinished"}}]})
        self.relay.content = "Answer:\n" + json.dumps(verdict)
        with patch.object(self.app, "refresh_brief_counters"):
            self.assertTrue(self.app.evaluate_job(1), "next model verdict rejected")
        self.assertEqual([r[2]["model"] for r in self.relay.requests if r[2]], ["first", "second"])
        self.assertEqual(self.app.MODEL, "second")
        with self.app.db() as conn:
            self.assertEqual(conn.execute("SELECT eval_status, eval_verdict, last_error FROM ideas").fetchone(),
                             ("done", "PARK", None))
        self.require_relay()

    def test_existing_backend_job_budgets_and_invalid_verdict(self):
        verdict = self.seed_evaluation()
        for backend in ("gemini", "anthropic"):
            with self.subTest(backend=backend), patch.object(self.app, "ai_backend", backend), \
                    patch.object(self.app, "refresh_brief_counters"), \
                    patch.object(self.app, "llm_call", return_value=(json.dumps(verdict), 1, 2)) as call:
                self.assertTrue(self.app.evaluate_job(1))
                self.assertEqual(call.call_args.kwargs["max_tokens"], 1400)
                call.return_value = ("# Instructions", 1, 2)
                self.assertTrue(self.app.instruct_job(1))
                self.assertEqual(call.call_args.kwargs["max_tokens"], 1800)
                call.return_value = ("No JSON", 1, 2)
                self.assertFalse(self.app.evaluate_job(1), "legacy invalid verdict accepted")
                with self.app.db() as conn:
                    self.assertEqual(conn.execute("SELECT eval_status, last_error FROM ideas").fetchone(),
                                     ("failed", "evaluation had no parseable JSON verdict"))
        self.assertEqual(self.relay.requests, [])

    def test_founder_profile_and_domain_keywords_exclude_salaried_work(self):
        profile = json.dumps(self.app.EVAL_PROFILE).lower()
        for word in ("restaurant", "procurement", "invoice"):
            self.assertNotIn(word, profile, "salaried work in founder profile")
        self.assertIn("agent tooling; local automation", profile)
        self.app.init_db()
        with self.app.db() as conn:
            for i in range(5):
                conn.execute("INSERT INTO ideas(youtube_url, video_title, eval_verdict, eval_fit_score, "
                             "created_at, updated_at) VALUES('', ?, 'PARK', 50, '2026-10-17', '2026-10-17')",
                             ("Restaurant invoice procurement automation",))
        domains = self.app.compute_per_domain_thresholds()
        self.assertEqual([d["domain"] for d in domains["domains"]], ["automation"], "salaried keyword retained")

    def test_preference_error_fallback_and_key_rotation(self):
        self.require_relay()
        self.assertEqual(self.app.llm_call("hello", 31, 0.7), ("answer", 12, 8))
        first = self.relay.requests[-1][2]
        self.assertEqual(first, {"model": "first", "messages": [{"role": "user", "content": "hello"}],
                                 "max_tokens": 31, "temperature": 0.7})
        self.assertTrue(all(row[1] == "Bearer " + self.key for row in self.relay.requests), "bad bearer")
        self.relay.requests.clear()
        rotated = self.key + "-rotated"
        self.key_file.write_text(json.dumps({"apiKey": rotated}))
        self.relay.replies["first"] = (500, {"error": rotated})
        self.assertEqual(self.app.llm_call("again"), ("answer", 12, 8))
        self.assertEqual([row[2]["model"] for row in self.relay.requests if row[2]], ["first", "second"])
        self.assertTrue(all(row[1] == "Bearer " + rotated for row in self.relay.requests), "stale bearer")
        self.assertEqual(self.app.MODEL, "second")
        self.require_relay()

    def test_timeout_uses_120_seconds_and_next_model(self):
        self.require_relay()
        real_open = urllib.request.OpenerDirector.open
        seen_timeouts = []

        def timed_open(opener, request, *args, **kwargs):
            seen_timeouts.append(kwargs.get("timeout"))
            if request.data and json.loads(request.data)["model"] == "first":
                raise TimeoutError("upstream error containing " + self.key)
            return real_open(opener, request, *args, **kwargs)

        with patch.object(urllib.request.OpenerDirector, "open", timed_open):
            self.assertEqual(self.app.llm_call("hello"), ("answer", 12, 8))
        self.assertEqual(seen_timeouts, [120, 120, 120])
        self.assertEqual(self.app.MODEL, "second")

    def test_jobs_preflight_events_and_errors_do_not_leak_key(self):
        self.require_relay()
        self.app.init_db()
        transcript = self.root / "transcript.txt"
        transcript.write_text("A local project idea.")
        with self.app.db() as conn:
            conn.execute("INSERT INTO ideas(id, youtube_url, video_title, transcript_clean_path, created_at, updated_at) "
                         "VALUES(1, '', 'Local idea', ?, '2026-10-17', '2026-10-17')", (str(transcript),))
        server = self.start_server(self.app.Handler)
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture), \
                patch.object(self.app.subprocess, "call", return_value=0):
            preflight = self.http_get(server, "/api/preflight")
            self.assertTrue(preflight["ai_enabled"])
            self.assertEqual((preflight["ai_backend"], preflight["model"]), ("openai-compatible", "first"))
            self.relay.content = json.dumps({"top_idea": {"one_sentence": self.key},
                "fit": {"fit_score_0_100": 63}, "build_recommendation": {"verdict": "PARK"}})
            self.assertTrue(self.app.evaluate_job(1), "evaluation failed")
            self.relay.content = "# Build instructions\n" + self.key
            self.assertTrue(self.app.instruct_job(1), "instruction failed")
            with self.app.db() as conn:
                self.assertEqual(conn.execute("SELECT eval_status, instr_status, eval_fit_score FROM ideas").fetchone(),
                                 ("done", "done", 63))
            for model in self.relay.models:
                self.relay.replies[model] = (500, {"error": self.key})
            self.assertFalse(self.app.evaluate_job(1), "failure ignored")
            self.assertFalse(self.app.instruct_job(1), "failure ignored")
            responses = [preflight, self.http_get(server, "/api/events/1"), self.http_get(server, "/api/ideas")]
        self.assertFalse(self.key in capture.getvalue() + json.dumps(responses), "credential leaked")
        with self.app.db() as conn:
            dump = "\n".join(conn.iterdump())
        self.assertFalse(self.key in dump, "credential in database")
        for path in self.root.rglob("*"):
            if path.is_file() and path != self.key_file:
                self.assertFalse(self.key.encode() in path.read_bytes(), "credential in output file")
        self.require_relay()

    def test_invalid_configuration_and_redirect_never_use_paid_clients(self):
        self.require_relay()
        self.relay.replies = {model: (302, {}) for model in self.relay.models}
        with self.assertRaisesRegex(RuntimeError, "OpenAI-compatible models failed"):
            self.app.llm_call("redirect")
        self.assertNotIn("/redirected", [row[0] for row in self.relay.requests])
        for configuration in ({"IDEAFORGE_OPENAI_MODELS": "unknown"},
                              {"IDEAFORGE_OPENAI_KEY_FILE": str(self.root / "missing")},
                              {"IDEAFORGE_OPENAI_BASE_URL": ""}):
            with self.subTest(configuration=configuration), patch.dict(os.environ, configuration):
                self.app = self.load_app()
                self.require_relay()
                with self.assertRaisesRegex(RuntimeError, "OpenAI-compatible models unavailable"):
                    self.app.llm_call("invalid")
                self.assertIsNone(self.app.MODEL)

    def test_unset_relay_preserves_existing_backends(self):
        del os.environ["IDEAFORGE_OPENAI_BASE_URL"]
        app = self.load_app()
        self.assertEqual(app.ai_backend, "gemini")
        self.genai.Client.return_value.models.generate_content.return_value = types.SimpleNamespace(
            text="gemini answer", usage_metadata=types.SimpleNamespace(prompt_token_count=4, candidates_token_count=5))
        self.assertEqual(app.llm_call("hello"), ("gemini answer", 4, 5))
        del os.environ["GEMINI_API_KEY"]
        app = self.load_app()
        self.assertEqual(app.ai_backend, "anthropic")
        self.anthropic.Anthropic.return_value.messages.create.return_value = types.SimpleNamespace(
            content=[types.SimpleNamespace(text="anthropic answer")],
            usage=types.SimpleNamespace(input_tokens=6, output_tokens=7))
        self.assertEqual(app.llm_call("hello"), ("anthropic answer", 6, 7))
        del os.environ["ANTHROPIC_API_KEY"]
        app = self.load_app()
        self.assertIsNone(app.ai_backend)
        with self.assertRaisesRegex(RuntimeError, "No AI backend configured"):
            app.llm_call("hello")
        self.assertEqual(self.relay.requests, [])

    def test_grounded_search_routes_through_shared_call(self):
        del os.environ["IDEAFORGE_OPENAI_BASE_URL"]
        app = self.load_app()

        def completion(prompt, **kwargs):
            kwargs["grounding_urls"]["https://example.org/source"] = "Source"
            return "[]", 1, 2

        with patch.object(app, "llm_call", side_effect=completion) as shared:
            result = app.web_search_grounded("query")
        self.assertEqual(shared.call_count, 1, "grounding bypassed llm_call")
        self.genai.Client.return_value.models.generate_content.assert_not_called()
        self.assertEqual(result[0]["url"], "https://example.org/source")
        self.assertEqual(result[0]["title"], "Source")


if __name__ == "__main__":
    unittest.main()

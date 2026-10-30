"""Request guard, local-file allowlist and CLI option terminator. Each test fails on the code before the fix."""
import http.client
import json
from pathlib import Path
import subprocess
import sys
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import test_hub_intake as fixtures
import demand_probe


class RequestGuardTests(unittest.TestCase):
    setUp = fixtures.HubIntakeTests.setUp
    server = fixtures.HubIntakeTests.server
    api = fixtures.HubIntakeTests.api

    def raw(self, method, path, body=None, **headers):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=5)
        conn.putrequest(method, path, skip_host='Host' in headers)
        for name, value in headers.items():
            conn.putheader(name, value)
        data = json.dumps(body).encode() if body is not None else b''
        if method == 'POST':
            conn.putheader('Content-Length', str(len(data)))
        conn.endheaders(data)
        status = conn.getresponse().status
        conn.close()
        return status

    def test_foreign_host_is_refused(self):                      # DNS rebinding
        for method, body in (('GET', None), ('POST', {'url': 'https://youtu.be/rebind'})):
            self.assertEqual(self.raw(method, '/api/ingest', body, Host='evil.example:80', **{'Content-Type': 'application/json'}), 403)

    def test_foreign_origin_is_refused(self):                    # CSRF from a web page
        self.assertEqual(self.raw('POST', '/api/ingest', {'url': 'https://youtu.be/csrf'}, Origin='http://evil.example',
                                  **{'Content-Type': 'application/json'}), 403)

    def test_simple_form_post_is_refused(self):                  # text/plain needs no CORS preflight
        self.assertEqual(self.raw('POST', '/api/ingest', {'url': 'https://youtu.be/plain'}, **{'Content-Type': 'text/plain'}), 403)

    def test_own_json_request_still_works(self):
        status, result = self.api('/api/ingest', {'url': 'https://youtu.be/guard-ok'})
        self.assertEqual((status, result['ok']), (200, True))

    def test_local_file_outside_inbox_is_refused(self):
        secret = self.root / 'secret.txt'
        secret.write_text('private')
        status, result = self.api('/api/ingest', {'url': str(secret)})
        self.assertEqual(status, 403, result)


class OptionTerminatorTests(unittest.TestCase):
    def test_query_cannot_become_an_option(self):
        seen = []
        def runner(argv, **kwargs):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, '[]')
        demand_probe.probe('--config=/tmp/x', runner=runner)
        for argv in seen:
            self.assertEqual(argv[-2:], ['--', '--config=/tmp/x'], argv)


if __name__ == '__main__':
    unittest.main()


class WorkerRecheckTests(unittest.TestCase):
    setUp = fixtures.HubIntakeTests.setUp
    server = fixtures.HubIntakeTests.server

    def test_worker_refuses_file_swapped_to_outside_after_accept(self):
        inbox = self.root / 'inbox'
        inbox.mkdir()
        secret = self.root / 'secret.txt'
        secret.write_text('private data')
        link = inbox / 'note.txt'
        link.symlink_to(secret)                                   # accepted as inbox file, now points outside
        with unittest.mock.patch.dict('os.environ', {'IDEAFORGE_INBOX': str(inbox)}):
            idea_id, _ = self.app.ingest_idea(str(link), 'text')
            self.app.extract_text_job(idea_id, str(link))
            with self.app.db() as conn:
                preview = conn.execute("SELECT transcript_preview FROM ideas WHERE id=?", (idea_id,)).fetchone()[0]
        self.assertNotIn('private data', preview or '')

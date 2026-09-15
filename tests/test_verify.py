import argparse
import contextlib
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import nebius_verify as verify

BASE = "https://api.sprites.dev/v1/gateway/custom_api/test-connection"


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200, content_type="application/json"):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Type": content_type}


def json_response(value, status=200):
    return Response(json.dumps(value).encode(), status)


def models():
    return json_response({"data": [{"id": "test-model"}]})


class FakeClient:
    timeout = 30.0

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def events(*values):
    return b"".join(b"data: " + (value.encode() if isinstance(value, str)
                                else json.dumps(value).encode()) + b"\n\n"
                    for value in values)


def chat_delta(text):
    return {"choices": [{"delta": {"content": text}, "finish_reason": None}]}


CHAT_STOP = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
RESPONSES_DONE = {"type": "response.completed", "response": {"status": "completed"}}


class TimedResponse(Response):
    """Advance a fake clock as each fully framed event is delivered."""

    def __init__(self, schedule):
        super().__init__(content_type="text/event-stream")
        self.lines = iter((when, line) for when, value in schedule
                          for line in events(value).splitlines(keepends=True))
        self.now = 0.0

    def readline(self, limit=-1):
        item = next(self.lines, None)
        if item is None:
            return b""
        self.now, line = item
        return line


class GatewayTests(unittest.TestCase):
    def test_url_validation(self):
        self.assertEqual(verify.gateway_url(BASE + "/"), BASE)
        for value in ("http://api.sprites.dev/v1/gateway/custom_api/x", BASE + "/v1",
                      BASE + "?key=secret", BASE + "#fragment", BASE + "/../x",
                      BASE.replace("custom_api", "nebius"), BASE + "\n",
                      BASE.replace("api.sprites.dev", "api.sprites.dev.evil.test"),
                      BASE.replace("https://", "https://user:password@")):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                verify.gateway_url(value)

    def test_discovery_filters_and_sanitizes_records(self):
        row = {"provider": "custom_api", "base_api_url": verify.NEBIUS_URL,
               "gateway_base_url": BASE, "new_sensitive_field": "must-not-print"}
        client = FakeClient(json_response({"connections": [
            row, {**row, "base_api_url": "https://example.test/v1"},
            {**row, "provider": "other"}, {**row, "base_api_url": None}, None]}))
        results = verify.discover(client)
        self.assertEqual(results[0]["connections"], [{"gateway_url": BASE}])
        self.assertNotIn("must-not-print", json.dumps(results))
        self.assertEqual(client.calls, [(verify.DISCOVERY_URL, {})])

    def test_discovery_requires_a_match(self):
        self.assertEqual(verify.discover(FakeClient(json_response({"connections": []})))[0]
                         ["status"], "fail")

    def test_discovery_rejects_untrusted_gateway_url(self):
        client = FakeClient(json_response({"connections": [{"provider": "custom_api",
            "base_api_url": verify.NEBIUS_URL, "gateway_base_url": "https://evil.test"}]}))
        with self.assertRaises(verify.ProbeError):
            verify.discover(client)
        with self.assertRaises(argparse.ArgumentTypeError):
            verify.gateway_url(None)

    def test_access_is_get_only_and_checks_baseline_first(self):
        client = FakeClient(models(), models(), Response(status=403),
                            Response(status=403), Response(status=403))
        results = verify.access(client, BASE, "allowed")
        self.assertTrue(all(row["status"] == "pass" for row in results))
        self.assertEqual(len(client.calls), 5)
        self.assertEqual(client.calls[0], (BASE + "/models", {}))
        self.assertEqual(client.calls[1][1], {"bearer": verify.INVALID_BEARER})
        self.assertTrue(all(call[1].get("method", "GET") == "GET" for call in client.calls))

    def test_failed_baseline_stops_comparison(self):
        client = FakeClient(Response(b"private error", status=401))
        with self.assertRaisesRegex(verify.ProbeError, "received 401") as raised:
            verify.access(client, BASE, "allowed")
        self.assertNotIn("private error", str(raised.exception))
        self.assertEqual(len(client.calls), 1)

    def test_wrong_block_status_fails(self):
        client = FakeClient(models(), models(), Response(status=200),
                            Response(status=404), Response(status=403))
        self.assertEqual([row["status"] for row in verify.access(client, BASE, "allowed")],
                         ["pass", "pass", "fail", "fail", "pass"])

    def test_negative_identity_probes_are_separate(self):
        for context, status, check in (("outside", 401, "V2"), ("unlabeled", 403, "V3")):
            with self.subTest(context=context):
                client = FakeClient(Response(status=status))
                result = verify.access(client, BASE, context)[0]
                self.assertEqual((result["check"], result["status"]), (check, "pass"))
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(verify.access(FakeClient(Response()), BASE, context)[0]
                                 ["status"], "fail")

    def test_bad_model_lists_do_not_count_as_success(self):
        for body in (None, [], {}, {"data": []}, {"data": [None]}, {"data": [{"id": ""}]}):
            with self.subTest(body=body), self.assertRaises(verify.ProbeError):
                verify.model_ids(json_response(body))
        with self.assertRaises(verify.ProbeError):
            verify.model_ids(Response(b"not json"))

    def test_json_size_bound(self):
        with self.assertRaisesRegex(verify.ProbeError, "size limit"):
            verify.read_json(Response(b" " * (verify.MAX_BODY + 1)))


class StreamTests(unittest.TestCase):
    def inspect(self, response, api="chat"):
        return verify.inspect_stream(response, api, clock=lambda: response.now)

    def test_incremental_chat_completion_and_usage(self):
        response = TimedResponse([(0.1, chat_delta("one")), (0.4, chat_delta("two")),
            (0.5, CHAT_STOP), (0.5, {"choices": [], "usage": {"prompt_tokens": 9,
            "completion_tokens": 4, "unexpected_secret": "hidden"}}), (0.5, "[DONE]")])
        result = self.inspect(response)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["first_to_last_delta_ms"], 300)
        self.assertEqual(result["usage"], {"prompt_tokens": 9, "completion_tokens": 4})
        self.assertNotIn("hidden", json.dumps(result))

    def test_incremental_responses(self):
        response = TimedResponse([
            (0.1, {"type": "response.output_text.delta", "delta": "one"}),
            (0.3, {"type": "response.output_text.delta", "delta": "two"}),
            (0.4, {"type": "response.completed", "response": {"status": "completed",
                  "usage": {"input_tokens": 8, "output_tokens": 4}}})])
        result = self.inspect(response, "responses")
        self.assertTrue(result["incremental_delivery_observed"])
        self.assertEqual(result["usage"], {"input_tokens": 8, "output_tokens": 4})

    def test_buffered_valid_stream_is_inconclusive_not_protocol_failure(self):
        response = TimedResponse([(2, chat_delta("one")), (2, chat_delta("two")),
                                  (2, CHAT_STOP), (2, "[DONE]")])
        result = self.inspect(response)
        self.assertEqual(result["protocol"], "pass")
        self.assertEqual(result["status"], "inconclusive")

    def test_single_delta_does_not_prove_incremental_delivery(self):
        response = TimedResponse([(0.1, chat_delta("whole output")),
                                  (2, CHAT_STOP), (2, "[DONE]")])
        self.assertEqual(self.inspect(response)["status"], "inconclusive")

    def test_errors_and_truncation_fail_without_echoing_content(self):
        bad_events = [
            {"error": {"message": "private-upstream-error"}},
            {"type": "error", "message": "private-upstream-error"},
            {"type": "response.failed"}, {"type": "response.incomplete"},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
        ]
        for event in bad_events:
            with self.subTest(event=event), self.assertRaises(verify.ProbeError) as raised:
                self.inspect(TimedResponse([(0.1, chat_delta("x")), (0.2, event)]))
            self.assertNotIn("private-upstream-error", str(raised.exception))

    def test_incomplete_streams_fail(self):
        for values in ([chat_delta("x")], [CHAT_STOP, "[DONE]"], [chat_delta("x"), "[DONE]"]):
            with self.subTest(values=values), self.assertRaises(verify.ProbeError):
                self.inspect(TimedResponse([(0.1, value) for value in values]))
        with self.assertRaises(verify.ProbeError):
            self.inspect(TimedResponse([(0.1, {"type": "response.completed"})]), "responses")

    def test_sse_multiline_bom_comments_and_crlf(self):
        response = Response(b'\xef\xbb\xbf: ping\r\nevent: message\r\ndata: {"a":\r\n'
                            b'data: 1}\r\n\r\n')
        result = list(verify.sse_data(response))
        self.assertEqual(json.loads(result[0][1]), {"a": 1})

    def test_malformed_frames_and_size_limits(self):
        for body in (b"data: unfinished", b"data: \xff\n\n",
                     b"data: " + b"a" * verify.MAX_LINE):
            with self.subTest(body_length=len(body)), self.assertRaises(verify.ProbeError):
                list(verify.sse_data(Response(body)))
        for value in ("not JSON", [], {"choices": "bad"}, {"choices": [None]}):
            with self.subTest(value=value), self.assertRaises(verify.ProbeError):
                self.inspect(TimedResponse([(0.1, value)]))

    def test_socket_and_total_limits_are_bounded(self):
        response = TimedResponse([(121, chat_delta("late"))])
        with self.assertRaisesRegex(verify.ProbeError, "duration limit"):
            self.inspect(response)
        with patch.object(verify, "MAX_BODY", 12), self.assertRaises(verify.ProbeError):
            list(verify.sse_data(Response(events({"long": "message"}))))

    def test_http_errors_and_non_sse_are_rejected(self):
        for response in (Response(b"private", status=500), Response(b"{}")):
            with self.assertRaises(verify.ProbeError) as raised:
                verify.inspect_stream(response, "chat")
            self.assertNotIn("private", str(raised.exception))


class SafetyTests(unittest.TestCase):
    def test_paid_requests_require_opt_in_before_client_creation(self):
        with patch.object(verify, "Client") as client, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                verify.main(["inference", "--gateway-url", BASE, "--model", "test-model"])
        self.assertEqual(raised.exception.code, 2)
        client.assert_not_called()

    def test_two_paid_calls_and_no_retry_with_placeholder_only(self):
        client = FakeClient(models(), Response(status=429), Response(status=500))
        results = verify.inference(client, BASE, "test-model", 256)
        self.assertEqual([row["status"] for row in results], ["fail", "fail"])
        self.assertEqual(len(client.calls), 3)
        for url, options in client.calls[1:]:
            self.assertTrue(url.startswith(BASE + "/"))
            self.assertEqual(options["method"], "POST")
            self.assertEqual(options["bearer"], verify.PLACEHOLDER)
            self.assertTrue(options["payload"]["stream"])
        self.assertEqual(client.calls[1][1]["payload"]["max_tokens"], 256)
        self.assertEqual(client.calls[2][1]["payload"]["max_output_tokens"], 256)
        self.assertFalse(client.calls[2][1]["payload"]["store"])

    def test_unknown_model_does_not_generate(self):
        client = FakeClient(models())
        with self.assertRaises(verify.ProbeError):
            verify.inference(client, BASE, "unknown", 256)
        self.assertEqual(len(client.calls), 1)

    def test_timeout_and_token_caps(self):
        for value in ("0", "-1", "121", "inf", "nan", "not-number"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                verify.positive_timeout(value)
        for value in ("0", "-1", "16385", "1.5"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                verify.token_limit(value)

    def test_client_does_not_follow_redirects(self):
        self.assertIsNone(verify.NoRedirect().redirect_request(None, None, 302, "", {},
                                                              "https://evil.test"))

    def test_inference_accepts_gateway_json_negotiation_but_requires_sse(self):
        client = verify.Client()
        with patch.object(client.opener, "open", return_value=Response()) as opener:
            with client.request(BASE + "/chat/completions", method="POST",
                                bearer=verify.PLACEHOLDER,
                                payload={"stream": True, "max_tokens": 256}) as response:
                request = opener.call_args.args[0]
                self.assertEqual(request.get_header("Accept"),
                                 "text/event-stream, application/json")
                self.assertEqual(request.get_header("Content-type"), "application/json")
                self.assertTrue(json.loads(request.data)["stream"])
                with self.assertRaisesRegex(verify.ProbeError, "Expected text/event-stream"):
                    verify.inspect_stream(response, "chat")

    def test_client_does_not_inherit_environment_credentials(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "not-for-the-client",
                                       "NEBIUS_API_KEY": "also-not-for-the-client"}):
            client = verify.Client()
            with patch.object(client.opener, "open", return_value=Response()) as opener:
                client.request(BASE + "/models")
                request = opener.call_args.args[0]
                self.assertIsNone(request.get_header("Authorization"))
                client.request(BASE + "/models", bearer=verify.INVALID_BEARER)
                self.assertEqual(opener.call_args.args[0].get_header("Authorization"),
                                 "Bearer " + verify.INVALID_BEARER)

    def test_transport_failures_are_sanitized_and_http_errors_not_followed(self):
        client = verify.Client()
        with patch.object(client.opener, "open", side_effect=URLError("private details")):
            with self.assertRaises(verify.ProbeError) as raised:
                client.request(BASE)
        self.assertNotIn("private details", str(raised.exception))
        error = HTTPError(BASE, 302, "redirect", {}, io.BytesIO(b"private"))
        with patch.object(client.opener, "open", side_effect=error):
            with client.request(BASE) as response:
                self.assertEqual(response.status, 302)

    def test_cli_never_claims_complete_spec_success(self):
        client = FakeClient(Response(status=401))
        out = io.StringIO()
        with patch.object(verify, "Client", return_value=client), contextlib.redirect_stdout(out):
            code = verify.main(["access", "--gateway-url", BASE, "--expect", "outside"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out.getvalue())["full_spec_verified"])

    def test_partial_http_body_is_sanitized(self):
        response = Response()
        with patch.object(response, "read", side_effect=IncompleteRead(b"private")), \
             patch.object(verify, "Client", return_value=FakeClient(response)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = verify.main(["access", "--gateway-url", BASE, "--expect", "allowed"])
        self.assertEqual(code, 1)
        self.assertNotIn("private", output.getvalue())
        self.assertIn("Transport failed", output.getvalue())


class LoopbackHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Reproduce the gateway's JSON Accept requirement before serving SSE.
        if "application/json" not in self.headers.get("Accept", ""):
            self.send_response(406)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.server.payloads.append(json.loads(self.rfile.read(
            int(self.headers.get("Content-Length", "0")))))
        self.do_GET()

    def do_GET(self):
        self.server.paths.append(self.path)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/must-not-follow")
            self.end_headers()
            return
        first = events(chat_delta("one"))
        last = events(chat_delta("two"), CHAT_STOP, "[DONE]")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(first) + len(last)))
        self.end_headers()
        self.wfile.write(first)
        self.wfile.flush()
        time.sleep(0.15)
        self.wfile.write(last)
        self.wfile.flush()

    def log_message(self, *args):
        pass


class LoopbackTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackHandler)
        self.server.paths = []
        self.server.payloads = []
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_real_http_client_observes_delayed_events(self):
        with verify.Client().request(self.url + "/stream") as response:
            result = verify.inspect_stream(response, "chat")
        self.assertEqual(result["status"], "pass")
        self.assertGreaterEqual(result["first_to_last_delta_ms"], 100)

    def test_real_redirect_is_not_followed(self):
        with verify.Client().request(self.url + "/redirect") as response:
            self.assertEqual(response.status, 302)
        self.assertEqual(self.server.paths, ["/redirect"])

    def test_real_stream_post_passes_gateway_accept_negotiation(self):
        payload = {"stream": True, "max_tokens": 256}
        with verify.Client().request(self.url + "/stream", method="POST",
                                     payload=payload) as response:
            result = verify.inspect_stream(response, "chat")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(self.server.payloads, [payload])


if __name__ == "__main__":
    unittest.main()

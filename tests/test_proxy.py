"""Offline adapter tests; every outgoing request uses an in-memory transport."""

import asyncio
import contextlib
import io
import json
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import httpx
    from proxy import server
    from proxy.vendor.conversion import ConversionError, request_to_openai
except ImportError:
    httpx = server = None

BASE = "https://api.sprites.dev/v1/gateway/custom_api/offline-test"
KEY = "sprites-nebius-placeholder-not-a-secret"
SETTINGS = {"OPENAI_BASE_URL": BASE, "OPENAI_API_KEY": KEY, "ANTHROPIC_API_KEY": KEY,
            "BIG_MODEL": "provider/big", "MIDDLE_MODEL": "provider/middle", "SMALL_MODEL": "provider/small"}
TOOLS = [{"name": "Read", "input_schema": {"type": "object"}}]


def request_body(**extra):
    return {"model": "claude-sonnet-4", "max_tokens": 16384, "messages": [{"role": "user", "content": "hello"}], **extra}


def frame(data):
    return b"data: " + (data.encode() if isinstance(data, str) else json.dumps(data).encode()) + b"\n\n"


def choice(delta=None, finish=None):
    return {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}


def events(parts):
    return [json.loads(part.split("data: ", 1)[1]) for part in parts]


if httpx:
    class FakeStream(httpx.AsyncByteStream):
        def __init__(self, parts, stall=False):
            self.parts = parts
            self.stall = stall
            self.closed = False
            self.waiting = asyncio.Event()

        async def __aiter__(self):
            for part in self.parts:
                yield part
            if self.stall:
                self.waiting.set()
                await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True


@unittest.skipIf(server is None, "Install proxy/requirements.txt to run proxy proofs")
class ConfigTests(unittest.TestCase):
    def test_pinned_license_manifest(self):
        vendor = Path(__file__).resolve().parents[1] / "proxy/vendor"
        source = json.loads((vendor / "SOURCE.json").read_text())
        self.assertEqual(source["commit"], "7ea4177a54a5ff7969a5f8ec76d9f80f2e0409e5")
        self.assertIn("Copyright (c) 2024 fuergaosi233", (vendor / "LICENSE").read_text())

    def test_safe_settings_and_model_aliases(self):
        settings = server.Settings.load(SETTINGS)
        self.assertEqual(settings.model("claude-sonnet-4"), "provider/middle")
        self.assertEqual(settings.model("haiku"), "provider/small")
        self.assertEqual(settings.model("provider/big"), "provider/big")
        with self.assertRaises(ConversionError):
            settings.model("gpt-another-model")

    def test_reject_unsafe_config(self):
        bad = [
            {"HOST": "0.0.0.0"}, {"PORT": "8082"}, {"OPENAI_API_KEY": "real-provider-key"},
            {"ANTHROPIC_API_KEY": "real-provider-key"}, {"CUSTOM_HEADER_AUTHORIZATION": "anything"},
            {"OPENAI_BASE_URL": "https://api.openai.com/v1"},
            {"OPENAI_BASE_URL": BASE + "?token=secret"}, {"OPENAI_BASE_URL": BASE + "/../bad"},
            {"OPENAI_BASE_URL": BASE + "#fragment"}, {"OPENAI_BASE_URL": "https://user@api.sprites.dev/v1/gateway/custom_api/x"},
            {"MAX_TOKENS_LIMIT": "4096"}, {"REQUEST_TIMEOUT": "nan"}, {"REQUEST_TIMEOUT": "121"},
        ]
        for update in bad:
            with self.subTest(update=list(update)):
                with self.assertRaises(ValueError):
                    server.Settings.load({**SETTINGS, **update})

    def test_mixed_tool_result_text_preserved_and_next_turn(self):
        history = [
            {"role": "user", "content": "read"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "one", "name": "Read", "input": {"path": "x"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "one", "content": "pass"}, {"type": "text", "text": "Now edit"}]},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "two", "name": "Edit", "input": {"path": "x"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "two", "content": [{"type": "text", "text": "done"}]}]},
        ]
        converted = request_to_openai(request_body(messages=history), "model", 16384)
        self.assertEqual([m["role"] for m in converted["messages"]], ["user", "assistant", "tool", "user", "assistant", "tool"])
        self.assertEqual(converted["messages"][3]["content"], "Now edit")
        self.assertEqual(converted["messages"][-1]["tool_call_id"], "two")
        self.assertEqual(converted["max_tokens"], 16384)

    def test_tool_choices_and_search_refusal(self):
        tool = {"name": "Read", "input_schema": {"type": "object"}}
        for original, mapped in (("any", "required"), ("none", "none"), ("auto", "auto")):
            result = request_to_openai(request_body(tools=[tool], tool_choice={"type": original}), "model", 16384)
            self.assertEqual(result["tool_choice"], mapped)
        named = request_to_openai(request_body(tools=[tool], tool_choice={"type": "tool", "name": "Read"}), "model", 16384)
        self.assertEqual(named["tool_choice"]["function"]["name"], "Read")
        with self.assertRaises(ConversionError):
            request_to_openai(request_body(tools=[{"type": "web_search_20250305", "name": "web_search"}]), "model", 16384)

    def test_parallel_tool_choice_is_preserved_and_validated(self):
        tool = {"name": "Read", "input_schema": {"type": "object"}}
        for kind in ("auto", "any", "none", "tool"):
            for disabled in (True, False):
                choice = {"type": kind, "name": "Read", "disable_parallel_tool_use": disabled}
                result = request_to_openai(request_body(tools=[tool], tool_choice=choice), "model", 16384)
                self.assertIs(result["parallel_tool_calls"], not disabled)
        for invalid in (None, 0, 1, "true", []):
            with self.subTest(invalid=invalid), self.assertRaises(ConversionError):
                request_to_openai(request_body(tool_choice={"type": "auto", "disable_parallel_tool_use": invalid}), "model", 16384)

    def test_consecutive_system_messages_use_linear_lookaround(self):
        class CountedMessage(dict):
            reads = 0
            def get(self, *args):
                CountedMessage.reads += 1
                return super().get(*args)
        count = 128
        history = [CountedMessage(role="user", content="task")]
        history += [CountedMessage(role="system", content="reminder", clear_at="next_user_message") for _ in range(count)]
        history += [CountedMessage(role="assistant", content="done"), CountedMessage(role="user", content="next")]
        converted = request_to_openai(request_body(messages=history), "model", 16384)
        self.assertEqual([m["role"] for m in converted["messages"]], ["user", "assistant", "user"])
        self.assertLess(CountedMessage.reads, 12 * len(history))

    def test_native_claude_mid_conversation_system_preserves_priority(self):
        history = [{"role": "user", "content": "task"},
                   {"role": "system", "content": [{"type": "text", "text": "constraint"}]}]
        result = request_to_openai(request_body(system="base", messages=history), "model", 16384)
        self.assertEqual(result["messages"], [{"role": "system", "content": "base"},
            {"role": "user", "content": "task"}, {"role": "system", "content": "constraint"}])

    def test_turn_scoped_system_clears_only_after_next_user(self):
        history = [{"role": "user", "content": "task"},
                   {"role": "system", "clear_at": "next_user_message", "content": "reminder"}]
        self.assertEqual(len(request_to_openai(request_body(messages=history), "model", 16384)["messages"]), 2)
        history += [{"role": "assistant", "content": "done"}, {"role": "user", "content": "next"}]
        converted = request_to_openai(request_body(messages=history), "model", 16384)
        self.assertEqual([m["role"] for m in converted["messages"]], ["user", "assistant", "user"])
        self.assertEqual(history[1]["content"], "reminder")

    def test_system_cannot_interrupt_tool_results_or_change_tools(self):
        for history in [
            [{"role": "system", "content": "first"}],
            [{"role": "user", "content": "x"}, {"role": "system", "content": "x"}, {"role": "user", "content": "x"}],
            [{"role": "user", "content": "x"}, {"role": "system", "content": [{"type": "tool_removal", "tool": {"name": "Read"}}]}],
            [{"role": "user", "content": "x"}, {"role": "system", "content": "x", "output_config": {"effort": "high"}}],
            [{"role": "assistant", "content": [{"type": "tool_use", "id": "one", "name": "Read", "input": {}}]}, {"role": "system", "content": "x"}],
        ]:
            with self.subTest(history=history), self.assertRaises(ConversionError):
                request_to_openai(request_body(messages=history), "model", 16384)


@unittest.skipIf(server is None, "Install proxy/requirements.txt to run proxy proofs")
class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = server.Settings.load(SETTINGS)
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.aclose()

    def client(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
        self.clients.append(client)
        return client

    def app_client(self, handler):
        app = server.create_app(self.settings, transport=httpx.MockTransport(handler))
        self.clients.append(app.state.upstream_client)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8083")
        self.clients.append(client)
        return client

    async def collect(self, stream):
        return events([part async for part in stream])

    async def test_health_count_and_no_diagnostic_inference(self):
        sent = []
        def handler(req):
            sent.append(req)
            raise AssertionError("Unexpected network request")
        client = self.app_client(handler)
        self.assertEqual((await client.get("/health")).status_code, 200)
        self.assertEqual((await client.get("/test-connection")).status_code, 404)
        response = await client.post("/v1/messages/count_tokens", headers={"x-api-key": KEY}, json=request_body())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-token-count-estimate"], "true")
        self.assertEqual(sent, [])

    async def test_reject_wrong_placeholder_without_upstream(self):
        client = self.app_client(lambda req: self.fail("Must not infer"))
        response = await client.post("/v1/messages", json=request_body())
        self.assertEqual(response.status_code, 401)

    async def test_deeply_nested_request_is_a_sanitized_400(self):
        client = self.app_client(lambda req: self.fail("Must not infer"))
        body = '{"private":' + '[' * 16000 + '"SECRET-BODY"' + ']' * 16000 + '}'
        response = await client.post("/v1/messages", headers={"x-api-key": KEY}, content=body)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("SECRET-BODY", response.text)

    async def test_deeply_nested_provider_response_is_a_sanitized_502(self):
        body = '{"private":' + '[' * 16000 + '"SECRET-BODY"' + ']' * 16000 + '}'
        source = FakeStream([body.encode()])
        client = self.app_client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "application/json"}))
        response = await client.post("/v1/messages", headers={"x-api-key": KEY}, json=request_body())
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("SECRET-BODY", response.text)
        self.assertTrue(source.closed)

    async def test_nonstream_translation_placeholder_and_fixed_gateway(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                                            "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
        client = self.app_client(handler)
        response = await client.post("/v1/messages", headers={"Authorization": "Bearer " + KEY}, json=request_body())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], [{"type": "text", "text": "OK"}])
        self.assertEqual(str(seen[0].url), BASE + "/chat/completions")
        self.assertEqual(seen[0].headers["authorization"], "Bearer " + KEY)
        self.assertEqual(seen[0].headers["accept-encoding"], "identity")
        self.assertEqual(json.loads(seen[0].content)["model"], "provider/middle")

    async def test_no_retries_no_redirect_and_safe_error(self):
        for status in (307, 429, 500):
            seen = []
            def handler(req):
                seen.append(req)
                return httpx.Response(status, text="SECRET-PROVIDER-BODY", headers={"Location": "https://evil.test"})
            client = self.app_client(handler)
            captured = io.StringIO()
            logger = logging.StreamHandler(captured)
            logging.getLogger().addHandler(logger)
            try:
                with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                    response = await client.post("/v1/messages", headers={"x-api-key": KEY}, json=request_body())
            finally:
                logging.getLogger().removeHandler(logger)
            self.assertEqual(len(seen), 1)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("SECRET-PROVIDER-BODY", response.text + captured.getvalue())

    async def test_text_is_incremental_and_usage_tail_kept(self):
        source = FakeStream([frame(choice({"content": "One"})), frame(choice({"content": "Two"})),
                             frame(choice(finish="stop")), frame({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}}), frame("[DONE]")])
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        parts = await self.collect(server.translated_stream(client, self.settings, request_body(stream=True), "claude-sonnet", "id"))
        deltas = [p["delta"]["text"] for p in parts if p["type"] == "content_block_delta"]
        self.assertEqual(deltas, ["One", "Two"])
        self.assertEqual(parts[-2]["usage"], {"input_tokens": 10, "output_tokens": 4})
        self.assertEqual(parts[-1]["type"], "message_stop")
        self.assertTrue(source.closed)

    async def test_sse_fragmented_multiline_and_empty_data(self):
        raw = b': heartbeat\r\ndata:\r\ndata: {"choices": [],\r\ndata: "usage": {}}\r\n\r\ndata: [DONE]\r\n\r\n'
        source = FakeStream([raw[index:index + 1] for index in range(len(raw))])
        self.assertEqual([item async for item in server.sse_objects(source)], [{"choices": [], "usage": {}}, None])
        self.assertTrue(source.closed)

    async def test_sse_empty_fields_and_framing_count_toward_event_limit(self):
        for raw in (b"data:\n" * 11, b":\n" * 33, b"data: " + b"x" * 59):
            with self.subTest(raw=raw), patch.object(server, "MAX_EVENT", 64):
                source = FakeStream([raw])
                with self.assertRaisesRegex(ConversionError, "exceeded limit"):
                    _ = [item async for item in server.sse_objects(source)]
                self.assertTrue(source.closed)

    async def test_sse_buffered_input_still_observes_cancellation(self):
        source = FakeStream([b"data:\n" * 16000 + frame({}) + frame("[DONE]")])
        async def consume():
            return [item async for item in server.sse_objects(source)]
        task = asyncio.create_task(consume())
        asyncio.get_running_loop().call_soon(task.cancel)
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(source.closed)

    async def test_compressed_response_rejected_before_reading_body(self):
        class UnreadBody(FakeStream):
            async def __aiter__(self):
                raise AssertionError("Must not read or decompress provider bytes")
                yield b""
        source = UnreadBody([])
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={
            "Content-Type": "application/json", "Content-Encoding": "gzip"}))
        with self.assertRaisesRegex(ConversionError, "Compressed"):
            _ = [part async for part in server.upstream_bytes(client, self.settings, {"stream": False})]
        self.assertTrue(source.closed)

    async def test_malformed_completions_fail_closed_in_both_modes(self):
        tool = {"id": "one", "function": {"name": "Read", "arguments": "{}"}}
        malformed = [
            ({"content": value}, "stop") for value in ([], {}, 0, True)
        ] + [
            ({"tool_calls": [tool]}, reason) for reason in ("stop", "length")
        ] + [
            ({"tool_calls": []}, "tool_calls"),
            ({"tool_calls": [tool, tool]}, "tool_calls"),
            ({"tool_calls": [{**tool, "id": ""}]}, "tool_calls"),
            ({"tool_calls": [{**tool, "function": {"name": "", "arguments": "{}"}}]}, "tool_calls"),
            ({"tool_calls": [{**tool, "function": {"name": "Read", "arguments": '{"x": NaN}'}}]}, "tool_calls"),
            ({"tool_calls": {}}, "stop"),
        ]
        for message, reason in malformed:
            with self.subTest(message=message, reason=reason):
                body = {"choices": [{"message": message, "finish_reason": reason}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
                client = self.app_client(lambda req: httpx.Response(200, json=body))
                response = await client.post("/v1/messages", headers={"x-api-key": KEY}, json=request_body())
                self.assertEqual(response.status_code, 502)
                delta = dict(message)
                if isinstance(delta.get("tool_calls"), list):
                    delta["tool_calls"] = [{**call, "index": index} for index, call in enumerate(delta["tool_calls"])]
                source = FakeStream([frame(choice(delta, reason)), frame({"usage": body["usage"]}), frame("[DONE]")])
                upstream = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
                parts = await self.collect(server.translated_stream(upstream, self.settings, {"stream": True}, "m", "id"))
                self.assertEqual(parts[-1]["type"], "error")
                self.assertFalse(any(p["type"] == "content_block_start" for p in parts))
                self.assertTrue(source.closed)

    async def test_single_choice_required_in_both_modes(self):
        for choices in ({}, [choice()["choices"][0]] * 2):
            client = self.app_client(lambda req: httpx.Response(200, json={"choices": choices}))
            response = await client.post("/v1/messages", headers={"x-api-key": KEY}, json=request_body())
            self.assertEqual(response.status_code, 502)
            source = FakeStream([frame({"choices": choices}), frame("[DONE]")])
            upstream = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
            parts = await self.collect(server.translated_stream(upstream, self.settings, {"stream": True}, "m", "id"))
            self.assertEqual(parts[-1]["type"], "error")

    async def test_repeated_tool_names_with_distinct_ids_remain_valid(self):
        calls = [{"id": name, "function": {"name": "Read", "arguments": "{}"}} for name in ("one", "two")]
        body = {"choices": [{"message": {"tool_calls": calls}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        client = self.app_client(lambda req: httpx.Response(200, json=body))
        response = await client.post("/v1/messages", headers={"x-api-key": KEY}, json=request_body(tools=TOOLS))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([block["id"] for block in response.json()["content"]], ["one", "two"])
        source = FakeStream([frame(choice({"tool_calls": [{**call, "index": index} for index, call in enumerate(calls)]}, "tool_calls")),
                             frame({"usage": body["usage"]}), frame("[DONE]")])
        upstream = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        payload = request_to_openai(request_body(stream=True, tools=TOOLS), "m", 16384)
        parts = await self.collect(server.translated_stream(upstream, self.settings, payload, "m", "id"))
        self.assertEqual(parts[-1]["type"], "message_stop")
        self.assertEqual([p["content_block"]["id"] for p in parts if p["type"] == "content_block_start"], ["one", "two"])

    async def test_fragmented_tool_call_is_valid_before_emitting(self):
        source = FakeStream([
            frame(choice({"tool_calls": [{"index": 0, "id": "tool-1", "function": {"name": "Read", "arguments": '{"pa'}}]})),
            frame(choice({"tool_calls": [{"index": 0, "function": {"arguments": 'th":"x"}'}}]})),
            frame(choice(finish="tool_calls")), frame({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 8}}), frame("[DONE]")])
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        payload = request_to_openai(request_body(stream=True, tools=TOOLS), "m", 16384)
        parts = await self.collect(server.translated_stream(client, self.settings, payload, "claude-sonnet", "id"))
        block = next(p for p in parts if p["type"] == "content_block_start")
        self.assertEqual(block["content_block"]["id"], "tool-1")
        delta = next(p for p in parts if p["type"] == "content_block_delta")
        self.assertEqual(json.loads(delta["delta"]["partial_json"]), {"path": "x"})
        self.assertEqual(parts[-2]["delta"]["stop_reason"], "tool_use")

    async def test_provider_must_obey_caller_tool_constraints(self):
        call = {"id": "one", "function": {"name": "Read", "arguments": "{}"}}
        scenarios = [
            ({"tools": []}, [call]),
            ({"tools": TOOLS, "tool_choice": {"type": "none"}}, [call]),
            ({"tools": TOOLS, "tool_choice": {"type": "auto", "disable_parallel_tool_use": True}},
             [call, {**call, "id": "two"}]),
            ({"tools": TOOLS + [{"name": "Edit", "input_schema": {"type": "object"}}],
              "tool_choice": {"type": "tool", "name": "Edit"}}, [call]),
        ]
        for options, calls in scenarios:
            with self.subTest(options=options):
                usage = {"prompt_tokens": 1, "completion_tokens": 1}
                body = {"choices": [{"message": {"tool_calls": calls}, "finish_reason": "tool_calls"}], "usage": usage}
                client = self.app_client(lambda req: httpx.Response(200, json=body))
                response = await client.post("/v1/messages", headers={"x-api-key": KEY}, json=request_body(**options))
                self.assertEqual(response.status_code, 502)
                source = FakeStream([frame(choice({"tool_calls": [{**c, "index": i} for i, c in enumerate(calls)]}, "tool_calls")),
                                     frame({"usage": usage}), frame("[DONE]")])
                upstream = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
                payload = request_to_openai(request_body(stream=True, **options), "m", 16384)
                parts = await self.collect(server.translated_stream(upstream, self.settings, payload, "m", "id"))
                self.assertEqual(parts[-1]["type"], "error")
                self.assertFalse(any(p["type"] == "content_block_start" for p in parts))
                self.assertTrue(source.closed)

    async def test_finish_marker_cannot_be_overridden_or_followed_by_deltas(self):
        tool = {"index": 0, "id": "one", "function": {"name": "Read", "arguments": "{}"}}
        for late in (choice(finish="tool_calls"), choice({"content": "late"})):
            source = FakeStream([frame(choice({"tool_calls": [tool]}, "length")), frame(late),
                                 frame({"usage": {"prompt_tokens": 1, "completion_tokens": 1}}), frame("[DONE]")])
            upstream = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
            payload = request_to_openai(request_body(stream=True, tools=TOOLS), "m", 16384)
            parts = await self.collect(server.translated_stream(upstream, self.settings, payload, "m", "id"))
            self.assertEqual(parts[-1]["type"], "error")
            self.assertFalse(any(p["type"] in ("content_block_start", "message_stop") for p in parts))
            self.assertTrue(source.closed)

    async def test_parser_deadline_emits_safe_error_and_keeps_task_usable(self):
        # A single buffered provider chunk must not hide the consumer timeout
        # behind a CancelledError from a suspended producer's cancel scope.
        source = FakeStream([b':\n\n' * 500000])
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        settings = server.Settings.load({**SETTINGS, "REQUEST_TIMEOUT": "0.001"})
        parts = await self.collect(server.translated_stream(client, settings, {"stream": True}, "m", "id"))
        self.assertEqual(parts[-1]["type"], "error")
        self.assertFalse(any(p["type"] == "message_stop" for p in parts))
        self.assertTrue(source.closed)
        await asyncio.sleep(0)

    async def test_deadline_budget_does_not_reset_between_items(self):
        clock = [0.0]
        async def items():
            for value in range(2):
                clock[0] += 0.6
                yield value
        stream = server.with_deadline(items(), 1.0)
        with patch.object(server.anyio, "current_time", side_effect=lambda: clock[0]):
            self.assertEqual(await stream.__anext__(), 0)
            with self.assertRaises(TimeoutError):
                await stream.__anext__()

    async def test_timeout_closes_stalled_upstream_in_both_response_modes(self):
        self.settings = server.Settings.load({**SETTINGS, "REQUEST_TIMEOUT": "0.01"})
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                source = FakeStream([], stall=True)
                client = self.app_client(lambda req: httpx.Response(200, stream=source, headers={
                    "Content-Type": "text/event-stream" if streaming else "application/json"}))
                response = await asyncio.wait_for(client.post("/v1/messages", headers={"x-api-key": KEY},
                    json=request_body(stream=streaming)), 1)
                if streaming:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('event: error', response.text)
                    self.assertNotIn('event: message_stop', response.text)
                else:
                    self.assertEqual(response.status_code, 502)
                self.assertTrue(source.closed)

    async def test_invalid_tool_json_never_emits_tool(self):
        source = FakeStream([frame(choice({"tool_calls": [{"index": 0, "id": "tool-1", "function": {"name": "Read", "arguments": "{"}}]}, "tool_calls")),
                             frame({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}), frame("[DONE]")])
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        parts = await self.collect(server.translated_stream(client, self.settings, request_body(stream=True), "claude-sonnet", "id"))
        self.assertFalse(any(p["type"] == "content_block_start" for p in parts))
        self.assertEqual(parts[-1]["type"], "error")

    async def test_truncated_stream_fails_not_success(self):
        source = FakeStream([frame(choice({"content": "part"}))])
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        parts = await self.collect(server.translated_stream(client, self.settings, request_body(stream=True), "claude-sonnet", "id"))
        self.assertEqual(parts[-1]["type"], "error")
        self.assertFalse(any(p["type"] == "message_stop" for p in parts))

    async def test_provider_error_cannot_be_hidden_by_success_fields(self):
        usage = {"prompt_tokens": 1, "completion_tokens": 1}
        error = {"message": "SECRET-PROVIDER-ERROR"}
        body = {"error": error, "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}], "usage": usage}
        client = self.app_client(lambda req: httpx.Response(200, json=body))
        response = await client.post("/v1/messages", headers={"x-api-key": KEY}, json=request_body())
        self.assertEqual(response.status_code, 502)
        self.assertNotIn(error["message"], response.text)
        for chunks in ([{**choice(finish="stop"), "usage": usage, "error": error}],
                       [{**choice(finish="stop"), "usage": usage}, {"error": error}]):
            source = FakeStream([frame(chunk) for chunk in chunks] + [frame("[DONE]")])
            upstream = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
            parts = await self.collect(server.translated_stream(upstream, self.settings, {"stream": True}, "m", "id"))
            self.assertEqual(parts[-1]["type"], "error")
            self.assertFalse(any(p["type"] == "message_stop" for p in parts))
            self.assertNotIn(error["message"], json.dumps(parts))
            self.assertTrue(source.closed)

    async def test_closing_stream_closes_upstream(self):
        source = FakeStream([frame(choice({"content": "part"}))], stall=True)
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        generator = server.translated_stream(client, self.settings, request_body(stream=True), "claude-sonnet", "id")
        await generator.__anext__()
        await generator.aclose()
        self.assertTrue(source.closed)

    async def test_cancel_stalled_stream_before_first_chunk(self):
        source = FakeStream([], stall=True)
        client = self.client(lambda req: httpx.Response(200, stream=source, headers={"Content-Type": "text/event-stream"}))
        generator = server.translated_stream(client, self.settings, request_body(stream=True), "claude-sonnet", "id")
        task = asyncio.create_task(generator.__anext__())
        await asyncio.wait_for(source.waiting.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(source.closed)

    async def test_nonstream_disconnect_cancels_work(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def work():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        class Request:
            async def receive(self):
                await started.wait()
                return {"type": "http.disconnect"}
        with self.assertRaises(ConversionError):
            await server.until_disconnect(work(), Request())
        self.assertTrue(cancelled.is_set())

    async def test_asgi_disconnect_cancels_stalled_upstream(self):
        for streaming in (False, True):
            for spec in ("2.3", "2.4"):
                with self.subTest(streaming=streaming, spec=spec):
                    source = FakeStream([], stall=True)
                    def handler(req):
                        return httpx.Response(200, stream=source, headers={
                            "Content-Type": "text/event-stream" if streaming else "application/json"})
                    app = server.create_app(self.settings, transport=httpx.MockTransport(handler))
                    self.clients.append(app.state.upstream_client)
                    body = json.dumps(request_body(stream=streaming)).encode()
                    sent_body = False
                    async def receive():
                        nonlocal sent_body
                        if not sent_body:
                            sent_body = True
                            return {"type": "http.request", "body": body, "more_body": False}
                        await source.waiting.wait()
                        return {"type": "http.disconnect"}
                    async def send(message):
                        pass
                    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": spec},
                             "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/v1/messages",
                             "raw_path": b"/v1/messages", "query_string": b"", "root_path": "",
                             "headers": [(b"x-api-key", KEY.encode()), (b"content-type", b"application/json")],
                             "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8083)}
                    await asyncio.wait_for(app(scope, receive, send), 1)
                    self.assertTrue(source.closed)


if __name__ == "__main__":
    unittest.main()

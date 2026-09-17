#!/usr/bin/env python3
"""Narrow, loopback-only Anthropic Messages adapter. Never accepts a Nebius key."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import uuid

import anyio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from proxy.vendor.conversion import (
    ConversionError, completion_tools, request_to_openai, response_text,
    response_to_claude, single_choice, stop_reason, usage,
)

PLACEHOLDER = "sprites-nebius-placeholder-not-a-secret"
MAX_BODY = 2 * 1024 * 1024
MAX_EVENT = 128 * 1024
CONFIG_KEYS = {"OPENAI_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "BIG_MODEL",
               "MIDDLE_MODEL", "SMALL_MODEL", "MAX_TOKENS_LIMIT", "REQUEST_TIMEOUT", "HOST", "PORT"}


@dataclass(frozen=True)
class Settings:
    gateway: str
    big: str
    middle: str
    small: str
    max_tokens: int = 16384
    timeout: float = 120.0

    @classmethod
    def load(cls, values):
        if not isinstance(values, dict) or set(values) - CONFIG_KEYS or any(not isinstance(v, str) for v in values.values()):
            raise ValueError("Proxy config must contain only documented string settings")
        if any(values.get(k) != PLACEHOLDER for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")):
            raise ValueError("Only the documented placeholder keys are accepted")
        gateway = values.get("OPENAI_BASE_URL", "").rstrip("/")
        if not re.fullmatch(r"https://api\.sprites\.dev/v1/gateway/custom_api/[A-Za-z0-9_-]+", gateway):
            raise ValueError("Use the exact custom_api gateway URL returned by Sprite discovery")
        if values.get("HOST", "127.0.0.1") != "127.0.0.1" or values.get("PORT", "8083") != "8083":
            raise ValueError("The proxy must bind to 127.0.0.1:8083")
        models = [values.get(k, "") for k in ("BIG_MODEL", "MIDDLE_MODEL", "SMALL_MODEL")]
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}", m) for m in models):
            raise ValueError("Set all three model aliases to selected discovery model IDs")
        try:
            limit = int(values.get("MAX_TOKENS_LIMIT", "16384"))
            timeout = float(values.get("REQUEST_TIMEOUT", "120"))
        except ValueError:
            raise ValueError("Invalid proxy limits") from None
        if not 16384 <= limit <= 65536 or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Token maximum must be 16384..65536; timeout must be 0..120 seconds")
        return cls(gateway, *models, limit, timeout)

    def model(self, requested):
        if requested in (self.big, self.middle, self.small):
            return requested
        if isinstance(requested, str):
            for alias, model in (("opus", self.big), ("sonnet", self.middle), ("haiku", self.small)):
                if requested == alias or (requested.startswith("claude-") and alias in requested):
                    return model
        raise ConversionError("Model is not a configured alias")


def event(kind, **data):
    return "event: " + kind + "\ndata: " + json.dumps({"type": kind, **data}) + "\n\n"


def error_response(status, message="Proxy request failed; upstream body omitted"):
    return JSONResponse({"type": "error", "error": {"type": "api_error", "message": message}}, status_code=status)


async def close_response(response):
    # Starlette cancels its streaming task on disconnect. Cleanup must survive
    # that cancellation scope; merely dropping an async generator is not enough.
    with anyio.move_on_after(5, shield=True):
        await response.aclose()


async def upstream_bytes(client, settings, payload):
    response = None
    try:
        request = client.build_request("POST", settings.gateway + "/chat/completions", json=payload,
                                       headers={"Authorization": "Bearer " + PLACEHOLDER,
                                                "Accept": "text/event-stream, application/json",
                                                "Accept-Encoding": "identity"})
        response = await client.send(request, stream=True)
        if response.status_code != 200:
            # No response bodies, URLs, prompts or credentials enter errors.
            raise ConversionError("Gateway inference request was rejected")
        expected = "text/event-stream" if payload["stream"] else "application/json"
        if response.headers.get("content-type", "").split(";")[0].lower() != expected:
            raise ConversionError("Unexpected gateway response content type")
        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise ConversionError("Compressed gateway responses are unsupported")
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_BODY:
                raise ConversionError("Gateway response exceeded size limit")
            yield chunk
    finally:
        if response is not None:
            await close_response(response)


async def with_deadline(items, timeout):
    """Bound the whole consumption without leaving a cancel scope across yield."""
    deadline = anyio.current_time() + timeout
    try:
        while True:
            remaining = deadline - anyio.current_time()
            if remaining <= 0:
                raise TimeoutError
            with anyio.fail_after(remaining):
                item = await items.__anext__()
            if anyio.current_time() >= deadline:
                raise TimeoutError
            yield item
    except StopAsyncIteration:
        return
    finally:
        await items.aclose()


async def sse_objects(chunks):
    buffer = bytearray()
    data = []
    event_size = 0
    try:
        async for chunk in chunks:
            # Split once per chunk; never repeatedly copy its unconsumed suffix.
            lines = chunk.split(b"\n")
            for index, line in enumerate(lines):
                if index % 256 == 0:
                    await anyio.lowlevel.checkpoint()
                if event_size + len(buffer) + len(line) > MAX_EVENT:
                    raise ConversionError("Upstream SSE event exceeded limit")
                if index == len(lines) - 1:
                    buffer.extend(line)
                    continue
                if buffer:
                    line = bytes(buffer) + line
                    buffer.clear()
                # Count framing and newlines too, including empty data fields.
                event_size += len(line) + 1
                if event_size > MAX_EVENT:
                    raise ConversionError("Upstream SSE event exceeded limit")
                line = line.rstrip(b"\r")
                if not line:
                    event_size = 0
                    if data:
                        raw = b"\n".join(data)
                        data = []
                        if raw == b"[DONE]":
                            yield None
                            return
                        try:
                            item = json.loads(raw)
                        except (ValueError, UnicodeError, RecursionError):
                            raise ConversionError("Malformed upstream SSE event") from None
                        if not isinstance(item, dict):
                            raise ConversionError("Malformed upstream SSE object")
                        yield item
                elif line.startswith(b"data:"):
                    data.append(line[5:].lstrip(b" "))
        raise ConversionError("Upstream stream ended without DONE")
    finally:
        await chunks.aclose()


async def translated_stream(client, settings, payload, original_model, message_id):
    payload = {**payload, "stream_options": {"include_usage": True}}
    stream = with_deadline(sse_objects(upstream_bytes(client, settings, payload)), settings.timeout)
    next_index, text_index, calls = 0, None, {}
    final_reason, final_usage, done, started = None, None, False, False
    try:
        async for chunk in stream:
            if not started:
                yield event("message_start", message={"id": message_id, "type": "message", "role": "assistant",
                            "model": original_model, "content": [], "stop_reason": None, "stop_sequence": None,
                            "usage": {"input_tokens": 0, "output_tokens": 0}})
                started = True
            if chunk is None:
                done = True
                break
            if chunk.get("error") is not None:
                raise ConversionError("Gateway stream reported an error")
            if chunk.get("usage") is not None:
                final_usage = usage(chunk["usage"])
            choice = single_choice(chunk.get("choices", []), allow_empty=True)
            if choice is None:
                continue
            if final_reason is not None:
                raise ConversionError("Upstream choice arrived after completion")
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                raise ConversionError("Malformed upstream delta")
            text = response_text(delta.get("content"))
            if text:
                if calls:
                    raise ConversionError("Unsupported upstream content ordering")
                if text_index is None:
                    text_index, next_index = next_index, next_index + 1
                    yield event("content_block_start", index=text_index, content_block={"type": "text", "text": ""})
                yield event("content_block_delta", index=text_index, delta={"type": "text_delta", "text": text})
            tool_parts = delta.get("tool_calls")
            if tool_parts is not None and not isinstance(tool_parts, list):
                raise ConversionError("Malformed upstream tool calls")
            for part in tool_parts or []:
                if not isinstance(part, dict) or part.get("type", "function") != "function":
                    raise ConversionError("Malformed upstream tool call")
                if text_index is not None:
                    yield event("content_block_stop", index=text_index)
                    text_index = None
                index = part.get("index")
                if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                    raise ConversionError("Invalid upstream tool index")
                call = calls.setdefault(index, {"id": None, "function": {"name": "", "arguments": ""}})
                if part.get("id") is not None:
                    if not isinstance(part["id"], str) or not part["id"]:
                        raise ConversionError("Invalid upstream tool ID")
                    if call["id"] and call["id"] != part["id"]:
                        raise ConversionError("Upstream tool ID changed")
                    call["id"] = part["id"]
                function = part.get("function", {})
                for key in ("name", "arguments"):
                    fragment = function.get(key)
                    if fragment is not None:
                        if not isinstance(fragment, str):
                            raise ConversionError("Invalid upstream tool fragment")
                        call["function"][key] += fragment
            if choice.get("finish_reason") is not None:
                final_reason = stop_reason(choice["finish_reason"])
        if not done or final_reason is None or final_usage is None:
            raise ConversionError("Incomplete upstream completion or usage")
        if text_index is not None:
            yield event("content_block_stop", index=text_index)
        # Buffer tool arguments until valid: never execute a truncated/empty
        # accidental tool. Text remains incremental; tool blocks are serialized.
        blocks = completion_tools(list(calls.values()), final_reason, payload)
        for block in blocks:
            arguments = json.dumps(block.pop("input"))
            yield event("content_block_start", index=next_index, content_block={**block, "input": {}})
            yield event("content_block_delta", index=next_index, delta={"type": "input_json_delta", "partial_json": arguments})
            yield event("content_block_stop", index=next_index)
            next_index += 1
        yield event("message_delta", delta={"stop_reason": final_reason, "stop_sequence": None}, usage=final_usage)
        yield event("message_stop")
    except (ConversionError, httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError, AttributeError):
        yield event("error", error={"type": "api_error", "message": "Gateway stream failed; upstream body omitted"})
    finally:
        await stream.aclose()


async def disconnected(request):
    # The request body has already been consumed. Await the ASGI disconnect
    # directly: polling is_disconnected() has its own cancellation scope.
    while (await request.receive())["type"] != "http.disconnect":
        pass


async def until_disconnect(awaitable, request):
    work = asyncio.create_task(awaitable)
    watch = asyncio.create_task(disconnected(request))
    try:
        done, _ = await asyncio.wait((work, watch), return_when=asyncio.FIRST_COMPLETED)
        if watch in done:
            raise ConversionError("Client disconnected")
        return await work
    finally:
        for task in (work, watch):
            if not task.done():
                task.cancel()
        with anyio.move_on_after(5, shield=True):
            await asyncio.gather(work, watch, return_exceptions=True)


async def read_request(request):
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > MAX_BODY:
            raise ConversionError("Request exceeds size limit")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise ConversionError("Expected JSON request") from None
    if not isinstance(value, dict):
        raise ConversionError("Expected JSON object")
    return value


class DisconnectStreamingResponse(StreamingResponse):
    """Watch disconnects even while no upstream bytes are arriving.

    ASGI 2.4 permits relying on send() errors. That alone cannot cancel a
    stalled upstream before the next send, so keep an explicit receive watcher.
    """

    async def __call__(self, scope, receive, send):
        async with anyio.create_task_group() as tasks:
            async def write():
                try:
                    await self.stream_response(send)
                except OSError:
                    pass  # Client closed; never forward/log request content.
                finally:
                    await self.body_iterator.aclose()
                    tasks.cancel_scope.cancel()
            tasks.start_soon(write)
            await self.listen_for_disconnect(receive)
            tasks.cancel_scope.cancel()


def create_app(settings, *, transport=None):
    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    client = httpx.AsyncClient(timeout=settings.timeout, trust_env=False, follow_redirects=False,
                               transport=transport or httpx.AsyncHTTPTransport(retries=0))
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.upstream_client = client

    @app.get("/health")
    async def health():
        return {"status": "ok", "scope": "local adapter only"}

    @app.post("/v1/messages")
    @app.post("/v1/messages/count_tokens")
    async def message(request: Request):
        # Placeholder authentication is not a security boundary against another
        # local Sprite process. The listener must never be exposed publicly.
        if request.headers.get("x-api-key") != PLACEHOLDER and request.headers.get("authorization") != "Bearer " + PLACEHOLDER:
            return error_response(401, "Expected the documented local placeholder")
        try:
            body = await read_request(request)
            model = settings.model(body.get("model"))
            if request.url.path.endswith("/count_tokens"):
                count_body = {**body, "max_tokens": 1, "stream": False}
                converted = request_to_openai(count_body, model, settings.max_tokens)
                # Local conservative approximation, never billing evidence.
                count = len(json.dumps({k: converted[k] for k in ("messages", "tools") if k in converted}))
                return JSONResponse({"input_tokens": max(1, (count + 2) // 3)}, headers={"X-Token-Count-Estimate": "true"})
            payload = request_to_openai(body, model, settings.max_tokens)
        except (ConversionError, TypeError, AttributeError, ValueError, RecursionError):
            return error_response(400, "Unsupported or invalid Messages request")
        message_id = "msg_" + uuid.uuid4().hex
        if payload["stream"]:
            return DisconnectStreamingResponse(translated_stream(client, settings, payload, body["model"], message_id),
                                               media_type="text/event-stream", headers={"Cache-Control": "no-store"})

        async def complete():
            parts = with_deadline(upstream_bytes(client, settings, payload), settings.timeout)
            try:
                data = b"".join([part async for part in parts])
                return response_to_claude(json.loads(data), body["model"], message_id, payload)
            finally:
                await parts.aclose()
        try:
            return await until_disconnect(complete(), request)
        except (ConversionError, httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError, RecursionError):
            return error_response(502)

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Private flat JSON settings file (no dotenv/shell execution)")
    args = parser.parse_args(argv)
    try:
        values = json.loads(args.config.read_text()) if args.config else {k: os.environ[k] for k in CONFIG_KEYS if k in os.environ}
        settings = Settings.load(values)
    except (OSError, ValueError):
        parser.exit(2, "Invalid proxy configuration; values omitted\n")
    # Libraries must not print full request/response diagnostics even if the
    # caller inherited a debug logging configuration. Access logs are off too.
    for name in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(name).disabled = True
    import uvicorn
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8083, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()

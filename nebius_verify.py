"""Bounded, credential-free probes for the Fly.io Sprites Nebius connector.

No real provider key is accepted, read from the environment, or written to disk.
Only inference probes send POST requests, with explicit CLI opt-in and no retries.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import json
import math
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DISCOVERY_URL = "https://api.sprites.dev/v1/gateway/list"
NEBIUS_URL = "https://api.tokenfactory.nebius.com/v1"
PLACEHOLDER = "sprites-nebius-placeholder-not-a-secret"
INVALID_BEARER = "deliberately-invalid-nebius-test-bearer"
MAX_BODY = 2 * 1024 * 1024
MAX_LINE = 128 * 1024
PROMPT = "Count from one to twenty, one number per line. Do not explain."


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def evidence_identity():
    # Hash the actual uploaded harness, not an assumed checkout revision.
    return {"recorded_at": utc_now(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


class ProbeError(Exception):
    """A safe diagnostic message; never includes an upstream response body."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, timeout=30.0):
        self.timeout = timeout
        # Do not inherit proxy credentials or redirect outside the selected gateway.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, url, *, method="GET", bearer=None, payload=None):
        headers = {"Accept": "application/json", "User-Agent": "sprites-nebius-verify"}
        if bearer is not None:
            headers["Authorization"] = "Bearer " + bearer
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
            # The gateway's JSON-only Accept negotiation precedes proxying.
            # Still request streaming in the body and require SSE in the response.
            headers["Accept"] = "text/event-stream, application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            return self.opener.open(request, timeout=self.timeout)
        except HTTPError as response:
            return response
        except (URLError, OSError, HTTPException):
            raise ProbeError("Gateway connection failed; no response body logged") from None


def gateway_url(value):
    if not isinstance(value, str):
        raise argparse.ArgumentTypeError("Gateway URL must be a string")
    value = value.rstrip("/")
    if not re.fullmatch(
        r"https://api\.sprites\.dev/v1/gateway/custom_api/[A-Za-z0-9_-]+", value
    ):
        raise argparse.ArgumentTypeError(
            "Use the exact HTTPS custom_api gateway_base_url from discovery; "
            "no key, query string, or extra /v1"
        )
    return value


def positive_timeout(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a number") from None
    if not math.isfinite(number) or not 0 < number <= 120:
        raise argparse.ArgumentTypeError("timeout must be between 0 and 120 seconds")
    return number


def token_limit(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("token limit must be an integer") from None
    if not 1 <= number <= 16384:
        raise argparse.ArgumentTypeError("token limit must be between 1 and 16384")
    return number


def read_json(response):
    body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ProbeError("JSON response exceeds size limit")
    try:
        return json.loads(body)
    except (ValueError, UnicodeError):
        raise ProbeError("Response is not valid JSON; body omitted") from None


def model_ids(response):
    if response.status != 200:
        raise ProbeError(f"Expected model list HTTP 200, received {response.status}")
    body = read_json(response)
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ProbeError("Expected a nonempty model data array")
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
           or not row["id"] for row in rows):
        raise ProbeError("Invalid model IDs in response")
    return sorted({row["id"] for row in rows})


def discover(client):
    with client.request(DISCOVERY_URL) as response:
        if response.status != 200:
            raise ProbeError(f"Gateway discovery returned HTTP {response.status}")
        body = read_json(response)
    rows = body.get("connections") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise ProbeError("Expected a gateway connections array")
    matches = []
    for row in rows:
        if not isinstance(row, dict) or row.get("provider") != "custom_api":
            continue
        upstream = row.get("base_api_url")
        if not isinstance(upstream, str) or upstream.rstrip("/") != NEBIUS_URL:
            continue
        try:
            url = gateway_url(row.get("gateway_base_url", ""))
        except argparse.ArgumentTypeError:
            raise ProbeError("Discovery returned an invalid gateway URL") from None
        # Never dump the raw connection record, which may gain new fields upstream.
        matches.append({"gateway_url": url})
    return [{"check": "discovery", "status": "pass" if matches else "fail",
             "connections": matches}]


def access(client, base, expected):
    if expected != "allowed":
        wanted = {"outside": 401, "unlabeled": 403}[expected]
        with client.request(base + "/models") as response:
            return [{"check": "V2" if expected == "outside" else "V3",
                     "status": "pass" if response.status == wanted else "fail",
                     "expected_http": wanted, "http_status": response.status}]

    with client.request(base + "/models") as response:
        ids = model_ids(response)
    results = [{"check": "S1", "status": "pass", "models": ids,
                "note": "CLI model discovery; not the V4 Gateway Playground UI check"}]
    with client.request(base + "/models", bearer=INVALID_BEARER) as response:
        # A successful baseline is necessary before the invalid-bearer comparison.
        other_ids = model_ids(response)
    results.append({"check": "S2", "status": "pass", "model_count": len(other_ids),
                    "note": "Invalid caller bearer accepted; server-side injection "
                            "still requires a credential-required upstream"})
    for path in ("/files", "/batches", "/fine_tuning/jobs"):
        with client.request(base + path) as response:
            results.append({"check": "S4 GET " + path,
                            "status": "pass" if response.status == 403 else "fail",
                            "http_status": response.status})
    return results


def sse_data(response, clock=time.monotonic, timeout=120.0):
    """Yield complete SSE data events, timestamped when received by this client."""
    started = clock()
    total = 0
    data = []
    first_line = True
    while True:
        raw = response.readline(MAX_LINE + 1)
        if clock() - started > timeout:
            raise ProbeError("Stream exceeded the duration limit")
        if not raw:
            # SSE dispatch requires an event terminator; a partial final frame is not success.
            if data:
                raise ProbeError("Stream ended inside an SSE event")
            return
        total += len(raw)
        if len(raw) > MAX_LINE or total > MAX_BODY:
            raise ProbeError("Stream exceeds size limit")
        try:
            line = raw.decode("utf-8").rstrip("\r\n")
        except UnicodeError:
            raise ProbeError("Invalid UTF-8 stream") from None
        if first_line:
            line = line.removeprefix("\ufeff")
            first_line = False
        if not line:
            if data:
                yield clock(), "\n".join(data)
                data = []
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)


def inspect_stream(response, api, *, clock=time.monotonic, timeout=120.0):
    if response.status != 200:
        raise ProbeError(f"Inference returned HTTP {response.status}; body omitted")
    if response.headers.get("Content-Type", "").split(";")[0].lower() != "text/event-stream":
        raise ProbeError("Expected text/event-stream")
    times = []
    characters = 0
    complete = False
    stopped = False
    tokens = {}
    for received, data in sse_data(response, clock, timeout):
        if data == "[DONE]":
            if api != "chat" or not stopped:
                raise ProbeError("Unexpected stream terminator")
            complete = True
            break
        try:
            event = json.loads(data)
        except ValueError:
            raise ProbeError("Invalid SSE JSON; data omitted") from None
        if not isinstance(event, dict):
            raise ProbeError("Expected an SSE event object")
        kind = event.get("type", "")
        if "error" in event or kind in ("error", "response.failed", "response.incomplete"):
            raise ProbeError("Upstream reported a stream error or incomplete response")
        content = None
        usage = event.get("usage")
        if api == "responses":
            if kind == "response.output_text.delta":
                content = event.get("delta")
            if kind == "response.completed":
                final = event.get("response")
                if not isinstance(final, dict) or final.get("status") != "completed":
                    raise ProbeError("Response completion is missing successful status")
                usage = final.get("usage")
                complete = True
        else:
            choices = event.get("choices", [])
            if not isinstance(choices, list):
                raise ProbeError("Invalid chat stream choices")
            if choices:
                choice = choices[0]
                if not isinstance(choice, dict) or not isinstance(choice.get("delta", {}), dict):
                    raise ProbeError("Invalid chat stream delta")
                content = choice.get("delta", {}).get("content")
                reason = choice.get("finish_reason")
                if reason is not None:
                    if reason != "stop":
                        raise ProbeError("Chat did not finish normally; check output budget")
                    stopped = True
        if isinstance(content, str) and content:
            times.append(received)
            characters += len(content)
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"):
                value = usage.get(key)
                if type(value) is int and value >= 0:
                    tokens[key] = value
        if complete:
            break
    if not complete or not times:
        raise ProbeError("Stream lacked text deltas or a successful completion event")
    span = times[-1] - times[0]
    observed = len(times) > 1 and span >= 0.05
    return {"check": "S3 " + api, "status": "pass" if observed else "inconclusive",
            "protocol": "pass", "incremental_delivery_observed": observed,
            "text_delta_count": len(times), "text_characters": characters,
            "first_to_last_delta_ms": round(span * 1000, 2), "usage": tokens,
            "note": "Arrival timing is observational, not proof of where buffering occurs; "
                    "short/fast generations may be inconclusive"}


def inference(client, base, model, max_tokens):
    with client.request(base + "/models") as response:
        if model not in model_ids(response):
            raise ProbeError("Selected model is not in the connector's model list")
    results = []
    payloads = (
        ("chat", "/chat/completions",
         {"messages": [{"role": "user", "content": PROMPT}], "max_tokens": max_tokens,
          "stream_options": {"include_usage": True}}),
        ("responses", "/responses", {"input": PROMPT, "max_output_tokens": max_tokens,
                                     "store": False}),
    )
    for api, path, payload in payloads:
        payload.update(model=model, stream=True)
        started_at = utc_now()
        try:
            with client.request(base + path, method="POST", bearer=PLACEHOLDER,
                                payload=payload) as response:
                result = inspect_stream(response, api, timeout=client.timeout)
        except (ProbeError, OSError, HTTPException) as exc:
            detail = str(exc) if isinstance(exc, ProbeError) else "Stream transport failed"
            result = {"check": "S3 " + api, "status": "fail", "detail": detail}
        result.update(started_at=started_at, finished_at=utc_now(), model=model,
                      endpoint=path, requested_output_limit=max_tokens,
                      request_attempts=1)
        results.append(result)
    return results


def write_denial(client, base):
    """One explicitly authorized empty POST, never an upload or inference call."""
    with client.request(base + "/models") as response:
        model_ids(response)  # A missing Sprite identity must not look like path denial.
    started = utc_now()
    with client.request(base + "/files", method="POST", bearer=PLACEHOLDER,
                        payload={}) as response:
        status = response.status
        body = read_json(response)
    expected = {"endpoint is blocked by policy", "endpoint is not in allowed list"}
    matched = isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"] in expected
    return [{"check": "V9", "status": "pass" if status == 403 and matched else "fail",
             "started_at": started, "finished_at": utc_now(), "http_status": status,
             "gateway_policy_error_observed": matched, "request_attempts": 1,
             "note": "HTTP and gateway policy error observed; retain separate no-upstream-dispatch evidence"}]


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--timeout", type=positive_timeout, default=30.0,
                     help="Socket timeout / stream duration check in seconds (default: 30)")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("discover", help="GET visible Nebius connectors from inside a Sprite")
    access_cli = commands.add_parser("access", help="GET-only authorization and path probes")
    access_cli.add_argument("--gateway-url", type=gateway_url, required=True)
    access_cli.add_argument("--expect", choices=("allowed", "outside", "unlabeled"), required=True)
    paid_cli = commands.add_parser("inference", help="Two bounded, potentially billable requests")
    paid_cli.add_argument("--gateway-url", type=gateway_url, required=True)
    paid_cli.add_argument("--model", required=True)
    paid_cli.add_argument("--max-output-tokens", type=token_limit, default=256)
    paid_cli.add_argument("--approve-paid-requests", action="store_true",
                          help="Required opt-in; sends up to two inference POSTs, without retries")
    denial_cli = commands.add_parser("write-denial", help="One permission-gated POST /files denial probe")
    denial_cli.add_argument("--gateway-url", type=gateway_url, required=True)
    denial_cli.add_argument("--approve-write-denial", action="store_true",
                            help="Requires prior authorization: a broken policy may dispatch upstream")
    return cli


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.command == "inference" and not args.approve_paid_requests:
        cli.error("inference requires --approve-paid-requests and prior authorization for spend")
    if args.command == "write-denial" and not args.approve_write_denial:
        cli.error("write-denial requires --approve-write-denial and prior authorization")
    client = Client(args.timeout)
    try:
        if args.command == "discover":
            results = discover(client)
        elif args.command == "access":
            results = access(client, args.gateway_url, args.expect)
        elif args.command == "write-denial":
            results = write_denial(client, args.gateway_url)
        else:
            results = inference(client, args.gateway_url, args.model, args.max_output_tokens)
    except (ProbeError, OSError, HTTPException) as exc:
        detail = str(exc) if isinstance(exc, ProbeError) else "Transport failed; body omitted"
        results = [{"check": args.command, "status": "fail", "detail": detail}]
    print(json.dumps({**evidence_identity(), "scope": "connector probes only", "full_spec_verified": False,
                      "results": results}, indent=2))
    return 0 if all(row["status"] == "pass" for row in results) else 1

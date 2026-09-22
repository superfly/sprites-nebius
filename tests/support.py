"""Shared offline fixtures; no credentials, real agents or external requests."""
import io
import json
from pathlib import Path
import tempfile
import unittest

import nebius_verify as verify

BASE = "https://api.sprites.dev/v1/gateway/custom_api/test-connector"
MODEL = "Qwen/test-model"


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200, content_type="application/json"):
        super().__init__(body)
        self.status = status
        self.headers = {"Content-Type": content_type}


def json_response(value, status=200):
    return Response(json.dumps(value).encode(), status)


class DiscoveryClient:
    def __init__(self, gateways=(BASE,), models=(MODEL,)):
        self.calls = []
        self.gateways = gateways
        self.models = models

    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == verify.DISCOVERY_URL:
            return json_response({"connections": [
                {"provider": "custom_api", "base_api_url": verify.NEBIUS_URL,
                 "gateway_base_url": item} for item in self.gateways]})
        return json_response({"data": [{"id": item} for item in self.models]})


class ServiceRuntime:
    def __init__(self):
        self.rows = []
        self.calls = []
        self.stall_stop = False

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "list":
            return json.dumps(self.rows).encode()
        if args[0] == "create":
            self.rows.append({"name": args[1], "cmd": args[3], "args": args[5].split(","),
                              "dir": args[7], "state": {"status": "running"}})
        elif args[0] == "stop" and not self.stall_stop:
            self.rows[0]["state"]["status"] = "stopped"
        elif args[0] == "delete":
            self.rows = [row for row in self.rows if row["name"] != args[1]]
        return b""


class HomeTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name).resolve()
        self.home = self.directory / "agent home"
        self.home.mkdir()

    def write(self, relative, content):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

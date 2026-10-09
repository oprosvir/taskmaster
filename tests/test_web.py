"""Tests for Taskmaster Web Dashboard HTTP server, REST API, and CLI."""

import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch

from src.ipc.client import IPCConnectionError
from src.web.server import create_server

_taskmasterweb_path = str(Path(__file__).resolve().parent.parent / "taskmasterweb")
_loader = SourceFileLoader("taskmasterweb", _taskmasterweb_path)
_spec = importlib.util.spec_from_loader("taskmasterweb", _loader)
taskmasterweb = importlib.util.module_from_spec(_spec)
_loader.exec_module(taskmasterweb)


class WebServerTests(unittest.TestCase):
    def setUp(self):
        self.client_patcher = patch("src.web.server.ClientIPC")
        self.mock_client_cls = self.client_patcher.start()
        self.addCleanup(self.client_patcher.stop)
        self.mock_client = self.mock_client_cls.return_value

        # Ephemeral port 0 binds to an available OS port automatically
        self.server = create_server("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _get(self, path: str):
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.headers.get_content_type(), resp.read()

    def _post_json(self, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else b""
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_get_root_serves_html_dashboard(self):
        status, content_type, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html")
        self.assertIn("Taskmaster", body.decode("utf-8"))
        self.assertIn("Auto-refresh", body.decode("utf-8"))

    def test_get_api_status_success(self):
        self.mock_client.request.return_value = {
            "ok": True,
            "data": {
                "programs": [
                    {
                        "name": "worker",
                        "processes": [
                            {"name": "worker_0", "state": "RUNNING", "pid": 1234, "uptime_seconds": 12.0}
                        ],
                    }
                ]
            },
        }

        status, content_type, body = self._get("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json")
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.mock_client.request.assert_called_once_with("status")

    def test_get_api_status_daemon_unavailable_returns_503(self):
        self.mock_client.request.side_effect = IPCConnectionError("socket not found")
        req = urllib.request.Request(f"{self.base_url}/api/status")
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError 503")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 503)
            data = json.loads(error.read().decode("utf-8"))
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"]["code"], "DAEMON_UNAVAILABLE")

    def test_post_action_start_success(self):
        self.mock_client.request.return_value = {"ok": True, "data": {"accepted": ["worker_0"]}}
        status, data = self._post_json("/api/action", {"action": "start", "target": "worker"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.mock_client.request.assert_called_once_with("start", "worker")

    def test_post_action_stop_success(self):
        self.mock_client.request.return_value = {"ok": True, "data": {"accepted": ["worker_0"]}}
        status, data = self._post_json("/api/action", {"action": "stop", "target": "worker_0"})
        self.assertEqual(status, 200)
        self.mock_client.request.assert_called_once_with("stop", "worker_0")

    def test_post_action_restart_success(self):
        self.mock_client.request.return_value = {"ok": True, "data": {"accepted": ["worker_0"]}}
        status, data = self._post_json("/api/action", {"action": "restart", "target": "all"})
        self.assertEqual(status, 200)
        self.mock_client.request.assert_called_once_with("restart", "all")

    def test_post_action_invalid_argument_returns_400(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/action",
            data=json.dumps({"action": "invalid", "target": "worker"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError 400")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)
            data = json.loads(error.read().decode("utf-8"))
            self.assertEqual(data["error"]["code"], "INVALID_ARGUMENT")

    def test_post_reload_success(self):
        self.mock_client.request.return_value = {"ok": True, "data": {"reloaded": True}}
        status, data = self._post_json("/api/reload", {})
        self.assertEqual(status, 200)
        self.mock_client.request.assert_called_once_with("reload")

    def test_post_shutdown_success(self):
        self.mock_client.request.return_value = {"ok": True, "data": {"accepted": True}}
        status, data = self._post_json("/api/shutdown", {})
        self.assertEqual(status, 200)
        self.mock_client.request.assert_called_once_with("shutdown")

    def test_unknown_endpoint_returns_404(self):
        req = urllib.request.Request(f"{self.base_url}/nonexistent")
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError 404")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 404)


class TaskmasterWebCliTests(unittest.TestCase):
    def test_parse_args_defaults(self):
        args = taskmasterweb.parse_args([])
        self.assertEqual(args.port, 9001)
        self.assertEqual(args.host, "127.0.0.1")

    def test_parse_args_custom_values(self):
        args = taskmasterweb.parse_args(["-p", "8888", "-H", "0.0.0.0"])
        self.assertEqual(args.port, 8888)
        self.assertEqual(args.host, "0.0.0.0")

    def test_exit_constants(self):
        self.assertEqual(taskmasterweb.EXIT_OK, 0)
        self.assertEqual(taskmasterweb.EXIT_ERROR, 1)


if __name__ == "__main__":
    unittest.main()

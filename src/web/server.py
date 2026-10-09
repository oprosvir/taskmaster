import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type

from src.ipc.client import ClientIPC, IPCClientError, IPCConnectionError
from src.ipc.protocol import SOCKET_PATH

DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"


class TaskmasterWebHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Taskmaster Web Dashboard."""

    client: ClientIPC
    html_content: bytes = b""

    def log_message(self, format: str, *args):
        """Suppress default stderr logging for clean console output."""
        return

    def _send_json(self, status_code: int, data: dict):
        """Helper to send a JSON response."""
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, status_code: int, content: bytes):
        """Helper to send an HTML response."""
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> dict | None:
        """Parse request body as JSON."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            return None
        body = self.rfile.read(content_length)
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self):
        """Handle GET requests."""
        if self.path in ("/", "/index.html"):
            self._send_html(200, self.html_content)
            return

        if self.path == "/api/status":
            try:
                response = self.client.request("status")
                self._send_json(200, response)
            except IPCConnectionError as error:
                self._send_json(
                    503,
                    {"ok": False, "error": {"code": "DAEMON_UNAVAILABLE", "message": str(error)}},
                )
            except IPCClientError as error:
                self._send_json(
                    500,
                    {"ok": False, "error": {"code": "IPC_ERROR", "message": str(error)}},
                )
            return

        self._send_json(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "Not Found"}})

    def _log(self, message: str) -> None:
        """Write timestamped log message to stdout with immediate flush."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [taskmasterweb] {message}", flush=True)

    def do_POST(self):
        """Handle POST requests."""
        if self.path == "/api/action":
            payload = self._read_json_body()
            if not payload or not isinstance(payload, dict):
                self._log("Rejected invalid JSON action payload")
                self._send_json(
                    400,
                    {"ok": False, "error": {"code": "BAD_REQUEST", "message": "Invalid JSON payload"}},
                )
                return

            action = payload.get("action")
            target = payload.get("target")

            if action not in ("start", "stop", "restart") or not target:
                self._log(f"Rejected invalid action request: action={action!r}, target={target!r}")
                self._send_json(
                    400,
                    {"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": "Invalid action or target"}},
                )
                return

            self._log(f"Action requested: {action} {target}")
            try:
                response = self.client.request(action, target)
                self._log(
                    f"Action succeeded: {action} {target} -> accepted: {response.get('data', {}).get('accepted', [])}"
                )
                self._send_json(200, response)
            except IPCConnectionError as error:
                self._log(f"Action failed (daemon unavailable): {error}")
                self._send_json(
                    503,
                    {"ok": False, "error": {"code": "DAEMON_UNAVAILABLE", "message": str(error)}},
                )
            except IPCClientError as error:
                self._log(f"Action failed (IPC error): {error}")
                self._send_json(
                    500,
                    {"ok": False, "error": {"code": "IPC_ERROR", "message": str(error)}},
                )
            return

        if self.path == "/api/reload":
            self._log("Config reload requested")
            try:
                response = self.client.request("reload")
                self._log("Config reload succeeded")
                self._send_json(200, response)
            except IPCConnectionError as error:
                self._log(f"Reload failed (daemon unavailable): {error}")
                self._send_json(
                    503,
                    {"ok": False, "error": {"code": "DAEMON_UNAVAILABLE", "message": str(error)}},
                )
            except IPCClientError as error:
                self._log(f"Reload failed (IPC error): {error}")
                self._send_json(
                    500,
                    {"ok": False, "error": {"code": "IPC_ERROR", "message": str(error)}},
                )
            return

        if self.path == "/api/shutdown":
            self._log("Daemon shutdown requested")
            try:
                response = self.client.request("shutdown")
                self._log("Daemon shutdown succeeded")
                self._send_json(200, response)
            except IPCConnectionError as error:
                self._log(f"Shutdown failed (daemon unavailable): {error}")
                self._send_json(
                    503,
                    {"ok": False, "error": {"code": "DAEMON_UNAVAILABLE", "message": str(error)}},
                )
            except IPCClientError as error:
                self._log(f"Shutdown failed (IPC error): {error}")
                self._send_json(
                    500,
                    {"ok": False, "error": {"code": "IPC_ERROR", "message": str(error)}},
                )
            return

        self._send_json(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "Not Found"}})


def create_server(
    host: str = "127.0.0.1",
    port: int = 9001,
    client: ClientIPC | None = None,
) -> ThreadingHTTPServer:
    """Create and return a configured ThreadingHTTPServer instance."""
    if client is None:
        client = ClientIPC(SOCKET_PATH)

    # Load HTML template content once
    if DASHBOARD_HTML_PATH.is_file():
        html_bytes = DASHBOARD_HTML_PATH.read_bytes()
    else:
        html_bytes = b"<h1>Taskmaster Dashboard (Template not found)</h1>"

    handler_cls: Type[TaskmasterWebHandler] = type(
        "CustomTaskmasterWebHandler",
        (TaskmasterWebHandler,),
        {"client": client, "html_content": html_bytes},
    )

    return ThreadingHTTPServer((host, port), handler_cls)


def run_server(
    host: str = "127.0.0.1",
    port: int = 9001,
    socket_path: Path = SOCKET_PATH,
):
    """Run the web dashboard HTTP server until interrupted."""
    client = ClientIPC(socket_path)
    server = create_server(host=host, port=port, client=client)
    print(f"[taskmasterweb] Dashboard running at http://{host}:{port}/", flush=True)
    print(f"[taskmasterweb] Connected to daemon socket: {socket_path}", flush=True)
    print("[taskmasterweb] Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[taskmasterweb] Shutting down...", flush=True)
    finally:
        server.server_close()

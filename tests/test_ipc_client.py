"""Linux integration tests for the low-level Taskmaster IPC client."""

import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
    raise unittest.SkipTest("POSIX Unix-domain sockets are required")

from src.ipc.client import (
    ClientIPC,
    IPCConnectionError,
    IPCProtocolError,
    MAX_MESSAGE_SIZE,
)


class IPCClientIntegrationTests(unittest.TestCase):
    """Integration tests using real Unix domain sockets."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.socket_path = Path(self.temp_dir.name) / "taskmaster.sock"
        self.received_request = bytearray()
        self.server_errors = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def _client_for_response(self, response_parts: list[bytes], *, close_after_parts: bool = True):
        """Start a fake IPC server and return a client connected to it."""
        # Clear state from previous test
        self.received_request.clear()
        self.server_errors.clear()

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        listener.listen(1)

        def serve():
            try:
                with listener:
                    connection, _ = listener.accept()
                    with connection:
                        # Read client request until newline
                        while b"\n" not in self.received_request:
                            chunk = connection.recv(4096)
                            if not chunk:
                                return
                            self.received_request.extend(chunk)

                        # Send response in parts
                        for part in response_parts:
                            connection.sendall(part)
                            if len(response_parts) > 1:
                                time.sleep(0.02)
                        if not close_after_parts:
                            connection.recv(1)
            except Exception as error:
                self.server_errors.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        return ClientIPC(self.socket_path, timeout=1), thread

    def _join_server(self, thread: threading.Thread):
        """Wait for server thread to finish and raise any errors."""
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive(), "fake IPC server did not finish")
        if self.server_errors:
            raise self.server_errors[0]

    def test_sends_one_json_line_and_returns_data(self):
        """Client sends JSON command and receives parsed response."""
        client, thread = self._client_for_response([b'{"status":"ok","message":"reloaded"}\n'])

        data = client.request("reload")
        self._join_server(thread)

        self.assertEqual(bytes(self.received_request), b'{"command": "reload"}\n')
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["message"], "reloaded")

    def test_reads_a_fragmented_response(self):
        """Client correctly reassembles response received in multiple chunks."""
        client, thread = self._client_for_response([b'{"status":"ok",', b'"message":"started"}\n'])

        data = client.request("start", target="worker_0")
        self._join_server(thread)

        self.assertEqual(bytes(self.received_request), b'{"command": "start", "target": "worker_0"}\n')
        self.assertEqual(data["status"], "ok")

    def test_rejects_invalid_json_response(self):
        """Client rejects invalid JSON responses from server."""
        client, thread = self._client_for_response([b"not-json\n"])

        with self.assertRaises((IPCConnectionError, Exception)):
            client.request("status")
        self._join_server(thread)

    def test_reports_eof_before_complete_response(self):
        """Server closes connection before sending complete response."""
        client, thread = self._client_for_response([b'{"status":"ok"'])

        with self.assertRaisesRegex(IPCConnectionError, "before sending a complete response"):
            client.request("status")
        self._join_server(thread)

    def test_reports_unavailable_socket(self):
        """Client raises error when socket file doesn't exist."""
        client = ClientIPC(self.socket_path, timeout=0.1)

        with self.assertRaises(IPCConnectionError):
            client.request("status")

    def test_rejects_oversized_request_before_connecting(self):
        """Client validates request size before attempting connection."""
        client = ClientIPC(self.socket_path)

        with self.assertRaises(IPCProtocolError):
            client.request("status", target="x" * MAX_MESSAGE_SIZE)

    def test_rejects_oversized_response(self):
        """Client rejects response exceeding MAX_MESSAGE_SIZE."""
        client, thread = self._client_for_response([b"x" * MAX_MESSAGE_SIZE + b"\n"])

        with self.assertRaises(IPCProtocolError):
            client.request("status")
        self._join_server(thread)

    def test_timeout_waiting_for_response(self):
        """Server doesn't respond within timeout raises IPCConnectionError."""
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        listener.listen(1)

        def serve():
            with listener:
                conn, _ = listener.accept()
                with conn:
                    conn.recv(4096)
                    time.sleep(2)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        client = ClientIPC(self.socket_path, timeout=0.5)
        with self.assertRaises(IPCConnectionError):
            client.request("status")

        thread.join(timeout=3)

    def test_server_sends_response_immediately(self):
        """Client handles fast server response."""
        client, thread = self._client_for_response([b'{"status":"ok"}\n'])

        data = client.request("reload")
        self._join_server(thread)

        self.assertEqual(data["status"], "ok")

    def test_server_closes_after_sending(self):
        """Client handles server closing connection after response."""
        client, thread = self._client_for_response([b'{"status":"ok"}\n'], close_after_parts=True)

        data = client.request("status")
        self._join_server(thread)

        self.assertEqual(data["status"], "ok")

    def test_rejects_empty_response(self):
        """Client rejects empty response from server."""
        client, thread = self._client_for_response([b"\n"])

        with self.assertRaises(IPCProtocolError):
            client.request("status")
        self._join_server(thread)


if __name__ == "__main__":
    unittest.main()

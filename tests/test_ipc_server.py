"""Linux tests for the non-blocking Unix-domain IPC server."""

import json
import os
import selectors
import socket
import tempfile
import time
import unittest
from pathlib import Path

if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
    raise unittest.SkipTest("POSIX Unix-domain sockets are required")

from src.ipc.server import MAX_MESSAGE_SIZE, ServerIPC


class ServerIPCTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.socket_path = Path(self.temp_dir.name) / "taskmaster.sock"
        self.selector = selectors.DefaultSelector()
        self.requests = []
        self.server = ServerIPC(self.socket_path, self._dispatch)
        self.server.start(self.selector)

    def tearDown(self):
        self.server.close()
        self.selector.close()
        self.temp_dir.cleanup()

    def _dispatch(self, command):
        self.requests.append(command)
        return {"accepted": [command.get("target", "none")]}

    def _run_once(self, timeout=0.5):
        for key, mask in self.selector.select(timeout):
            key.data(key.fileobj, mask)

    def _request(self, payload: bytes) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(str(self.socket_path))
            client.sendall(payload)
            client.setblocking(False)
            response = self._receive_response(client)
            return json.loads(response.split(b"\n", 1)[0].decode("utf-8"))

    def _receive_response(self, client: socket.socket) -> bytearray:
        response = bytearray()
        deadline = time.monotonic() + 1
        while b"\n" not in response and time.monotonic() < deadline:
            self._run_once(timeout=0.05)
            try:
                chunk = client.recv(4096)
            except BlockingIOError:
                continue
            except socket.timeout:
                continue
            if not chunk:
                break
            response.extend(chunk)
        self.assertIn(b"\n", response, "timed out waiting for IPC response")
        return response

    def test_valid_request_is_normalized_dispatched_and_answered(self):
        response = self._request(b'{"command":"start","target":"worker_0"}\n')

        self.assertEqual(self.requests, [{"command": "start", "target": "worker_0"}])
        self.assertEqual(
            response,
            {
                "ok": True,
                "data": {"accepted": ["worker_0"]},
            },
        )
        self.assertEqual(self.server.clients, {})

    def test_fragmented_request_is_read_across_selector_events(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(str(self.socket_path))
            client.sendall(b'{"command":"status",')
            self._run_once()  # accept
            self._run_once()  # read the first, incomplete request fragment
            self.assertEqual(self.requests, [])

            client.sendall(b'"target":"all"}\n')
            client.setblocking(False)
            response = self._receive_response(client)

        self.assertEqual(self.requests, [{"command": "status", "target": "all"}])
        self.assertEqual(
            json.loads(response),
            {
                "ok": True,
                "data": {"accepted": ["all"]},
            },
        )

    def test_malformed_utf8_and_json_return_protocol_errors(self):
        for payload in (b"\xff\n", b"{not-json}\n", b"[]\n"):
            with self.subTest(payload=payload):
                response = self._request(payload)
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "MALFORMED_REQUEST")
        self.assertEqual(self.requests, [])

    def test_unknown_command_and_invalid_arguments_are_rejected(self):
        unknown = self._request(b'{"command":"explode"}\n')
        missing_target = self._request(b'{"command":"restart"}\n')
        forbidden_target = self._request(b'{"command":"reload","target":"all"}\n')

        self.assertEqual(unknown["error"]["code"], "UNKNOWN_COMMAND")
        self.assertEqual(missing_target["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(forbidden_target["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.requests, [])

    def test_oversized_request_is_rejected(self):
        response = self._request(b"x" * MAX_MESSAGE_SIZE)

        self.assertEqual(response["error"]["code"], "REQUEST_TOO_LARGE")
        self.assertEqual(self.requests, [])

    def test_second_request_on_same_connection_is_never_dispatched(self):
        line = b'{"command":"status"}\n'
        response = self._request(line + line)

        if not response["ok"]:
            self.assertEqual(response["error"]["code"], "MALFORMED_REQUEST")
        self.assertLessEqual(len(self.requests), 1)

    def test_close_closes_registered_clients_and_removes_owned_socket(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(self.socket_path))
            self._run_once()
            self.assertEqual(len(self.server.clients), 1)
            self.assertTrue(self.socket_path.exists())

            self.server.close()

            self.assertEqual(self.server.clients, {})
            self.assertFalse(self.socket_path.exists())

    def test_start_removes_a_stale_socket_inode(self):
        self.server.close()
        stale_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale_socket.bind(str(self.socket_path))
        stale_socket.close()
        self.assertTrue(self.socket_path.exists())

        replacement = ServerIPC(self.socket_path, self._dispatch)
        replacement.start(self.selector)

        self.assertIsNotNone(replacement.server_socket)
        replacement.close()
        self.assertFalse(self.socket_path.exists())

    def test_duplicate_keys_are_rejected(self):
        """Ensure duplicate keys in JSON objects trigger MALFORMED_REQUEST."""
        response = self._request(b'{"command": "status", "command": "restart"}\n')
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "MALFORMED_REQUEST")
        self.assertEqual(self.requests, [])

    def test_normalization_strictness_errors(self):
        """Ensure strict normalization rejects unknown fields, bad types, and empty values."""
        # 1. Unknown fields in the request object
        resp1 = self._request(b'{"command": "status", "unexpected_field": true}\n')
        self.assertEqual(resp1["error"]["code"], "MALFORMED_REQUEST")

        # 2. Command is not a string (e.g., integer)
        resp2 = self._request(b'{"command": 42}\n')
        self.assertEqual(resp2["error"]["code"], "MALFORMED_REQUEST")

        # 3. Command is an empty string
        resp3 = self._request(b'{"command": ""}\n')
        self.assertEqual(resp3["error"]["code"], "MALFORMED_REQUEST")

        # 4. Status command with an invalid target type (integer instead of string)
        resp4 = self._request(b'{"command": "status", "target": 123}\n')
        self.assertEqual(resp4["error"]["code"], "INVALID_ARGUMENT")

        # 5. Target command with an empty target string
        resp5 = self._request(b'{"command": "start", "target": ""}\n')
        self.assertEqual(resp5["error"]["code"], "INVALID_ARGUMENT")

        self.assertEqual(self.requests, [])

    def test_dispatcher_error_mapping(self):
        """Ensure exceptions raised during command dispatch are correctly mapped to error responses."""
        # Test that ValueError maps to INVALID_ARGUMENT
        self.server.dispatcher = lambda cmd: int("not-an-int")
        response_val = self._request(b'{"command": "status"}\n')
        self.assertEqual(response_val["error"]["code"], "INVALID_ARGUMENT")

        # Test that unexpected Exception maps to INTERNAL_ERROR
        self.server.dispatcher = lambda cmd: (_ for _ in ()).throw(RuntimeError("unexpected crash"))
        response_err = self._request(b'{"command": "status"}\n')
        self.assertEqual(response_err["error"]["code"], "INTERNAL_ERROR")


if __name__ == "__main__":
    unittest.main()

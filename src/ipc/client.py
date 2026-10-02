import json
import socket
from pathlib import Path

from .server import MAX_MESSAGE_SIZE
from src.core.daemon import SOCKET_PATH

DEFAULT_TIMEOUT = 5.0


class IPCClientError(RuntimeError):
    """Base class for errors surfaced by the IPC client."""


class IPCConnectionError(IPCClientError):
    """The daemon socket could not be reached or the connection was interrupted."""


class IPCProtocolError(IPCClientError):
    """The daemon sent a response that does not match the IPC protocol."""


class ClientIPC:
    """Send one NDJSON command over a fresh Unix-domain socket connection."""

    def __init__(self, socket_path: Path = SOCKET_PATH, timeout: float = DEFAULT_TIMEOUT):
        self.socket_path = socket_path
        self.timeout = timeout

    def request(self, command: str, target: str | None = None) -> dict:
        """Send one request and return the parsed response dict"""
        # Build JSON style request payload
        request = {"command": command}
        if target is not None:
            request["target"] = target

        # Serialize to string and encode as UTF-8 bytes with newline delimiter
        try:
            message = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        except TypeError as error:
            raise ValueError(f"request cannot be encoded as JSON: {error}") from error

        # Enforce protocol size limit
        if len(message) > MAX_MESSAGE_SIZE:
            raise IPCProtocolError("request exceeds the 65536-byte protocol limit")

        # Open Unix domain socket connection to daemon
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(str(self.socket_path))
                connection.sendall(message)
                # Read response until newline delimiter or timeout
                response_bytes = self._receive_response(connection)
        except FileNotFoundError:
            raise IPCConnectionError(f"socket {self.socket_path} not found - is taskmasterd running?")
        except TimeoutError:
            raise IPCConnectionError("timed out while communicating with taskmasterd")
        except OSError as error:
            raise IPCConnectionError(f"cannot communicate with taskmasterd: {error}") from error

        try:
            return json.loads(response_bytes)
        except json.JSONDecodeError as error:
            raise IPCProtocolError(f"Invalid JSON response: {error}") from error

    def _receive_response(self, connection: socket.socket) -> bytes:
        """Read a complete newline-delimited JSON response from the daemon."""
        response = bytearray()

        while True:
            newline = response.find(b"\n")
            if newline >= 0:  # response is complete
                if newline + 1 > MAX_MESSAGE_SIZE:
                    raise IPCProtocolError("response exceeds the 65536-byte protocol limit")
                if newline != len(response) - 1:
                    raise IPCProtocolError("daemon sent more than one response on a connection")
                return bytes(response[:newline])

            try:
                chunk = connection.recv(min(4096, MAX_MESSAGE_SIZE + 1 - len(response)))
            except TimeoutError:
                raise IPCConnectionError("timed out waiting for a complete daemon response")
            except OSError as error:
                raise IPCConnectionError(f"connection failed while reading daemon response: {error}") from error

            if not chunk:
                raise IPCConnectionError("daemon closed the connection before sending a complete response")

            response.extend(chunk)

import json
import logging
import selectors
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.core.manager import ProgramNotFoundError

MAX_MESSAGE_SIZE = 65_536
COMMANDS = {"status", "start", "stop", "restart", "reload", "shutdown"}
TARGET_COMMANDS = {"start", "stop", "restart"}


class RequestError(Exception):
    """A client request failed protocol validation."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CommandFailedError(RuntimeError):
    """A valid command could not be completed by the daemon."""


class IPCStartError(RuntimeError):
    """Raised when the IPC server fails to start"""


@dataclass
class ClientConnection:
    """Tracks the state, buffers, and lifecycle of a single connected IPC client."""

    socket: socket.socket  # client socket for I/O
    request_buffer: bytearray = field(default_factory=bytearray)  # bytes read until "\n"
    response_buffer: bytes | None = None  # remaining response bytes to send
    responding: bool = False  # False = reading request, True = writing response


class ServerIPC:
    """Non-blocking NDJSON server for local control-shell clients."""

    def __init__(self, socket_path: Path, dispatcher: Callable[[dict], object]):
        self.socket_path = socket_path  # Unix socket file path
        self.dispatcher = dispatcher  # handles parsed commands
        self.server_socket: socket.socket | None = None  # listening socket
        self.selector: selectors.DefaultSelector | None = None  # I/O multiplexer
        self.clients: dict[socket.socket, ClientConnection] = {}  # socket -> state
        self.logger = logging.getLogger("taskmasterd.ipc")

    @property
    def has_pending_writes(self) -> bool:
        """True if any client still has a response in flight, used for shutdown."""
        return any(client.responding for client in self.clients.values())

    def start(self, selector: selectors.DefaultSelector):
        """Start listening on the Unix domain socket, registering it with the selector."""
        # Remove old socket file if it remains from a previous run
        if self.socket_path.exists():
            try:
                test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                test_sock.connect(str(self.socket_path))
                test_sock.close()
                # IPC socket is already accepting connections
                self.logger.critical("Failed to start IPC server: daemon is already running")
                raise IPCStartError
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                self.socket_path.unlink()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(str(self.socket_path))
        self.server_socket.listen()
        self.server_socket.setblocking(False)

        # Restrict access permissions (only the owner can read/write the socket)
        self.socket_path.chmod(0o600)

        selector.register(self.server_socket, selectors.EVENT_READ, self._accept)
        self.selector = selector
        self.logger.info("Server is listening on %s", self.socket_path)

    def close(self):
        """Unregister and close every client, and clean up the socket file."""
        # Close all active client connections
        for connection in list(self.clients.values()):
            self._close_client(connection)

        # Stop the server socket and unregister it from the selector
        if self.server_socket:
            try:
                self.selector.unregister(self.server_socket)
            except (KeyError, ValueError):
                pass

            self.server_socket.close()
            self.server_socket = None

        # Remove the socket file from the filesystem
        if self.socket_path and self.socket_path.exists():
            self.socket_path.unlink()

        # Reset the selector reference and log completion
        self.selector = None
        self.logger.info("Server socket closed and cleaned up.")

    def _accept(self, fileobj: socket.socket, mask):
        """Accept all currently queued clients without blocking."""
        while True:  # drain the whole backlog — multiple clients may be waiting
            try:
                conn, _ = fileobj.accept()
            except BlockingIOError:
                return  # backlog is empty, nothing left to accept
            except OSError:
                self.logger.error("Failed to accept IPC client")
                return

            conn.setblocking(False)
            client = ClientConnection(socket=conn)
            self.clients[conn] = client
            try:
                self.selector.register(conn, selectors.EVENT_READ, self._read_client)
                self.logger.info("Accepted new IPC client connection on fd=%s", conn.fileno())
            except (OSError, ValueError):
                self._close_client(client)  # roll back

    def _read_client(self, fileobj: socket.socket, mask: int):
        """Read incoming data from a client socket, validate protocol rules,
        and queue the request for processing upon receiving a complete message.
        """
        client = self.clients.get(fileobj)
        if client is None or client.responding:
            return  # already closed, or waiting to write a response

        # Read a chunk of data, capping size to prevent excessive memory usage
        try:
            chunk = fileobj.recv(min(4096, MAX_MESSAGE_SIZE + 1 - len(client.request_buffer)))
        except BlockingIOError:
            return  # no data available right now
        except OSError:
            self._close_client(client)
            return

        # Handle client disconnection (EOF)
        if not chunk:
            if client.request_buffer:
                self._queue_response(client, self._error("MALFORMED_REQUEST", "request ended before newline"))
            else:
                self._close_client(client)
            return

        client.request_buffer.extend(chunk)

        # maximum allowed message size limit
        if len(client.request_buffer) >= MAX_MESSAGE_SIZE:
            self._queue_response(client, self._error("REQUEST_TOO_LARGE", "request exceeds 65536 bytes"))
            return

        newline = client.request_buffer.find(b"\n")
        if newline < 0:
            return  # request not complete yet, wait for more data

        # bytes exist after the newline - the start of a second request
        if newline != len(client.request_buffer) - 1:
            self._queue_response(client, self._error("MALFORMED_REQUEST", "only one request is allowed per connection"))
            return

        # Extract and process the valid complete request
        self._process_request(client, client.request_buffer[:newline])

    def _process_request(self, client: ClientConnection, payload: bytes):
        """Process a verified raw request payload"""
        # deserialization and JSON parsing with duplicate key protection
        try:
            request = json.loads(payload, object_pairs_hook=self._check_duplicates)
        except (json.JSONDecodeError, ValueError) as error:
            self._queue_response(client, self._error("MALFORMED_REQUEST", f"invalid JSON request: {error}"))
            return

        # normalization (structure validation)
        try:
            command = self._normalize_request(request)
        except RequestError as error:
            self._queue_response(client, self._error(error.code, str(error)))
            return

        self.logger.info("Executing command: %s", command)

        # command execution and error mapping
        try:
            data = self.dispatcher(command)
            response = {"ok": True, "data": data}
        except CommandFailedError as error:
            self.logger.warning("Command failed [%s]: %s", command.get("command"), error)
            response = self._error("COMMAND_FAILED", str(error))
        except ProgramNotFoundError as error:
            self.logger.warning("Command target not found [%s]: %s", command.get("command"), error)
            response = self._error("UNKNOWN_TARGET", str(error))
        except ValueError as error:
            self.logger.warning("Invalid argument [%s]: %s", command.get("command"), error)
            response = self._error("INVALID_ARGUMENT", str(error))
        except Exception:
            self.logger.error("IPC command failed: %s", command.get("command"))
            response = self._error("INTERNAL_ERROR", "daemon could not process the command")
        self._queue_response(client, response)

    @staticmethod
    def _normalize_request(request: object) -> dict:
        """Validate and normalize raw request structure into a clean command dict."""
        if not isinstance(request, dict):
            raise RequestError("MALFORMED_REQUEST", "request must be a JSON object")
        if set(request) - {"command", "target"}:
            raise RequestError("MALFORMED_REQUEST", "request contains unknown fields")

        command = request.get("command")
        if not isinstance(command, str) or not command:
            raise RequestError("MALFORMED_REQUEST", "command must be a non-empty string")
        if command not in COMMANDS:
            raise RequestError("UNKNOWN_COMMAND", f"unknown command {command!r}")

        has_target = "target" in request
        target = request.get("target")
        if command == "status":
            # "status" allows "target" to be omitted (defaults to "all") but not blank
            if has_target and (not isinstance(target, str) or not target):
                raise RequestError("INVALID_ARGUMENT", "target must be a non-empty string")
            target = target or "all"
        elif command in TARGET_COMMANDS:
            # "start", "stop", and "restart" commands require a "target"
            if not isinstance(target, str) or not target:
                raise RequestError("INVALID_ARGUMENT", f"{command} requires a non-empty target")
        elif has_target:
            raise RequestError("INVALID_ARGUMENT", f"{command} does not accept a target")

        normalized = {"command": command}
        if command in TARGET_COMMANDS or command == "status":
            normalized["target"] = target
        return normalized

    @staticmethod
    def _check_duplicates(pairs: list[tuple[str, object]]) -> dict:
        """Ensure all keys in JSON object pairs are unique"""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key {key!r}")
            result[key] = value
        return result

    def _queue_response(self, client: ClientConnection, response: dict):
        """Serialize response dict to JSON bytes and switch client socket to write mode."""
        # Serialize response dict to bytes and append newline as a marker
        response_bytes = (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")

        client.response_buffer = response_bytes
        client.responding = True

        # Switch socket in the selector from EVENT_READ to EVENT_WRITE mode
        try:
            self.selector.modify(client.socket, selectors.EVENT_WRITE, self._write_client)
        except (KeyError, OSError, ValueError):
            self._close_client(client)

    def _write_client(self, fileobj: socket.socket, mask: int):
        """Send queued response bytes; close the connection once fully sent."""
        client = self.clients.get(fileobj)
        if client is None or client.response_buffer is None:
            return  # already closed, or nothing queued yet

        try:
            sent = fileobj.send(client.response_buffer)
        except BlockingIOError:
            return  # socket not ready to accept more bytes right now
        except OSError:
            self._close_client(client)
            return  # fatal network error

        # client closed its side of the connection
        if sent == 0:
            self._close_client(client)
            return

        client.response_buffer = client.response_buffer[sent:]  # keep only the unsent tail
        if len(client.response_buffer) == 0:
            self._close_client(client)  # full response delivered

    def _error(self, code: str, message: str) -> dict:
        """Build an error response payload."""
        return {"ok": False, "error": {"code": code, "message": message}}

    def _close_client(self, client: ClientConnection):
        """Safely unregister, close, and clean up a client connection."""
        # Remove the client from the active tracking dictionary
        fd = None
        self.clients.pop(client.socket, None)
        if client.socket:
            # Unregister the client socket from the selector safely
            try:
                fd = client.socket.fileno()
                self.selector.unregister(client.socket)
            except (KeyError, ValueError, OSError):
                pass

            # Close the underlying socket file descriptor
            try:
                client.socket.close()
            except OSError:
                pass

            client.socket = None
            self.logger.info("Client connection on fd=%s closed.", fd)

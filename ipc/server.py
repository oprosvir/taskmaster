import selectors
import socket
from pathlib import Path


class ServerIPC:
    """Manages the Unix Domain Socket server for local IPC between daemon and CLI clients."""

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self.server_socket = None

    def start(self, selector: selectors.DefaultSelector):
        """Start listening on the Unix domain socket, registering it with the selector."""
        # Remove old socket file if it remains from a previous run
        if self.socket_path.exists():
            self.socket_path.unlink()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(str(self.socket_path))
        self.server_socket.listen()
        self.server_socket.setblocking(False)

        # Restrict access permissions (only the owner can read/write the socket)
        self.socket_path.chmod(0o600)

        selector.register(self.server_socket, selectors.EVENT_READ, self._accept)
        print(f"[ipc] Server listening on {self.socket_path}")

    def close(self, selector: selectors.DefaultSelector):
        if self.server_socket:
            selector.unregister(self.server_socket)
            self.server_socket.close()
            self.server_socket = None

        if self.socket_path.exists():
            self.socket_path.unlink()
        print("[ipc] Server socket closed and cleaned up.")

    def _accept(self, fileobj, mask):
        """Temporary stub for accepting incoming client connections."""
        # TODO: Implement connection acceptance in the client shell sprint

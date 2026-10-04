from pathlib import Path

SOCKET_PATH = Path("/tmp/taskmaster.sock")
MAX_MESSAGE_SIZE = 65_536


class RequestError(Exception):
    """A client request failed protocol validation or command execution."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

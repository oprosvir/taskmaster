from enum import Enum, auto


class ProcessState(Enum):
    """FSM states for a managed process."""

    STOPPED = auto()  # Stopped by the user or not started yet
    STARTING = auto()  # Popen was called; starttime countdown is in progress
    RUNNING = auto()  # The process has run for at least starttime seconds
    BACKOFF = auto()  # Failed during startup; waiting for a retry
    STOPPING = auto()  # SIGTERM sent; waiting for the process to exit
    EXITED = auto()  # Exited successfully after reaching RUNNING
    FATAL = auto()  # startretries exceeded; process is considered unhealthy

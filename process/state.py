from enum import Enum, auto


class ProcessState(Enum):
    """FSM states for a managed process."""

    STOPPED = auto()    # Stopped by the user or not started yet
    STARTING = auto()   # Popen was called; starttime countdown is in progress
    RUNNING = auto()    # Stayed alive for at least starttime seconds
    BACKOFF = auto()    # Failed before starttime; waiting for a retry
    STOPPING = auto()   # Stop signal sent; waiting up to stoptime for exit
    EXITED = auto()     # Process exited after reaching RUNNING
    FATAL = auto()      # startretries exceeded; no further retries are allowed


class InvalidTransition(RuntimeError):
    """Raised when a transition isn't allowed from the current state."""


ALLOWED_TRANSITIONS: dict[ProcessState, set[ProcessState]] = {
    ProcessState.STOPPED: {ProcessState.STARTING},
    ProcessState.STARTING: {ProcessState.RUNNING, ProcessState.BACKOFF, ProcessState.STOPPING},
    ProcessState.RUNNING: {ProcessState.STOPPING, ProcessState.EXITED},
    ProcessState.STOPPING: {ProcessState.EXITED},
    ProcessState.EXITED: {ProcessState.STARTING, ProcessState.STOPPED},
    ProcessState.BACKOFF: {ProcessState.STARTING, ProcessState.FATAL},
    ProcessState.FATAL: set(),
}

from __future__ import annotations

import time
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .process import Process


class ProcessState(Enum):
    """FSM states for a managed process."""

    STOPPED = auto()  # Stopped by the user or not started yet
    STARTING = auto()  # Popen was called; starttime countdown is in progress
    RUNNING = auto()  # Stayed alive for at least starttime seconds
    BACKOFF = auto()  # Failed before starttime; waiting for a retry
    STOPPING = auto()  # Stop signal sent; waiting up to stoptime for exit
    EXITED = auto()  # Process exited after reaching RUNNING
    FATAL = auto()  # startretries exceeded; no further retries are allowed


class InvalidTransition(RuntimeError):
    """Raised when a transition isn't allowed from the current state."""


ALLOWED_TRANSITIONS: dict[ProcessState, set[ProcessState]] = {
    ProcessState.STOPPED: {ProcessState.STARTING},
    ProcessState.STARTING: {ProcessState.RUNNING, ProcessState.BACKOFF, ProcessState.STOPPING},
    ProcessState.RUNNING: {ProcessState.STOPPING, ProcessState.EXITED},
    ProcessState.STOPPING: {ProcessState.EXITED},
    ProcessState.EXITED: {ProcessState.STARTING, ProcessState.STOPPED},
    ProcessState.BACKOFF: {ProcessState.STARTING, ProcessState.FATAL, ProcessState.STOPPED},
    ProcessState.FATAL: set(),
}


def tick(proc: Process):
    """Advance one process state machine by a single event-loop tick."""
    if proc.state in (ProcessState.STOPPED, ProcessState.FATAL):
        return
    if proc.state == ProcessState.STARTING:
        _tick_starting(proc)
    elif proc.state == ProcessState.RUNNING:
        _tick_running(proc)
    elif proc.state == ProcessState.STOPPING:
        _tick_stopping(proc)


def _tick_starting(proc: Process):
    """Handle a process that is waiting to reach the start-time threshold."""
    exit_code = proc.poll()
    elapsed = time.monotonic() - proc.start_time

    if exit_code is not None:
        proc.exit_code = exit_code
        proc.logger.warning("Exited during startup with code %s.", exit_code)
        proc.transition_to(ProcessState.BACKOFF)
        _handle_backoff(proc)
        return

    if elapsed >= proc.config.starttime:
        proc.transition_to(ProcessState.RUNNING)
        proc.logger.info("Successfully reached RUNNING state.")


def _handle_backoff(proc: Process):
    """Retry a failed startup or mark the process as permanently failed."""
    if proc.shutting_down:
        proc.transition_to(ProcessState.STOPPED)
        return
    if proc.try_count <= proc.config.startretries:
        proc.logger.warning("Retrying startup (%d/%d).", proc.try_count, proc.config.startretries)
        proc.start()
    else:
        proc.logger.critical(
            "Startup retries exhausted (%d/%d); entering FATAL state.",
            proc.try_count - 1,
            proc.config.startretries
        )
        proc.transition_to(ProcessState.FATAL)


def spawn_failed(proc: Process):
    """Move a process to BACKOFF after a failed spawn attempt."""
    proc.transition_to(ProcessState.BACKOFF)
    _handle_backoff(proc)


def _tick_running(proc: Process):
    """Handle a process that has already reached the RUNNING state."""
    exit_code = proc.poll()
    if exit_code is not None:
        proc.exit_code = exit_code
        proc.transition_to(ProcessState.EXITED)
        _handle_exit(proc)


def _handle_exit(proc: Process):
    """Restart or stop a process after it exits according to its config."""
    if proc.shutting_down:
        proc.transition_to(ProcessState.STOPPED)
        return

    expected = proc.exit_code in proc.config.exitcodes
    should_restart = proc.config.autorestart == "always" or (proc.config.autorestart == "unexpected" and not expected)
    proc.transition_to(ProcessState.STOPPED)
    if should_restart:
        proc.try_count = 0
        proc.logger.info("Restarting according to autorestart policy.")
        proc.start()


def _tick_stopping(proc: Process):
    """Wait for graceful exit and force-kill after the configured timeout."""
    exit_code = proc.poll()
    if exit_code is not None:
        proc.exit_code = exit_code
        proc.logger.info("Stopped with exit code %s.", exit_code)
        proc.transition_to(ProcessState.EXITED)
        proc.transition_to(ProcessState.STOPPED)
        return

    elapsed = time.monotonic() - proc.stop_time
    if elapsed >= proc.config.stoptime:
        proc.kill()

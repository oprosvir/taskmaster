import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

from src.config import ProgramConfig

from .fsm import ALLOWED_TRANSITIONS, InvalidTransition, ProcessState, spawn_failed


@dataclass
class Process:
    """Manages an individual program instance lifecycle"""

    name: str
    config: ProgramConfig
    state: ProcessState = ProcessState.STOPPED
    popen: subprocess.Popen | None = None
    start_time: float | None = None
    stop_time: float | None = None
    try_count: int = 0
    exit_code: int | None = None
    shutting_down: bool = False
    logger: logging.Logger = field(init=False, repr=False)

    def __post_init__(self):
        self.logger = logging.getLogger(f"taskmasterd.{self.name}")

    # computed properties
    @property
    def pid(self) -> int | None:
        """Return the OS process ID if the process is active, otherwise None."""
        return self.popen.pid if self.popen else None

    @property
    def uptime(self) -> float | None:
        """Return running duration in seconds if the process is currently running."""
        if self.state != ProcessState.RUNNING or self.start_time is None:
            return None
        return time.monotonic() - self.start_time

    def poll(self) -> int | None:
        """Non-blocking check: None if still alive, exit code if dead."""
        if self.popen is None:
            return None
        return self.popen.poll()

    def transition_to(self, new_state: ProcessState):
        """Validate and apply a state transition on the given process."""
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.name}: {self.state.name} -> {new_state.name}")
        self.logger.debug("State transition: %s -> %s", self.state.name, new_state.name)
        self.state = new_state

    def _open_log_file(self, log_path: str | None):
        """Open the configured log file in append mode, creating parent directories if needed."""
        if not log_path:
            return subprocess.DEVNULL

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            return open(log_path, "a", encoding="utf-8")
        except (PermissionError, OSError) as e:
            self.logger.error("Error opening log file %s: %s. Output will be discarded.", log_path, e)
            return subprocess.DEVNULL

    def start(self, *, manual: bool = False):
        """Spawn the process, optionally resetting terminal manual-stop state.

        Automatic retries start from BACKOFF.  A manual start is intentionally
        narrower: it can only start a stopped process and may recover FATAL.
        """
        if self.state in (ProcessState.RUNNING, ProcessState.STARTING):
            return

        if manual:
            if self.state == ProcessState.FATAL:
                self.transition_to(ProcessState.STOPPED)
            if self.state != ProcessState.STOPPED:
                return
            self.shutting_down = False
            self.try_count = 0
        elif self.state == ProcessState.FATAL:
            return

        self.exit_code = None
        self.transition_to(ProcessState.STARTING)
        self.try_count += 1

        env = os.environ.copy()
        env.update(self.config.env)

        process_umask = self.config.umask if self.config.umask is not None else -1

        stdout_dest = self._open_log_file(self.config.stdout)
        stderr_dest = self._open_log_file(self.config.stderr)

        try:
            self.logger.info("Starting command: %s", self.config.cmd)
            self.popen = subprocess.Popen(
                self.config.argv,
                shell=False,
                cwd=self.config.workingdir,
                env=env,
                umask=process_umask,
                stdout=stdout_dest,
                stderr=stderr_dest,
                start_new_session=True,
            )
            self.start_time = time.monotonic()
        except OSError as e:
            self.popen = None
            self.logger.error("Failed to spawn process: %s", e)
            spawn_failed(self)
        finally:
            # Close parent process file descriptors to prevent descriptor leaks
            for stream in (stdout_dest, stderr_dest):
                if stream is not subprocess.DEVNULL:
                    stream.close()

    def send_stop_signal(self):
        """Send the configured stop signal and transition to STOPPING."""
        if not self.popen or self.state not in (ProcessState.RUNNING, ProcessState.STARTING):
            return

        try:
            self.logger.info("Stopping with signal %s...", self.config.stopsignal.name)
            self.popen.send_signal(self.config.stopsignal)
            self.stop_time = time.monotonic()
            self.transition_to(ProcessState.STOPPING)
        except ProcessLookupError:
            return

    def kill(self):
        """Forcefully terminate — used when graceful stop exceeds stoptime."""
        if self.popen is None:
            return

        try:
            self.logger.warning("Graceful stop timed out; force-killing process.")
            self.popen.kill()
            self.logger.info("SIGKILL sent.")
        except ProcessLookupError:
            return

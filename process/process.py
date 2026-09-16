import os
import subprocess
import sys
import time
from dataclasses import dataclass

from config import ProgramConfig

from .fsm import ALLOWED_TRANSITIONS, InvalidTransition, ProcessState, spawn_failed


@dataclass
class Process:
    name: str
    config: ProgramConfig
    state: ProcessState = ProcessState.STOPPED
    popen: subprocess.Popen | None = None
    start_time: float | None = None
    stop_time: float | None = None
    try_count: int = 0
    exit_code: int | None = None
    shutting_down: bool = False

    @property
    def pid(self) -> int | None:
        return self.popen.pid if self.popen else None

    @property
    def uptime(self) -> float | None:
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
        print(f"[{self.name}] State: {self.state.name} -> {new_state.name}")
        self.state = new_state

    def start(self):
        if self.state in (ProcessState.RUNNING, ProcessState.STARTING):
            return

        self.exit_code = None
        self.transition_to(ProcessState.STARTING)
        self.try_count += 1

        env = os.environ.copy()
        env.update(self.config.env)

        stdout_dest = subprocess.DEVNULL
        stderr_dest = subprocess.DEVNULL
        process_umask = self.config.umask if self.config.umask is not None else -1

        try:
            print(f"[{self.name}] Starting: {self.config.cmd}")
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
            print(f"[{self.name}] Failed to spawn: {e}", file=sys.stderr)
            spawn_failed(self)

    # TODO: Open the configured stdout/stderr file, or DEVNULL if unset
    # def _resolve_stream(path: str | None):

    def send_stop_signal(self):
        """Send the configured stop signal and transition to STOPPING."""
        if not self.popen or self.state not in (ProcessState.RUNNING, ProcessState.STARTING):
            return

        try:
            print(f"[{self.name}] Stopping with {self.config.stopsignal.name}...")
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
            print(f"[{self.name}] Graceful stop timed out; killing process.")
            self.popen.kill()
            print(f"[{self.name}] SIGKILL sent.")
        except ProcessLookupError:
            return

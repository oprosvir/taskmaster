import subprocess
import sys
import time
import os
from dataclasses import dataclass

from config import ProgramConfig
from .state import ProcessState, ALLOWED_TRANSITIONS, InvalidTransition


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

    @property
    def pid(self) -> int | None:
        return self.popen.pid if self.popen else None

    def poll(self) -> int | None:
        """Non-blocking check: None if still alive, exit code if dead."""
        if self.popen is None:
            return None
        return self.popen.poll()

    def transition_to(self, new_state: ProcessState):
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.name}: {self.state.name} -> {new_state.name}")
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
            )
            self.start_time = time.monotonic()
        except OSError as e:
            self.transition_to(ProcessState.BACKOFF)
            self.popen = None
            print(f"[{self.name}] Failed to spawn: {e}", file=sys.stderr)

    def stop(self):
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
        except ProcessLookupError:
            return

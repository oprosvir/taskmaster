import subprocess
import shlex
import sys
import time
import os
from enum import Enum, auto

from config import ProgramConfig


class ProcessState(Enum):
    """FSM states for a managed process."""

    STOPPED = auto()  # Stopped by the user or not started yet
    STARTING = auto()  # Popen was called; starttime countdown is in progress
    RUNNING = auto()  # The process has run for at least starttime seconds
    BACKOFF = auto()  # Failed during startup; waiting for a retry
    STOPPING = auto()  # SIGTERM sent; waiting for the process to exit
    EXITED = auto()  # Exited successfully after reaching RUNNING
    FATAL = auto()  # startretries exceeded; process is considered unhealthy


class Process:
    def __init__(self, name: str, config: ProgramConfig):
        self.name = name
        self.cfg = config

        self.state = ProcessState.STOPPED
        self.popen: subprocess.Popen | None = None

        self.start_time: float = 0.0
        self.stop_time: float = 0.0
        self.try_count: int = 0
        self.exit_code: int | None = None

    @property
    def pid(self) -> int | None:
        return self.popen.pid if self.popen else None

    def start(self) -> None:
        if self.state in (ProcessState.RUNNING, ProcessState.STARTING):
            return

        self.try_count += 1
        self.exit_code = None

        env = os.environ.copy()
        env.update(self.cfg.env)

        stdout_dest = subprocess.DEVNULL
        stderr_dest = subprocess.DEVNULL
        process_umask = self.cfg.umask if self.cfg.umask is not None else -1

        try:
            print(f"[{self.name}] Starting: {self.cfg.cmd}")
            self.popen = subprocess.Popen(
                shlex.split(self.cfg.cmd),
                shell=False,
                cwd=self.cfg.workingdir,
                env=env,
                umask=process_umask,
                stdout=stdout_dest,
                stderr=stderr_dest,
            )
            self.state = ProcessState.STARTING
            self.start_time = time.time()
        except Exception as e:
            self.state = ProcessState.BACKOFF
            self.popen = None
            print(f"[{self.name}] Failed to spawn: {e}", file=sys.stderr)

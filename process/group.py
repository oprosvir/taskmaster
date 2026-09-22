from dataclasses import dataclass, field

from config import ProgramConfig

from . import fsm
from .process import Process


@dataclass
class ProcessGroup:
    name: str
    config: ProgramConfig
    processes: list[Process] = field(default_factory=list)
    pending_restarts: set[str] = field(default_factory=set)

    def create_processes(self):
        """Create process instances according to the configured numprocs."""
        self.processes = []
        numprocs = self.config.numprocs
        for i in range(numprocs):
            proc_name = f"{self.name}_{i}" if numprocs > 1 else self.name
            proc = Process(name=proc_name, config=self.config)
            self.processes.append(proc)

    def start_if_autostart(self):
        """Start all processes when autostart is enabled."""
        if self.config.autostart:
            self.start()

    def start(self, targets: list[Process] | None = None):
        """Manually start the given processes, including recovering
        ones stuck in FATAL.
        """
        targets = targets if targets is not None else self.processes
        for proc in targets:
            self.pending_restarts.discard(proc.name)
            proc.start(manual=True)

    def stop(self, targets: list[Process] | None = None):
        """Request a graceful stop for the given processes (or the
        whole group), cancelling any pending restart for them.
        """
        targets = targets if targets is not None else self.processes
        for proc in targets:
            self.pending_restarts.discard(proc.name)
        self._request_stop(targets)

    def stop_all(self):
        self.stop()

    def restart(self, targets: list[Process] | None = None):
        """Stop the given processes (or the whole group) and restart
        each one individually as soon as it reaches a terminal state —
        checked on the next tick(), not immediately.
        """
        targets = targets if targets is not None else self.processes
        for proc in targets:
            self.pending_restarts.add(proc.name)
        self._request_stop(targets)

    def _request_stop(self, targets: list[Process]):
        """Mark processes as intentionally stopping and signal active ones."""
        for proc in targets:
            proc.shutting_down = True
            if proc.state in (fsm.ProcessState.RUNNING, fsm.ProcessState.STARTING):
                proc.send_stop_signal()
            else:
                proc.logger.info("Stop skipped; current state is %s.", proc.state.name)

    def tick(self):
        """Advance the state of every process in the group."""
        for proc in self.processes:
            fsm.tick(proc)

        if not self.pending_restarts:
            return
        ready = [
            proc for proc in self.processes
            if proc.name in self.pending_restarts
            and proc.state in (fsm.ProcessState.STOPPED, fsm.ProcessState.FATAL)
        ]
        if ready:
            self.start(ready)

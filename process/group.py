from dataclasses import dataclass, field

from config import ProgramConfig
from .process import Process
from . import fsm


@dataclass
class ProcessGroup:
    name: str
    config: ProgramConfig
    processes: list[Process] = field(default_factory=list)

    def create_processes(self) -> None:
        """Create process instances according to the configured numprocs."""
        self.processes = []
        numprocs = self.config.numprocs
        for i in range(numprocs):
            proc_name = f"{self.name}_{i}" if numprocs > 1 else self.name
            proc = Process(name=proc_name, config=self.config)
            self.processes.append(proc)

    def start_if_autostart(self) -> None:
        """Start all processes when autostart is enabled."""
        if self.config.autostart:
            for proc in self.processes:
                proc.start()

    def stop_all(self) -> None:
        """Request a graceful stop for every active process in the group."""
        for proc in self.processes:
            if proc.state in (fsm.ProcessState.RUNNING, fsm.ProcessState.STARTING):
                proc.send_stop_signal()

    def tick(self) -> None:
        """Advance the state of every process in the group."""
        for proc in self.processes:
            fsm.tick(proc)

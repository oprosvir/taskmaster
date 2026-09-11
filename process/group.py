from dataclasses import dataclass, field

from config import ProgramConfig
from .process import Process
from .state import ProcessState


@dataclass
class ProcessGroup:
    name: str
    config: ProgramConfig
    processes: list[Process] = field(default_factory=list)

    def create_processes(self):
        self.processes = []
        numprocs = self.config.numprocs
        for i in range(numprocs):
            proc_name = f"{self.name}_{i}" if numprocs > 1 else self.name
            proc = Process(name=proc_name, config=self.config)
            self.processes.append(proc)

    def start_if_autostart(self):
        if self.config.autostart:
            for proc in self.processes:
                proc.start()

    def stop_all(self) -> None:
        for proc in self.processes:
            if proc.state in (ProcessState.RUNNING, ProcessState.STARTING):
                proc.stop()

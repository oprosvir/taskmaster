from config import ProgramConfig
from .process import Process


class ProcessManager:
    def __init__(self, programs_cfg: dict[str, ProgramConfig]):
        # {"nginx": [<Process name="nginx">]}
        # {"worker": [<Process name="worker_0">, <Process name="worker_1">]}
        self.processes: dict[str, list[Process]] = {}
        self.setup_programs(programs_cfg)

    def setup_programs(self, programs_cfg: dict[str, ProgramConfig]):
        for prog_name, cfg in programs_cfg.items():
            numprocs = cfg.numprocs
            self.processes[prog_name] = []

            for i in range(numprocs):
                proc_name = f"{prog_name}_{i}" if numprocs > 1 else prog_name
                proc = Process(name=proc_name, config=cfg)
                self.processes[prog_name].append(proc)

    def start_all(self):
        """Start all processes whose configuration enables autostart."""
        for group in self.processes.values():
            for proc in group:
                if proc.cfg.autostart:
                    proc.start()

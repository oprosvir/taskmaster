from config import ProgramConfig
from process.group import ProcessGroup


class ProcessManager:
    def __init__(self, programs_cfg: dict[str, ProgramConfig]):
        self.groups: dict[str, ProcessGroup] = {}
        self.setup_programs(programs_cfg)

    def setup_programs(self, programs_cfg: dict[str, ProgramConfig]):
        # {"nginx": ProcessGroup(processes=[<Process name="nginx">])}
        # {"worker": ProcessGroup(processes=[<Process name="worker_0">,
        #                                    <Process name="worker_1">])}
        for prog_name, cfg in programs_cfg.items():
            group = ProcessGroup(name=prog_name, config=cfg)
            group.create_processes()
            self.groups[prog_name] = group

    def start_all(self) -> None:
        """Start every group whose config enables autostart."""
        for group in self.groups.values():
            group.start_if_autostart()

from config import ProgramConfig
from process.group import ProcessGroup
from process.fsm import ProcessState


class ProcessManager:
    def __init__(self, programs_cfg: dict[str, ProgramConfig]):
        self.groups: dict[str, ProcessGroup] = {}
        self.setup_programs(programs_cfg)

    def setup_programs(self, programs_cfg: dict[str, ProgramConfig]) -> None:
        """Create process groups from validated program configurations."""
        # {"nginx": ProcessGroup(processes=[<Process name="nginx">])}
        # {"worker": ProcessGroup(processes=[<Process name="worker_0">,
        #                                    <Process name="worker_1">])}
        for prog_name, cfg in programs_cfg.items():
            group = ProcessGroup(name=prog_name, config=cfg)
            group.create_processes()
            self.groups[prog_name] = group

    def start_all(self):
        """Start every group whose config enables autostart."""
        for group in self.groups.values():
            group.start_if_autostart()

    def stop_all(self):
        """Request a graceful stop for every active process."""
        for group in self.groups.values():
            group.stop_all()

    def all_stopped(self) -> bool:
        """True once every process has reached a terminal, non-running state."""
        terminal_states = (ProcessState.STOPPED, ProcessState.FATAL)
        return all(
            proc.state in terminal_states
            for group in self.groups.values()
            for proc in group.processes
        )

    def check_children(self):
        """Advance the state of every managed process."""
        for group in self.groups.values():
            group.tick()

    # TODO: def apply_diff(self, diff: ConfigDiff)

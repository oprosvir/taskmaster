from config import ProgramConfig, ConfigDiff
from process.group import ProcessGroup
from process.fsm import ProcessState

TERMINAL_STATES = (ProcessState.STOPPED, ProcessState.FATAL)


class ProcessManager:
    def __init__(self, programs_cfg: dict[str, ProgramConfig]):
        self.groups: dict[str, ProcessGroup] = {}
        self.draining_groups: list[ProcessGroup] = []
        self.pending_restarts: dict[str, ProgramConfig] = {}
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
        all_groups = list(self.groups.values()) + self.draining_groups
        return all(
            proc.state in TERMINAL_STATES
            for group in all_groups
            for proc in group.processes
        )

    def check_children(self):
        """Advance the state of every managed process."""
        for group in self.groups.values():
            group.tick()
        for group in self.draining_groups:
            group.tick()

        self._process_draining_groups()

    def _process_draining_groups(self):
        """Remove stopped groups and start any pending replacements."""
        still_draining = []
        for group in self.draining_groups:
            if all(proc.state in TERMINAL_STATES for proc in group.processes):
                pending_cfg = self.pending_restarts.pop(group.name, None)
                if pending_cfg is not None:
                    self._add_group(group.name, pending_cfg)
            else:
                still_draining.append(group)

        self.draining_groups = still_draining

    def _add_group(self, name: str, cfg: ProgramConfig):
        """Create, configure, and optionally start a new process group."""
        group = ProcessGroup(name=name, config=cfg)
        group.create_processes()
        group.start_if_autostart()
        self.groups[name] = group

    def _remove_group(self, name: str):
        """Stop an existing group and move it to draining_groups."""
        group = self.groups.pop(name)
        group.stop_all()
        self.draining_groups.append(group)

    def apply_diff(self, diff: ConfigDiff):
        """Apply config changes using atomic add/remove operations."""
        for name, cfg in diff.added.items():
            self._add_group(name, cfg)

        for name in diff.removed:
            self._remove_group(name)

        for name, cfg in diff.changed.items():
            self._remove_group(name)
            self.pending_restarts[name] = cfg

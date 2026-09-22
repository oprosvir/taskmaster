from src.config import ConfigDiff, ProgramConfig
from src.process.fsm import ProcessState
from src.process.group import ProcessGroup
from src.process.process import Process

TERMINAL_STATES = (ProcessState.STOPPED, ProcessState.FATAL)
ALL_TARGET = "all"


class ProgramNotFoundError(KeyError):
    """Raised when a command references a program name that doesn't exist."""


class ProcessManager:
    """Coordinates and manages multiple process groups within the daemon."""

    # =========================================================================
    # 1. INITIALIZATION & SETUP
    # =========================================================================

    def __init__(self, programs_cfg: dict[str, ProgramConfig]):
        self.groups: dict[str, ProcessGroup] = {}
        self.draining_groups: list[ProcessGroup] = []
        self.config_restarts: dict[str, ProgramConfig] = {}
        self.setup_programs(programs_cfg)

    def setup_programs(self, programs_cfg: dict[str, ProgramConfig]):
        """Create process groups from validated program configurations."""
        for prog_name, cfg in programs_cfg.items():
            group = ProcessGroup(name=prog_name, config=cfg)
            group.create_processes()
            self.groups[prog_name] = group

    # =========================================================================
    # 2. PUBLIC API / CONTROL COMMANDS
    # =========================================================================

    def start_all(self):
        """Start every group whose config enables autostart."""
        for group in self.groups.values():
            group.start_if_autostart()

    def stop_all(self):
        """Request a graceful stop for every active process."""
        for group in self.groups.values():
            group.stop_all()

    def status(self, target: str = ALL_TARGET) -> list[dict]:
        """Retrieve status information for a specific target or all programs."""
        resolved = self._resolve_target(target)
        return [
            {
                "name": group.name,
                "processes": [
                    {
                        "name": proc.name,
                        "state": proc.state.name,
                        "pid": proc.pid,
                        "uptime_seconds": proc.uptime,
                        "exit_code": proc.exit_code,
                    }
                    for proc in (procs if procs is not None else group.processes)
                ],
            }
            for group, procs in resolved
        ]

    def start(self, target: str) -> list[str]:
        """Start processes for a specific target group or instance."""
        resolved = self._resolve_target(target)
        for group, procs in resolved:
            group.start(procs)
        return [group.name for group, _ in resolved]

    def stop(self, target: str) -> list[str]:
        """Stop processes for a specific target group or instance."""
        resolved = self._resolve_target(target)
        for group, procs in resolved:
            group.stop(procs)
        return [group.name for group, _ in resolved]

    def restart(self, target: str) -> list[str]:
        """Restart processes for a specific target group or instance."""
        resolved = self._resolve_target(target)
        for group, procs in resolved:
            group.restart(procs)
        return [group.name for group, _ in resolved]

    # =========================================================================
    # 3. DAEMON CORE LOOP (TICK & STATE MACHINE)
    # =========================================================================

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

    # =========================================================================
    # 4. CONFIGURATION & GROUP LIFECYCLE (HOT-RELOAD)
    # =========================================================================

    def apply_diff(self, diff: ConfigDiff):
        """Apply config changes using atomic add/remove operations."""
        for name, cfg in diff.added.items():
            self._add_group(name, cfg)

        for name in diff.removed:
            self._remove_group(name)

        for name, cfg in diff.changed.items():
            self._remove_group(name)
            self.config_restarts[name] = cfg

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

    # =========================================================================
    # 5. HELPER METHODS
    # =========================================================================

    def _resolve_target(self, target: str) -> list[tuple[ProcessGroup, list[Process] | None]]:
        """Resolve a protocol target to (group, processes) pairs.

        - "all"                -> every group, whole group each
        - a bare group name    -> that group, whole group (None)
        - a specific instance  -> that group, just that one process
        """
        if not isinstance(target, str) or not target:
            raise ValueError("target must be a non-empty program name or 'all'")

        if target == ALL_TARGET:
            return [(group, None) for group in self.groups.values()]

        group = self.groups.get(target)
        if group is not None:
            return [(group, None)]

        for group in self.groups.values():
            for proc in group.processes:
                if proc.name == target:
                    return [(group, [proc])]

        raise ProgramNotFoundError(f"program {target!r} is not configured")

    def _process_draining_groups(self):
        """Remove stopped groups and start any pending replacements."""
        still_draining = []
        for group in self.draining_groups:
            if all(proc.state in TERMINAL_STATES for proc in group.processes):
                pending_cfg = self.config_restarts.pop(group.name, None)
                if pending_cfg is not None:
                    self._add_group(group.name, pending_cfg)
            else:
                still_draining.append(group)

        self.draining_groups = still_draining

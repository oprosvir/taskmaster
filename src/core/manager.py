from src.config import ConfigDiff, ProgramConfig
from src.process.state import ProcessState
from src.process.group import ProcessGroup
from src.process.process import Process

TERMINAL_STATES = (ProcessState.STOPPED, ProcessState.FATAL)
ALL_TARGET = "all"


class ProgramNotFoundError(Exception):
    """Raised when a command references a program name that doesn't exist."""


class DependencyNotReadyError(Exception):
    """Raised when a command cannot be executed because dependencies are not ready."""


class ProcessManager:
    """Coordinates and manages multiple process groups within the daemon."""

    # =========================================================================
    # 1. INITIALIZATION & SETUP
    # =========================================================================

    def __init__(self, programs_cfg: dict[str, ProgramConfig]):
        self.groups: dict[str, ProcessGroup] = {}
        self.draining_groups: list[ProcessGroup] = []
        self.config_restarts: dict[str, ProgramConfig] = {}
        self.pending_autostart: set[str] = set()
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
        """Start every group whose config enables autostart and track pending dependencies."""
        for group in self.groups.values():
            if not group.config.autostart:
                continue
            if self._deps_ready(group):
                group.start_if_autostart()
            else:
                self.pending_autostart.add(group.name)

    def stop_all(self):
        """Request a graceful stop for every active process."""
        self.pending_autostart.clear()
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
                        "stop_reason": proc.stop_reason.value if proc.stop_reason is not None else None,
                    }
                    for proc in (procs if procs is not None else group.processes)
                ],
            }
            for group, procs in resolved
        ]

    def start(self, target: str) -> list[str]:
        """Start processes for a specific target group or instance."""
        return self._execute_action(target, "start")

    def stop(self, target: str) -> list[str]:
        """Stop processes for a specific target group or instance."""
        return self._execute_action(target, "stop")

    def restart(self, target: str) -> list[str]:
        """Restart processes for a specific target group or instance."""
        return self._execute_action(target, "restart")

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

        self._process_pending_autostart()
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
        self.groups[name] = group
        if cfg.autostart:
            if self._deps_ready(group):
                group.start_if_autostart()
            else:
                self.pending_autostart.add(name)

    def _remove_group(self, name: str):
        """Stop an existing group and move it to draining_groups."""
        self.pending_autostart.discard(name)
        group = self.groups.pop(name)
        group.stop_all()
        self.draining_groups.append(group)

    # =========================================================================
    # 5. HELPER METHODS
    # =========================================================================

    def _deps_ready(self, group: ProcessGroup) -> bool:
        """Return True if all dependencies of the group are in RUNNING state."""
        return all(
            dep_name in self.groups and self.groups[dep_name].is_running
            for dep_name in group.config.depends_on
        )

    def _check_dependencies(self, group: ProcessGroup, target: str, action_name: str):
        """Ensure all dependencies are RUNNING, or raise DependencyNotReadyError."""
        if not self._deps_ready(group):
            unready = [
                d for d in group.config.depends_on
                if not (d in self.groups and self.groups[d].is_running)
            ]
            raise DependencyNotReadyError(
                f"cannot {action_name} {target!r}: dependencies not RUNNING ({', '.join(unready)})"
            )

    def _execute_action(self, target: str, action_name: str) -> list[str]:
        """Helper to resolve target, execute a group action, and return affected process names."""
        resolved = self._resolve_target(target)

        # Immediate rejection for start/restart of targeted program if dependencies are not RUNNING
        if action_name in ("start", "restart") and target != ALL_TARGET:
            for group, _ in resolved:
                self._check_dependencies(group, target, action_name)

        started = []
        for group, procs in resolved:
            if action_name in ("start", "restart") and target == ALL_TARGET and not self._deps_ready(group):
                if group.config.autostart:
                    self.pending_autostart.add(group.name)
                continue
            self.pending_autostart.discard(group.name)
            action = getattr(group, action_name)
            action(procs)
            started.extend([proc.name for proc in (procs if procs is not None else group.processes)])

        return started

    def _resolve_target(self, target: str) -> list[tuple[ProcessGroup, list[Process] | None]]:
        """Resolve a protocol target to (group, processes) pairs.

        - "all"                -> every group, whole group each
        - a bare group name    -> that group, whole group (None)
        - a specific instance  -> that group, just that one process
        """
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

    def _process_pending_autostart(self):
        """Start pending autostart groups whose dependencies have become ready."""
        if not self.pending_autostart:
            return

        for name in list(self.pending_autostart):
            group = self.groups.get(name)
            if group is None:
                self.pending_autostart.discard(name)
            elif self._deps_ready(group):
                group.start_if_autostart()
                self.pending_autostart.discard(name)

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

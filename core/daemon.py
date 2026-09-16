import os
import sys
from pathlib import Path
from pprint import pprint

from config import diff_programs, drop_privileges, load_config

from .event_loop import EventLoop
from .manager import ProcessManager


class TaskmasterDaemon:
    """Owns the daemon's runtime state"""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.global_cfg, self.programs_cfg = load_config(self.config_path)
        self.event_loop = EventLoop(daemon=self)
        self.manager = ProcessManager(self.programs_cfg)
        self.drop_privileges_if_root()

    def reload_config(self):
        """Reload configuration file, calculate diff, and apply state updates."""
        new_global, new_programs = load_config(self.config_path)
        diff = diff_programs(self.programs_cfg, new_programs)

        print("[taskmasterd] Config reloaded successfully.")
        print("[taskmasterd] Config diff summary:", file=sys.stderr)
        print(f"  - Added:     {sorted(diff.added)}", file=sys.stderr)
        print(f"  - Removed:   {sorted(diff.removed)}", file=sys.stderr)
        print(f"  - Changed:   {sorted(diff.changed)}", file=sys.stderr)
        print(f"  - Unchanged: {sorted(diff.unchanged)}", file=sys.stderr)

        self.manager.apply_diff(diff)

        self.global_cfg = new_global
        self.programs_cfg = new_programs
        pprint(self.global_cfg)
        pprint(self.programs_cfg)

    def drop_privileges_if_root(self):
        if os.geteuid() == 0:
            drop_privileges(self.global_cfg.user)
            print(f"[taskmasterd] Dropped privileges to user {self.global_cfg.user!r}")

    def shutdown(self):
        print("\n[taskmasterd] Shutting down.", file=sys.stderr)
        self.manager.stop_all()

    def run(self):
        """Start the event loop and process daemon signals.

        The event loop handles SIGHUP for configuration reloads and
        SIGINT/SIGTERM for graceful shutdown.
        """
        print("[taskmasterd] Initial configuration loaded successfully:")
        pprint(self.global_cfg)
        pprint(self.programs_cfg)
        print(f"\n[taskmasterd] Running (PID: {os.getpid()}). Press Ctrl+C to exit.")
        print("Test SIGHUP with: kill -HUP <PID>")

        self.event_loop.run()

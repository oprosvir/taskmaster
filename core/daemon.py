import os
import sys
from pathlib import Path
from pprint import pprint

from config import load_config, drop_privileges, diff_programs
from .event_loop import EventLoop


class TaskmasterDaemon:
    """Owns the daemon's runtime state"""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.global_cfg = None
        self.programs_cfg: dict = {}
        self.event_loop = None

    def reload_config(self) -> None:
        """Reload configuration file, calculate diff, and apply state updates."""
        new_global, new_programs = load_config(self.config_path)
        diff = diff_programs(self.programs_cfg, new_programs)

        if self.programs_cfg:
            print("[taskmaster] Config reloaded successfully.")
            print("[taskmasterd] Config diff summary:", file=sys.stderr)
            print(f"  - Added:     {sorted(diff.added)}", file=sys.stderr)
            print(f"  - Removed:   {sorted(diff.removed)}", file=sys.stderr)
            print(f"  - Changed:   {sorted(diff.changed)}", file=sys.stderr)
            print(f"  - Unchanged: {sorted(diff.unchanged)}", file=sys.stderr)

        self.global_cfg = new_global
        self.programs_cfg = new_programs
        pprint(self.global_cfg)
        pprint(self.programs_cfg)

        # TODO: self.process_manager.apply_diff(diff)

    def drop_privileges_if_root(self):
        if os.geteuid() == 0:
            drop_privileges(self.global_cfg.user)
            print(f"[taskmasterd] Dropped privileges to user {self.global_cfg.user!r}")

    def shutdown(self):
        print("\n[taskmasterd] Shutting down.", file=sys.stderr)
        # TODO:
        # if self.process_manager:
        #     self.process_manager.stop_all()

    def run(self):
        """Start the event loop and process daemon signals.

        The event loop handles SIGHUP for configuration reloads and
        SIGINT/SIGTERM for graceful shutdown.
        """
        print("[taskmaster] Initial configuration loaded successfully.")
        print(f"\n[taskmasterd] Running (PID: {os.getpid()}). Press Ctrl+C to exit.")
        print("Test SIGHUP with: kill -HUP <PID>")

        self.event_loop = EventLoop(daemon=self)
        self.event_loop.run()

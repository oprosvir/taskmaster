import os
import signal
import sys
from pathlib import Path
from pprint import pprint

from config import load_config, drop_privileges, ConfigNotFoundError, ConfigError, diff_programs
from common.exit_codes import EXIT_OK


class TaskmasterDaemon:
    """Owns the daemon's runtime state"""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.global_cfg = None
        self.programs_cfg: dict = {}

    def reload_config(self) -> None:
        """Reload configuration file, calculate diff, and apply state updates."""
        new_global, new_programs = load_config(self.config_path)

        diff = diff_programs(self.programs_cfg, new_programs)

        print("[taskmasterd] Config diff summary:", file=sys.stderr)
        print(f"  - Added:     {sorted(diff.added)}", file=sys.stderr)
        print(f"  - Removed:   {sorted(diff.removed)}", file=sys.stderr)
        print(f"  - Changed:   {sorted(diff.changed)}", file=sys.stderr)
        print(f"  - Unchanged: {sorted(diff.unchanged)}", file=sys.stderr)

        self.global_cfg = new_global
        self.programs_cfg = new_programs

        # TODO: self.process_manager.apply_diff(diff)

    def drop_privileges_if_root(self):
        if os.geteuid() == 0:
            drop_privileges(self.global_cfg.user)
            print(f"[taskmasterd] Dropped privileges to user {self.global_cfg.user!r}")

    def register_signal_handlers(self):
        # 1. SIGHUP -> reload
        signal.signal(signal.SIGHUP, self._handle_sighup)

        # 2. SIGINT / SIGTERM -> Graceful Shutdown
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_sighup(self, signum, frame):
        """Reload the config file and report what changed.

        No process manager yet (later sprint), so this only reloads
        and diffs — applying the diff to running processes comes later.
        """
        print("\n[taskmasterd] SIGHUP received: reloading config...", file=sys.stderr)
        try:
            self.reload_config()
            print("[taskmaster] Config reloaded successfully:")
            pprint(self.global_cfg)
            pprint(self.programs_cfg)
        except (ConfigNotFoundError, ConfigError) as e:
            print(f"[taskmasterd] Reload failed, keeping current config. Error: {e}", file=sys.stderr)

    def _handle_shutdown(self, signum, frame):
        print("\n[taskmasterd] Shutting down.", file=sys.stderr)
        sys.exit(EXIT_OK)

    def run(self):
        """Block and wait for signals.

        Placeholder for the real event loop / control server (later
        sprints) — for now this just keeps the process alive so SIGHUP
        can be tested.
        """
        print("[taskmaster] Initial configuration loaded successfully:")
        pprint(self.global_cfg)
        pprint(self.programs_cfg)
        print(f"\n[taskmasterd] Running (PID: {os.getpid()}). Press Ctrl+C to exit.")
        print("Test SIGHUP with: kill -HUP <PID>")

        while True:
            signal.pause()

import grp
import os
import pwd
import sys
import time
from pathlib import Path
from pprint import pformat

from src.config import diff_programs, drop_privileges, load_config
from src.ipc.server import ServerIPC

from .event_loop import SLEEP_TIMEOUT, EventLoop
from .manager import ProcessManager
from .logger import setup_logging

MAX_SHUTDOWN_WAIT = 30


class TaskmasterDaemon:
    """Owns the daemon's runtime state"""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.global_cfg, self.programs_cfg = load_config(self.config_path)

        self.drop_privileges_if_root()

        self.logger = setup_logging(
            logfile=self.global_cfg.logfile,
            loglevel=self.global_cfg.loglevel,
        )

        self.manager = ProcessManager(self.programs_cfg)

        self.ipc_server = ServerIPC(self.global_cfg.socket_path)

        self.event_loop = EventLoop(
            on_tick=self.manager.check_children,
            on_reload=self.reload_config,
            on_shutdown=self.shutdown
        )

    def reload_config(self):
        """Reload configuration file, calculate diff, and apply state updates."""
        new_global, new_programs = load_config(self.config_path)
        diff = diff_programs(self.programs_cfg, new_programs)

        self.logger.info(
            "Configuration reloaded: added=%s removed=%s changed=%s unchanged=%s",
            sorted(diff.added),
            sorted(diff.removed),
            sorted(diff.changed),
            sorted(diff.unchanged)
        )

        self.manager.apply_diff(diff)

        self.global_cfg = new_global
        self.programs_cfg = new_programs
        self.logger.debug("New global config:\n%s", pformat(self.global_cfg))
        self.logger.debug("New programs config:\n%s", pformat(self.programs_cfg))

    def drop_privileges_if_root(self):
        """Drop root privileges to a safer configured user if running as root."""
        if os.geteuid() == 0:
            drop_privileges(self.global_cfg.user)
            print(f"[taskmasterd] Dropped privileges to user {self.global_cfg.user!r}", file=sys.stderr)

    def shutdown(self):
        """Signal all processes to stop, then keep ticking until they actually exit"""
        self.logger.info("Shutting down: stopping all processes...")
        self.event_loop.is_running = False
        self.ipc_server.close(self.event_loop.selector)
        self.manager.stop_all()

        shutdown_deadline = time.monotonic() + MAX_SHUTDOWN_WAIT
        while not self.manager.all_stopped():
            if time.monotonic() > shutdown_deadline:
                self.logger.warning("Shutdown timeout exceeded, force-exiting.")
                break
            self.manager.check_children()
            time.sleep(SLEEP_TIMEOUT)

        self.logger.info("All processes stopped successfully.")

    def run(self):
        """High-level daemon startup orchestration."""
        self.logger.info("Taskmaster starting (pid=%s, config=%s)", os.getpid(), self.config_path)

        username = pwd.getpwuid(os.geteuid()).pw_name
        groupname = grp.getgrgid(os.getegid()).gr_name
        self.logger.info(
            "Daemon initialized as user=%s (uid=%s) group=%s (gid=%s)",
            username, os.geteuid(), groupname, os.getegid()
        )

        self.logger.info("Initial configuration loaded successfully.")
        self.logger.debug("Global config:\n%s", pformat(self.global_cfg))
        self.logger.debug("Programs config:\n%s", pformat(self.programs_cfg))

        self.logger.info("Test SIGHUP with: kill -HUP %s", os.getpid())
        self.logger.info("Press Ctrl+C to exit.")

        # 1. Start the IPC server and register it with the event loop selector
        self.ipc_server.start(self.event_loop.selector)

        # 2. Start programs configured with autostart = true
        self.manager.start_all()
        self.logger.info("Autostart phase completed")

        # 3. Transfer control to the event loop (blocking call)
        self.event_loop.run()

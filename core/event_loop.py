from __future__ import annotations
import signal
import sys
import time
from typing import TYPE_CHECKING
from config import ConfigNotFoundError, ConfigError

if TYPE_CHECKING:
    from .daemon import TaskmasterDaemon


class SignalFlags:
    def __init__(self) -> None:
        self.sighup: bool = False
        self.shutdown: bool = False

    def reset_hup(self) -> None:
        self.sighup = False


class EventLoop:
    def __init__(self, daemon: TaskmasterDaemon):
        self.daemon = daemon
        self.flags = SignalFlags()
        self.is_running = False

    def _setup_signals(self):

        def _handle_sighup(signum, frame):
            self.flags.sighup = True

        def _handle_shutdown(signum, frame):
            self.flags.shutdown = True

        signal.signal(signal.SIGHUP, _handle_sighup)
        signal.signal(signal.SIGINT, _handle_shutdown)
        signal.signal(signal.SIGTERM, _handle_shutdown)

    def run(self):
        self._setup_signals()
        self.is_running = True

        print("[event_loop] Started.")
        self.daemon.manager.start_all()

        while self.is_running:
            if self.flags.shutdown:
                print("\n[event_loop] Shutdown requested via signal.")
                self.daemon.shutdown()
                break

            if self.flags.sighup:
                self.flags.reset_hup()
                print("\n[taskmasterd] SIGHUP received: reloading config...", file=sys.stderr)
                try:
                    self.daemon.reload_config()
                except (ConfigNotFoundError, ConfigError) as e:
                    print(f"[taskmasterd] Reload failed, keeping current config. Error: {e}", file=sys.stderr)

            self.daemon.manager.check_children()
            time.sleep(0.1)

        self._cleanup()

    def _cleanup(self):
        self.is_running = False
        print("[event_loop] Stopped gracefully.")

import signal
import sys

from config import ConfigNotFoundError, ConfigError


class SignalFlags:
    def __init__(self) -> None:
        self.sighup: bool = False
        self.shutdown: bool = False

    def reset_hup(self) -> None:
        self.sighup = False


class EventLoop:
    def __init__(self, daemon):
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

        self._cleanup()

    def _cleanup(self):
        self.is_running = False
        print("[event_loop] Stopped gracefully.")

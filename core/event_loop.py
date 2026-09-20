import logging
import selectors
import signal

from config import ConfigError, ConfigNotFoundError

SLEEP_TIMEOUT = 0.1


class SignalFlags:
    """Container for asynchronous signal flags captured by signal handlers."""

    def __init__(self):
        self.sighup: bool = False
        self.shutdown: bool = False

    def reset_hup(self):
        """Reset the SIGHUP flag back to False after handling."""
        self.sighup = False


class EventLoop:
    """Core event loop responsible for I/O multiplexing and periodic ticks."""

    def __init__(self, on_tick, on_reload, on_shutdown):
        self.on_tick = on_tick
        self.on_reload = on_reload
        self.on_shutdown = on_shutdown
        self.selector = selectors.DefaultSelector()
        self.flags = SignalFlags()
        self.is_running = False
        self.logger = logging.getLogger("taskmasterd.event_loop")

    def _setup_signals(self):
        """Register signal handlers for SIGHUP, SIGINT, and SIGTERM."""

        def _handle_sighup(signum, frame):
            self.flags.sighup = True

        def _handle_shutdown(signum, frame):
            self.flags.shutdown = True

        signal.signal(signal.SIGHUP, _handle_sighup)
        signal.signal(signal.SIGINT, _handle_shutdown)
        signal.signal(signal.SIGTERM, _handle_shutdown)

    def run(self):
        """Start the event loop, processing I/O events, signals, and process ticks."""
        self._setup_signals()
        self.is_running = True
        self.logger.info("Started.")

        while self.is_running:
            # 1. Wait for I/O events
            events = self.selector.select(timeout=SLEEP_TIMEOUT)
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)

            # 2. Handle asynchronous signal flags
            if self.flags.shutdown:
                self.on_shutdown()

            if self.flags.sighup:
                self.flags.reset_hup()
                self.logger.info("SIGHUP received: reloading config...")
                try:
                    self.on_reload()
                except (ConfigNotFoundError, ConfigError) as e:
                    self.logger.error("Reload failed, keeping current config. Error: %s", e)

            # 3. Process manager tick (evaluate FSM states)
            self.on_tick()

        self._cleanup()

    def _cleanup(self):
        """Clean up event loop resources."""
        self.selector.close()
        self.logger.info("Selector closed, loop terminated.")

import logging
import selectors
import signal

from src.config import ConfigError

SLEEP_TIMEOUT = 0.1


class EventLoop:
    """Dispatch selector events, coalesce signals, and tick daemon state."""

    def __init__(self, on_tick, on_reload):
        self.on_tick = on_tick
        self.on_reload = on_reload

        self.shutdown_requested = False
        self.reload_requested = False
        self.is_running = False

        self.selector = selectors.DefaultSelector()
        self.logger = logging.getLogger("taskmasterd.event_loop")

    def _setup_signals(self):
        """Register flags-only handlers for reload and graceful shutdown signals."""

        def _handle_sighup(signum, frame):
            self.reload_requested = True

        def _handle_shutdown(signum, frame):
            self.shutdown_requested = True

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

            # 2. Handle SIGHUP signal
            if self.reload_requested:
                self.reload_requested = False
                self.logger.info("SIGHUP received: reloading config...")
                try:
                    self.on_reload()
                except ConfigError as e:
                    self.logger.error("Configuration reload failed, keeping current config. Error: %s", e)

            # 3. Process manager tick (evaluate FSM states)
            self.on_tick()

        self._cleanup()

    def _cleanup(self):
        """Clean up event loop resources."""
        self.selector.close()
        self.logger.info("Selector closed, loop terminated.")

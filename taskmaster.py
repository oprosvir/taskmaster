#!/usr/bin/env python3
import argparse
import os
import signal
import sys
from pathlib import Path
from pprint import pprint

from config import ConfigError, ConfigNotFoundError, load_config, diff_programs

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1


def get_config_path() -> Path:
    """
    Parse the config path from command-line arguments.

    Returns:
        Path: Path to the config file.
    """
    parser = argparse.ArgumentParser(description="Taskmaster process supervisor")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to the configuration file (default: ./config.toml)",
    )
    args = parser.parse_args()
    if not args.config.is_file():
        raise ConfigNotFoundError(f"configuration file '{args.config}' not found")
    return args.config


def main() -> int:
    try:
        config_path = get_config_path()
        global_cfg, programs_cfg = load_config(config_path)
    except (ConfigNotFoundError, ConfigError) as e:
        print(f"[taskmaster]: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    def handle_sighup(signum, _):
        """Reload the config file and report what changed.

        At this stage there is no process manager yet, so we only reload
        and diff — actually applying changes to running processes is a
        later sprint.
        """
        nonlocal programs_cfg
        print("\n[taskmaster] SIGHUP received: reloading config...", file=sys.stderr)
        try:
            new_global, new_programs = load_config(config_path)
            print("[taskmaster] Config reloaded successfully:")
            pprint(new_global)
            pprint(new_programs)
        except (ConfigNotFoundError, ConfigError) as e:
            print(f"[taskmaster] Reload error: {e}", file=sys.stderr)
            return

        diff = diff_programs(programs_cfg, new_programs)
        print("[taskmaster] Diff summary:")
        print(f"  - Added:     {sorted(diff.added.keys())}", file=sys.stderr)
        print(f"  - Removed:   {sorted(diff.removed)}", file=sys.stderr)
        print(f"  - Changed:   {sorted(diff.changed.keys())}", file=sys.stderr)
        print(f"  - Unchanged: {sorted(diff.unchanged)}", file=sys.stderr)

        # Update in-memory config for future process management
        programs_cfg = new_programs

    def handle_sigint(signum, _):
        """Handle Ctrl+C gracefully."""
        print("\n[taskmaster] Shutting down.", file=sys.stderr)
        sys.exit(EXIT_OK)

    signal.signal(signal.SIGHUP, handle_sighup)
    signal.signal(signal.SIGINT, handle_sigint)

    print("[taskmaster] Initial configuration loaded successfully:")
    pprint(global_cfg)
    pprint(programs_cfg)

    print(f"\n[taskmaster] Running (PID: {os.getpid()}). Press Ctrl+C to exit.")
    print("Test SIGHUP with: kill -HUP <PID>")

    # Placeholder for the real event loop / control shell (later sprints).
    # For now, just block and wait for signals so SIGHUP can be tested.
    while True:
        signal.pause()


if __name__ == "__main__":
    sys.exit(main())

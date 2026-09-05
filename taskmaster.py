#!/usr/bin/env python3
import argparse
import os
import signal
import sys
import time
from pathlib import Path
from pprint import pprint

from config import ConfigError, ConfigNotFoundError, load_config

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

    def handle_sighup(signum, _) -> None:
        print("\n[taskmaster] SIGHUP received: reloading config...", file=sys.stderr)
        try:
            global_cfg, programs_cfg = load_config(config_path)
            print("[taskmaster] Config reloaded successfully:")
            pprint(global_cfg)
            pprint(programs_cfg)
        except (ConfigNotFoundError, ConfigError) as e:
            print(f"[taskmaster] Reload error: {e}", file=sys.stderr)

    signal.signal(signal.SIGHUP, handle_sighup)

    print("[taskmaster] Initial configuration loaded successfully:")
    pprint(global_cfg)
    pprint(programs_cfg)

    print(f"\n[taskmaster] Running (PID: {os.getpid()}). Press Ctrl+C to exit.")
    print("Test SIGHUP with: kill -HUP <PID>")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[taskmaster] Shutting down.")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

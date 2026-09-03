#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from pprint import pprint

from config.loader import load_config
from config.models import ConfigError

EXIT_OK = 0
EXIT_CONFIG_ERROR = 1


def get_config_path() -> Path | None:
    """
    Parse the config path from command-line arguments.

    Returns:
        Path: Absolute or relative path to the config file if it exists.
        None: If the file does not exist or is not a regular file.
    """
    parser = argparse.ArgumentParser(description="Taskmaster process supervisor")
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to the configuration file (default: ./config.toml)"
    )
    args = parser.parse_args()
    if args.config.is_file():
        return args.config

    print(f"Error: Configuration file '{args.config}' not found.", file=sys.stderr)
    return None


def main() -> int:
    config_path = get_config_path()
    if config_path is None:
        return EXIT_CONFIG_ERROR

    try:
        global_cfg, programs_cfg = load_config(config_path)
    except ConfigError as e:
        print(f"taskmaster: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    pprint(global_cfg)
    pprint(programs_cfg)

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

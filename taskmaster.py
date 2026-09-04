#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from pprint import pprint

from config.loader import load_config
from config.models import ConfigError, ConfigNotFoundError

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
        "-c", "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to the configuration file (default: ./config.toml)"
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
        print(f"taskmaster: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    pprint(global_cfg)
    pprint(programs_cfg)

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

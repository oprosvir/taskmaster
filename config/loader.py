import tomllib
from .models import ConfigError, GlobalConfig, ProgramConfig


def load_config(path: str):
    """Load and validate the TOML config file.

    Args:
        path: Path to the TOML config file.

    Returns:
        A tuple containing the global configuration and a dictionary of
        program configurations, or ``None`` if the file is invalid or cannot
        be read.
    """
    try:
        with open(path, "rb") as f:
            raw_data = tomllib.load(f)

    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML syntax in {path!r}: {e}") from e
    except OSError as e:
        raise ConfigError(f"cannot read config file {path!r}: {e}") from e

    global_cfg = GlobalConfig(**raw_data.get("global", {}))
    programs_raw = raw_data.get("programs", {})

    if not isinstance(programs_raw, dict) or not programs_raw:
        raise ConfigError("config must contain a non-empty 'programs' section")

    programs_cfg: dict[str, ProgramConfig] = {}
    for prog_name, prog_data in programs_raw.items():
        if not isinstance(prog_data, dict):
            raise ConfigError(f"invalid configuration format for program {prog_name!r}")
        programs_cfg[prog_name] = ProgramConfig(name=prog_name, **prog_data)

    return global_cfg, programs_cfg

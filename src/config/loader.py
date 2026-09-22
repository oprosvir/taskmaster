import tomllib

from .models import ConfigError, GlobalConfig, ProgramConfig

KNOWN_SECTIONS = {"global", "program"}


def load_config(path: str) -> tuple[GlobalConfig, dict[str, ProgramConfig]]:
    """Load and validate the TOML config file.

    Args:
        path: Path to the TOML config file.

    Returns:
        A tuple containing the global configuration and a dictionary of
        program configurations.
    """
    # parse toml into dict, catch syntax and file access errors
    try:
        with open(path, "rb") as f:
            raw_data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML syntax in {path!r}: {e}") from e
    except OSError as e:
        raise ConfigError(f"cannot read config file {path!r}: {e}") from e

    # reject typos in section names
    unknown = set(raw_data) - KNOWN_SECTIONS
    if unknown:
        raise ConfigError(f"unknown top-level section(s): {sorted(unknown)}")

    # catch unknown or missing keyword arguments
    try:
        global_cfg = GlobalConfig(**raw_data.get("global", {}))
    except TypeError as e:
        raise ConfigError(f"invalid [global] section: {e}") from e

    # at least one program is required
    programs_raw = raw_data.get("program", {})
    if not isinstance(programs_raw, dict) or not programs_raw:
        raise ConfigError("config must contain a non-empty 'program' section")

    # bad program reports its own name in the error
    programs_cfg: dict[str, ProgramConfig] = {}
    for prog_name, prog_data in programs_raw.items():
        if not isinstance(prog_data, dict):
            raise ConfigError(f"invalid configuration format for program {prog_name!r}")
        try:
            programs_cfg[prog_name] = ProgramConfig(name=prog_name, **prog_data)
        except TypeError as e:
            raise ConfigError(f"invalid config for program {prog_name!r}: {e}") from e
    return global_cfg, programs_cfg

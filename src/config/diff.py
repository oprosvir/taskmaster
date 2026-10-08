from dataclasses import dataclass

from .models import ProgramConfig


@dataclass
class ConfigDiff:
    added: dict[str, ProgramConfig]
    removed: set[str]
    changed: dict[str, ProgramConfig]
    unchanged: set[str]


def diff_programs(old: dict[str, ProgramConfig], new: dict[str, ProgramConfig]) -> ConfigDiff:
    """Compare old and new program configurations.

    Args:
        old: Previous program configuration.
        new: New program configuration.

    Returns:
        ConfigDiff with added, removed, changed, and unchanged programs.
    """
    added = {name: new[name] for name in new if name not in old}
    removed = {name for name in old if name not in new}

    changed = {}
    unchanged = set()
    for name in new:
        if name in old:
            if old[name] != new[name]:
                changed[name] = new[name]
            else:
                unchanged.add(name)

    return ConfigDiff(added=added, removed=removed, changed=changed, unchanged=unchanged)

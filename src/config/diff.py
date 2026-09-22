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
    old_names = set(old)
    new_names = set(new)

    added = {name: new[name] for name in new_names - old_names}
    removed = old_names - new_names

    changed = {}
    unchanged = set()
    for name in old_names & new_names:  # intersection: names in both old and new
        if old[name] != new[name]:
            changed[name] = new[name]
        else:
            unchanged.add(name)

    return ConfigDiff(added=added, removed=removed, changed=changed, unchanged=unchanged)

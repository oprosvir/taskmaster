import shlex
from dataclasses import dataclass


class ParseError(ValueError):
    """Input isn't a valid command; the message is shown to the user as-is."""


@dataclass(frozen=True)
class Spec:
    """Defines validation rules and metadata for a CLI command."""

    min_args: int
    max_args: int
    usage: str
    description: str
    local: bool = False


COMMANDS = {
    "status": Spec(0, 1, "status [GROUP|PROCESS]", "show process status"),
    "start": Spec(1, 1, "start GROUP|PROCESS|all", "start processes"),
    "stop": Spec(1, 1, "stop GROUP|PROCESS|all", "stop processes"),
    "restart": Spec(1, 1, "restart GROUP|PROCESS|all", "restart processes"),
    "reload": Spec(0, 0, "reload", "reload daemon configuration"),
    "shutdown": Spec(0, 0, "shutdown", "stop the daemon"),
    "help": Spec(0, 0, "help", "show this help", local=True),
    "quit": Spec(0, 0, "quit", "leave the shell (daemon keeps running)", local=True),
}


@dataclass(frozen=True)
class Command:
    """Data Transfer Object (DTO) representing a successfully parsed user command."""

    name: str
    target: str | None = None

    @property
    def local(self) -> bool:
        """Return True if the command is executed locally by the client,
        or False if it must be sent to the daemon.
        """
        return COMMANDS[self.name].local


def parse_line(line: str) -> Command | None:
    """Turn one line of user input into a Command; None for a blank line."""
    try:
        parts = shlex.split(line)
    except ValueError as error:  # e.g. unbalanced quotes
        raise ParseError(f"cannot parse input: {error}") from None
    if not parts:
        return None

    name, *args = parts
    name = name.lower()

    spec = COMMANDS.get(name)
    if spec is None:
        raise ParseError(f"unknown command {name!r} (type 'help')")
    if not spec.min_args <= len(args) <= spec.max_args or "" in args:
        raise ParseError(f"usage: {spec.usage}")

    return Command(name, args[0] if args else None)

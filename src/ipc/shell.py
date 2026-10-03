import atexit
import os
import readline
import sys

from .client import ClientIPC, IPCClientError
from .parser import parse_line, COMMANDS, ParseError

PROMPT = "taskmaster> "
HISTORY_FILE = os.path.expanduser("~/.taskmaster_history")


def _setup_readline():
    """Configure readline for history, line editing and tab-completion."""
    try:
        readline.read_history_file(HISTORY_FILE)
    except FileNotFoundError:
        pass

    atexit.register(readline.write_history_file, HISTORY_FILE)
    readline.set_history_length(1000)

    def complete(text: str, state: int) -> str | None:
        """Readline completer function using COMMANDS keys."""
        matches = [cmd for cmd in COMMANDS.keys() if cmd.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")
    readline.parse_and_bind("set show-all-if-ambiguous on")


def print_help():
    """Print help information for all available commands."""
    print("Available commands:")
    for _, spec in COMMANDS.items():
        print(f"  {spec.usage:<30} - {spec.description}")


def _print_response(response: dict):
    """Format and print the daemon's response."""
    if response.get("ok"):
        data = response.get("data", {})
        if "programs" in data:
            _print_status(data["programs"])
        else:
            print(response)
    else:
        error = response.get("error", {})
        print(f"[{error.get('code')}] {error.get('message')}", file=sys.stderr)


def _print_status(programs: list[dict]):
    """Format and print all configured programs and their processes,
    showing name, state, PID, and uptime.
    """
    for program in programs:
        for proc in program["processes"]:
            uptime = f"{proc['uptime_seconds']:.1f}s" if proc["uptime_seconds"] is not None else "-"
            pid = proc["pid"] if proc["pid"] is not None else "-"
            print(f"{proc['name'][:24]:<25} {proc['state']:<10} pid={pid} uptime={uptime}")


def run(client: ClientIPC | None = None) -> int:
    """Run the interactive REPL until the user quits. Returns the exit code."""
    _setup_readline()
    client = client or ClientIPC()

    print("Taskmaster shell. Type 'help' for available commands.")

    while True:
        try:
            line = input(PROMPT)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break

        try:
            command = parse_line(line)
        except ParseError as error:
            print(f"Error: {error}", file=sys.stderr)
            continue

        if command is None:
            continue

        if command.name == "quit":
            print("Goodbye!")
            break

        if command.name == "help":
            print_help()
            continue

        try:
            response = client.request(command.name, command.target)
            _print_response(response)
        except IPCClientError as error:
            print(f"Error communicating with daemon: {error}", file=sys.stderr)

    return 0

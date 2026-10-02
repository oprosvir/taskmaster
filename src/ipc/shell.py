import sys
from .client import ClientIPC, IPCClientError
from .parser import parse_line, COMMANDS, ParseError


def print_help() -> None:
    """Print help information for all available commands."""
    print("Available commands:")
    for _, spec in COMMANDS.items():
        print(f"  {spec.usage:<30} - {spec.description}")


def run(client: ClientIPC | None = None) -> int:
    """Run the interactive REPL until the user quits. Returns the exit code."""
    client = client or ClientIPC()

    print("Taskmaster shell. Type 'help' for available commands.")

    while True:
        try:
            line = input("taskmaster> ")
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
            print(response)
        except IPCClientError as error:
            print(f"Error communicating with daemon: {error}", file=sys.stderr)

    return 0

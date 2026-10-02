import sys
from .client import ClientIPC, IPCClientError


def run(client: ClientIPC) -> int:

    print("Connecting to taskmasterd...")

    try:
        response = client.request("status")
        print("Success! Received response from daemon:")
        print(response)
    except IPCClientError as error:
        print(f"Error communicating with daemon: {error}", file=sys.stderr)
        return 1

    return 0

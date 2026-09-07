import os
import pwd
import sys


class PrivilegeError(RuntimeError):
    """Raised when dropping root privileges fails."""


def drop_privileges(username: str) -> None:
    """Drop root privileges to the given unprivileged user.

    Args:
        username: Existing system user to drop privileges to.
    """
    # defensive programming
    if os.geteuid() != 0:
        return

    try:
        user_entry = pwd.getpwnam(username)
    except KeyError as e:
        raise PrivilegeError(f"unknown user: {username!r}") from e

    try:
        if username == "nobody":
            # log.warning
            print("[taskmaster]: no 'user' specified in config file.",
                  "Dropping to 'nobody:nogroup' by default.", file=sys.stderr)
        os.initgroups(username, user_entry.pw_gid)
        os.setgid(user_entry.pw_gid)
        os.setuid(user_entry.pw_uid)
    except OSError as e:
        raise PrivilegeError(f"failed to drop privileges to {username!r}: {e}") from e

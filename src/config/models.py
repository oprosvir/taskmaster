import pwd
import shlex
import signal
from dataclasses import dataclass, field
from pathlib import Path

VALID_AUTORESTART = ("always", "never", "unexpected")
VALID_LOGLEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(ValueError):
    """Raised on malformed or invalid config file."""


class ConfigNotFoundError(FileNotFoundError):
    """Raised when the specified config file does not exist."""


@dataclass
class GlobalConfig:
    logfile: str = "/tmp/taskmaster.log"
    loglevel: str = "INFO"
    user: str = "nobody"
    socket_path: str = "/tmp/taskmaster.sock"

    def __post_init__(self):
        self._validate_loglevel()
        self._validate_logfile()
        self._validate_user()
        self._validate_socket_path()

    def _validate_loglevel(self):
        if not isinstance(self.loglevel, str):
            raise ConfigError("loglevel must be a string")
        level = self.loglevel.upper()
        if level not in VALID_LOGLEVELS:
            raise ConfigError(
                f"invalid loglevel: {self.loglevel!r} "
                f"(expected one of {VALID_LOGLEVELS})"
            )
        self.loglevel = level

    def _validate_logfile(self):
        if not isinstance(self.logfile, str) or not self.logfile.strip():
            raise ConfigError("logfile must be a non-empty string")
        self.logfile = Path(self.logfile)

    def _validate_user(self):
        if not isinstance(self.user, str) or not self.user.strip():
            raise ConfigError("user must be a non-empty string")
        try:
            user_info = pwd.getpwnam(self.user)
        except KeyError:
            raise ConfigError(f"unknown user: {self.user!r}")
        if user_info.pw_uid == 0:
            raise ConfigError("user must not be root")

    def _validate_socket_path(self):
        if not isinstance(self.socket_path, str) or not self.socket_path.strip():
            raise ConfigError("socket_path must be a non-empty string")
        self.socket_path = Path(self.socket_path)


@dataclass
class ProgramConfig:
    name: str
    cmd: str
    numprocs: int = 1
    autostart: bool = True
    autorestart: str = "unexpected"
    exitcodes: set[int] = field(default_factory=lambda: {0})
    starttime: int = 5
    startretries: int = 3
    stopsignal: str = "TERM"
    stoptime: int = 10
    stdout: str | None = None
    stderr: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    workingdir: str | None = None
    umask: str | None = None
    argv: list[str] = field(default_factory=list, init=False)

    def __post_init__(self):
        self._validate_cmd()
        self._validate_numprocs()
        self._validate_autostart()
        self._validate_autorestart()
        self._validate_exitcodes()
        self._validate_starttime()
        self._validate_startretries()
        self._validate_stopsignal()
        self._validate_stoptime()
        self._validate_stdout()
        self._validate_stderr()
        self._validate_env()
        self._validate_workingdir()
        self._validate_umask()

    def _validate_cmd(self):
        if not isinstance(self.cmd, str) or not self.cmd.strip():
            raise ConfigError("cmd must be a non-empty string")
        try:
            self.argv = shlex.split(self.cmd)
        except ValueError as e:
            raise ConfigError(f"cmd cannot be parsed: {e}") from e

    def _validate_numprocs(self):
        if not isinstance(self.numprocs, int) or isinstance(self.numprocs, bool):
            raise ConfigError("numprocs must be an integer")
        if self.numprocs < 1:
            raise ConfigError("numprocs must be >= 1")

    def _validate_autostart(self):
        if not isinstance(self.autostart, bool):
            raise ConfigError("autostart must be a boolean")

    def _validate_autorestart(self):
        if self.autorestart not in VALID_AUTORESTART:
            raise ConfigError(
                f"invalid autorestart: {self.autorestart!r} "
                f"(expected one of {VALID_AUTORESTART})"
            )

    def _validate_exitcodes(self):
        # Convert single int to set, or list to set
        if isinstance(self.exitcodes, int):
            self.exitcodes = {self.exitcodes}
        elif isinstance(self.exitcodes, list):
            self.exitcodes = set(self.exitcodes)
        if not isinstance(self.exitcodes, set) or not self.exitcodes:
            raise ConfigError("exitcodes must be a non-empty list of integers")
        for code in self.exitcodes:
            if not isinstance(code, int) or not (0 <= code <= 255):
                raise ConfigError(f"invalid exit code: {code!r} (must be 0-255)")

    def _validate_starttime(self):
        if not isinstance(self.starttime, int) or self.starttime < 0:
            raise ConfigError("starttime must be a non-negative integer")

    def _validate_startretries(self):
        if not isinstance(self.startretries, int) or self.startretries < 0:
            raise ConfigError("startretries must be a non-negative integer")

    def _validate_stopsignal(self):
        if not isinstance(self.stopsignal, str):
            raise ConfigError("stopsignal must be a string")
        name = self.stopsignal.upper()
        if not name.startswith("SIG"):
            name = f"SIG{name}"
        try:
            self.stopsignal = signal.Signals[name]
        except KeyError:
            raise ConfigError(f"unknown stopsignal: {self.stopsignal!r}")

    def _validate_stoptime(self):
        if not isinstance(self.stoptime, int) or self.stoptime < 0:
            raise ConfigError("stoptime must be a non-negative integer")

    def _validate_stdout(self):
        if self.stdout is not None:
            if not isinstance(self.stdout, str) or not self.stdout.strip():
                raise ConfigError("stdout must be a non-empty string or None")
            self.stdout = Path(self.stdout)

    def _validate_stderr(self):
        if self.stderr is not None:
            if not isinstance(self.stderr, str) or not self.stderr.strip():
                raise ConfigError("stderr must be a non-empty string or None")
            self.stderr = Path(self.stderr)

    def _validate_env(self):
        if not isinstance(self.env, dict):
            raise ConfigError("env must be a table of key-value strings")
        for k, v in self.env.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ConfigError(f"env entries must be strings: {k!r}={v!r}")

    def _validate_workingdir(self):
        if self.workingdir is None:
            return
        if not isinstance(self.workingdir, str) or not self.workingdir.strip():
            raise ConfigError("workingdir must be a non-empty string or None")
        path = Path(self.workingdir)
        if not path.is_dir():
            raise ConfigError(f"workingdir does not exist: {self.workingdir!r}")
        self.workingdir = path

    def _validate_umask(self):
        if self.umask is None:
            return
        if not isinstance(self.umask, str):
            raise ConfigError("umask must be an octal string or None")
        try:
            value = int(self.umask, 8)
        except ValueError:
            raise ConfigError(f"invalid umask: {self.umask!r} (expected octal string)")
        if not (0 <= value <= 0o777):
            raise ConfigError(f"umask out of range: {self.umask!r}")
        self.umask = value

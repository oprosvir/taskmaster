"""Unit tests for configuration loading, validation, models, and diffing."""

import signal
import tempfile
import unittest
from pathlib import Path

from src.config.diff import diff_programs
from src.config.loader import load_config
from src.config.models import ConfigError, GlobalConfig, ProgramConfig


class GlobalConfigValidationTests(unittest.TestCase):
    """Validation tests for the [global] configuration section."""

    def test_default_values(self):
        cfg = GlobalConfig()
        self.assertEqual(cfg.logfile, Path("/tmp/taskmaster.log"))
        self.assertEqual(cfg.loglevel, "INFO")
        self.assertEqual(cfg.user, "nobody")

    def test_valid_loglevel_case_insensitive(self):
        for level in ("debug", "INFO", "Warning", "error", "CRITICAL"):
            cfg = GlobalConfig(loglevel=level)
            self.assertEqual(cfg.loglevel, level.upper())

    def test_invalid_loglevel_raises(self):
        for invalid in ("VERBOSE", "TRACE", "", 123, None):
            with self.assertRaises(ConfigError):
                GlobalConfig(loglevel=invalid)

    def test_valid_logfile(self):
        cfg = GlobalConfig(logfile="/var/log/custom.log")
        self.assertEqual(cfg.logfile, Path("/var/log/custom.log"))

    def test_invalid_logfile_raises(self):
        for invalid in ("", "   ", 123, None):
            with self.assertRaises(ConfigError):
                GlobalConfig(logfile=invalid)

    def test_user_must_exist_and_not_be_root(self):
        with self.assertRaises(ConfigError):
            GlobalConfig(user="root")
        with self.assertRaises(ConfigError):
            GlobalConfig(user="definitely_nonexistent_user_xyz_123")
        with self.assertRaises(ConfigError):
            GlobalConfig(user="")


class ProgramConfigValidationTests(unittest.TestCase):
    """Validation tests for individual [program.<name>] parameters."""

    def test_minimal_valid_config_and_defaults(self):
        cfg = ProgramConfig(name="worker", cmd="/bin/sleep 10")
        self.assertEqual(cfg.name, "worker")
        self.assertEqual(cfg.cmd, "/bin/sleep 10")
        self.assertEqual(cfg.argv, ["/bin/sleep", "10"])
        self.assertEqual(cfg.numprocs, 1)
        self.assertTrue(cfg.autostart)
        self.assertEqual(cfg.autorestart, "unexpected")
        self.assertEqual(cfg.exitcodes, {0})
        self.assertEqual(cfg.starttime, 5)
        self.assertEqual(cfg.startretries, 3)
        self.assertEqual(cfg.stopsignal, signal.Signals.SIGTERM)
        self.assertEqual(cfg.stoptime, 10)
        self.assertIsNone(cfg.stdout)
        self.assertIsNone(cfg.stderr)
        self.assertEqual(cfg.env, {})
        self.assertIsNone(cfg.workingdir)
        self.assertIsNone(cfg.umask)

    def test_cmd_validation_and_shlex_splitting(self):
        cfg = ProgramConfig(name="w", cmd='echo "hello world" arg2')
        self.assertEqual(cfg.argv, ["echo", "hello world", "arg2"])

        for invalid in ("", "   ", 123, None):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd=invalid)

        # Unbalanced quotes should raise ConfigError
        with self.assertRaises(ConfigError):
            ProgramConfig(name="w", cmd='echo "unclosed quote')

    def test_numprocs_validation(self):
        cfg = ProgramConfig(name="w", cmd="sleep 1", numprocs=5)
        self.assertEqual(cfg.numprocs, 5)

        for invalid in (0, -1, True, False, "1", 1.5, None):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", numprocs=invalid)

    def test_autostart_validation(self):
        self.assertTrue(ProgramConfig(name="w", cmd="sleep 1", autostart=True).autostart)
        self.assertFalse(ProgramConfig(name="w", cmd="sleep 1", autostart=False).autostart)

        for invalid in ("true", 1, 0, None):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", autostart=invalid)

    def test_autorestart_validation(self):
        for mode in ("always", "never", "unexpected"):
            cfg = ProgramConfig(name="w", cmd="sleep 1", autorestart=mode)
            self.assertEqual(cfg.autorestart, mode)

        for invalid in ("sometimes", "ALWAYS", True, 1, None):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", autorestart=invalid)

    def test_exitcodes_validation(self):
        # Single int converted to set
        cfg1 = ProgramConfig(name="w", cmd="sleep 1", exitcodes=0)
        self.assertEqual(cfg1.exitcodes, {0})

        # List of ints converted to set
        cfg2 = ProgramConfig(name="w", cmd="sleep 1", exitcodes=[0, 1, 2])
        self.assertEqual(cfg2.exitcodes, {0, 1, 2})

        # Out of bounds or invalid types
        for invalid in (-1, 256, [-1], [256], [], ["0"], None):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", exitcodes=invalid)

    def test_starttime_startretries_stoptime_validation(self):
        cfg = ProgramConfig(name="w", cmd="sleep 1", starttime=0, startretries=0, stoptime=0)
        self.assertEqual(cfg.starttime, 0)
        self.assertEqual(cfg.startretries, 0)
        self.assertEqual(cfg.stoptime, 0)

        for invalid in (-1, "5", 1.5, None):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", starttime=invalid)
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", startretries=invalid)
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", stoptime=invalid)

    def test_stopsignal_validation(self):
        # Names with or without SIG prefix, case-insensitive
        for sig_name in ("TERM", "sigterm", "INT", "SIGINT", "hup", "KILL", "usr1", "quit"):
            cfg = ProgramConfig(name="w", cmd="sleep 1", stopsignal=sig_name)
            self.assertIsInstance(cfg.stopsignal, signal.Signals)

        self.assertEqual(
            ProgramConfig(name="w", cmd="sleep 1", stopsignal="INT").stopsignal,
            signal.Signals.SIGINT,
        )

        for invalid in ("NOTASIGNAL", "15", 15, "", None):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", stopsignal=invalid)

    def test_stdout_and_stderr_validation(self):
        cfg = ProgramConfig(name="w", cmd="sleep 1", stdout="./logs/out.log", stderr="./logs/err.log")
        self.assertEqual(cfg.stdout, Path("./logs/out.log"))
        self.assertEqual(cfg.stderr, Path("./logs/err.log"))

        for invalid in ("", "   ", 123):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", stdout=invalid)
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", stderr=invalid)

    def test_env_validation(self):
        cfg = ProgramConfig(name="w", cmd="sleep 1", env={"KEY": "VAL", "FOO": "BAR"})
        self.assertEqual(cfg.env, {"KEY": "VAL", "FOO": "BAR"})

        # Must be dict of str -> str
        for invalid in (
            {"KEY": 123},
            {123: "VAL"},
            ["KEY=VAL"],
            "KEY=VAL",
            None,
        ):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", env=invalid)

    def test_workingdir_validation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg = ProgramConfig(name="w", cmd="sleep 1", workingdir=tmp_dir)
            self.assertEqual(cfg.workingdir, Path(tmp_dir))

        # Non-existent directory
        with self.assertRaises(ConfigError):
            ProgramConfig(name="w", cmd="sleep 1", workingdir="/nonexistent/dir/xyz/123")

        for invalid in ("", "   ", 123):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", workingdir=invalid)

    def test_umask_validation(self):
        # Octal strings
        self.assertEqual(ProgramConfig(name="w", cmd="sleep 1", umask="022").umask, 0o22)
        self.assertEqual(ProgramConfig(name="w", cmd="sleep 1", umask="077").umask, 0o77)
        self.assertEqual(ProgramConfig(name="w", cmd="sleep 1", umask="000").umask, 0)
        self.assertEqual(ProgramConfig(name="w", cmd="sleep 1", umask="777").umask, 0o777)

        # Non-octal strings, out of range, or non-strings
        for invalid in ("888", "99", "089", "-1", "1000", 22, 0o22, True, []):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", umask=invalid)

    def test_depends_on_validation(self):
        # List of strings
        cfg = ProgramConfig(name="w", cmd="sleep 1", depends_on=["db", "redis"])
        self.assertEqual(cfg.depends_on, ["db", "redis"])

        # Single string gets converted to a list
        cfg_single = ProgramConfig(name="w", cmd="sleep 1", depends_on="database")
        self.assertEqual(cfg_single.depends_on, ["database"])

        # Single string with whitespace
        cfg_single_ws = ProgramConfig(name="w", cmd="sleep 1", depends_on="  database  ")
        self.assertEqual(cfg_single_ws.depends_on, ["database"])

        # Default is empty list
        self.assertEqual(ProgramConfig(name="w", cmd="sleep 1").depends_on, [])

        # Normalization of whitespace
        cfg_ws = ProgramConfig(name="w", cmd="sleep 1", depends_on=["  db  ", "redis "])
        self.assertEqual(cfg_ws.depends_on, ["db", "redis"])

        # Self-dependency is rejected (even as a string)
        with self.assertRaises(ConfigError) as ctx:
            ProgramConfig(name="w", cmd="sleep 1", depends_on="w ")
        self.assertIn("cannot depend on itself", str(ctx.exception))

        # Self-dependency is rejected (even with trailing whitespace)
        with self.assertRaises(ConfigError) as ctx:
            ProgramConfig(name="w", cmd="sleep 1", depends_on=["w "])
        self.assertIn("cannot depend on itself", str(ctx.exception))

        # Duplicate entries are rejected (even when normalized)
        with self.assertRaises(ConfigError) as ctx:
            ProgramConfig(name="w", cmd="sleep 1", depends_on=["db", "db "])
        self.assertIn("duplicate entries", str(ctx.exception))

        # Invalid types or invalid elements
        for invalid in (123, None, [""], ""):
            with self.assertRaises(ConfigError):
                ProgramConfig(name="w", cmd="sleep 1", depends_on=invalid)

        with self.assertRaises(ConfigError):
            ProgramConfig(name="w", cmd="sleep 1", depends_on=["   "])
        with self.assertRaises(ConfigError):
            ProgramConfig(name="w", cmd="sleep 1", depends_on=[123])


class LoadConfigTests(unittest.TestCase):
    """Tests for the load_config() TOML loader."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "test_config.toml"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_loads_current_repo_config_toml(self):
        """Ensure the actual repository config.toml parses without errors."""
        repo_config = Path("config.toml")
        if repo_config.exists():
            global_cfg, programs_cfg = load_config(str(repo_config))
            self.assertIsInstance(global_cfg, GlobalConfig)
            self.assertGreater(len(programs_cfg), 0)

    def test_loads_valid_toml_file(self):
        content = """
        [global]
        logfile = "/tmp/app.log"
        loglevel = "DEBUG"

        [program.srv]
        cmd = "/usr/bin/python3 -m http.server 8000"
        numprocs = 2
        autostart = false
        autorestart = "always"
        exitcodes = [0, 2]
        stopsignal = "INT"
        stoptime = 5
        stdout = "/tmp/srv.log"
        env = { PORT = "8000" }
        workingdir = "/tmp"
        umask = "027"
        """
        self.config_path.write_text(content)
        global_cfg, programs = load_config(str(self.config_path))

        self.assertEqual(global_cfg.logfile, Path("/tmp/app.log"))
        self.assertEqual(global_cfg.loglevel, "DEBUG")

        self.assertIn("srv", programs)
        srv = programs["srv"]
        self.assertEqual(srv.numprocs, 2)
        self.assertFalse(srv.autostart)
        self.assertEqual(srv.autorestart, "always")
        self.assertEqual(srv.exitcodes, {0, 2})
        self.assertEqual(srv.stopsignal, signal.Signals.SIGINT)
        self.assertEqual(srv.stoptime, 5)
        self.assertEqual(srv.stdout, Path("/tmp/srv.log"))
        self.assertEqual(srv.env, {"PORT": "8000"})
        self.assertEqual(srv.workingdir, Path("/tmp"))
        self.assertEqual(srv.umask, 0o27)

    def test_nonexistent_file_raises_config_error(self):
        with self.assertRaises(ConfigError):
            load_config("/nonexistent/file/taskmaster.toml")

    def test_invalid_toml_syntax_raises_config_error(self):
        self.config_path.write_text("this is not [ valid toml =")
        with self.assertRaises(ConfigError):
            load_config(str(self.config_path))

    def test_unknown_top_level_section_raises_config_error(self):
        content = """
        [unknown_section]
        key = "value"

        [program.w]
        cmd = "sleep 1"
        """
        self.config_path.write_text(content)
        with self.assertRaises(ConfigError):
            load_config(str(self.config_path))

    def test_missing_or_empty_programs_section_raises_config_error(self):
        # No program section at all
        self.config_path.write_text("[global]\nloglevel = 'INFO'\n")
        with self.assertRaises(ConfigError):
            load_config(str(self.config_path))

        # Program section is empty
        self.config_path.write_text("[global]\nloglevel = 'INFO'\n[program]\n")
        with self.assertRaises(ConfigError):
            load_config(str(self.config_path))

    def test_invalid_program_structure_raises_config_error(self):
        # Program value is not a dict
        self.config_path.write_text("[program]\nw = 'just a string'\n")
        with self.assertRaises(ConfigError):
            load_config(str(self.config_path))

    def test_unknown_keys_in_sections_raise_config_error(self):
        # Unknown key in global
        content = """
        [global]
        unknown_global_key = 123

        [program.w]
        cmd = "sleep 1"
        """
        self.config_path.write_text(content)
        with self.assertRaises(ConfigError):
            load_config(str(self.config_path))

        # Unknown key in program
        content = """
        [program.w]
        cmd = "sleep 1"
        unknown_prog_key = "abc"
        """
        self.config_path.write_text(content)
        with self.assertRaises(ConfigError):
            load_config(str(self.config_path))

    def test_depends_on_valid_dependency_chain(self):
        content = """
        [program.a]
        cmd = "sleep 1"

        [program.b]
        cmd = "sleep 1"
        depends_on = ["a"]

        [program.c]
        cmd = "sleep 1"
        depends_on = ["b"]
        """
        self.config_path.write_text(content)
        _, progs = load_config(str(self.config_path))
        self.assertEqual(progs["c"].depends_on, ["b"])
        self.assertEqual(progs["b"].depends_on, ["a"])
        self.assertEqual(progs["a"].depends_on, [])

    def test_depends_on_unknown_program_raises(self):
        content = """
        [program.web]
        cmd = "sleep 1"
        depends_on = ["database"]
        """
        self.config_path.write_text(content)
        with self.assertRaises(ConfigError) as ctx:
            load_config(str(self.config_path))
        self.assertIn("depends on unknown program 'database'", str(ctx.exception))

    def test_depends_on_two_cycle_raises(self):
        content = """
        [program.a]
        cmd = "sleep 1"
        depends_on = ["b"]

        [program.b]
        cmd = "sleep 1"
        depends_on = ["a"]
        """
        self.config_path.write_text(content)
        with self.assertRaises(ConfigError) as ctx:
            load_config(str(self.config_path))
        self.assertIn("dependency cycle detected:", str(ctx.exception))
        self.assertIn("a -> b -> a", str(ctx.exception))

    def test_depends_on_three_cycle_raises(self):
        content = """
        [program.a]
        cmd = "sleep 1"
        depends_on = ["b"]

        [program.b]
        cmd = "sleep 1"
        depends_on = ["c"]

        [program.c]
        cmd = "sleep 1"
        depends_on = ["a"]
        """
        self.config_path.write_text(content)
        with self.assertRaises(ConfigError) as ctx:
            load_config(str(self.config_path))
        self.assertIn("dependency cycle detected:", str(ctx.exception))
        self.assertIn("a -> b -> c -> a", str(ctx.exception))

    def test_depends_on_diamond_dag_succeeds(self):
        content = """
        [program.d]
        cmd = "sleep 1"

        [program.b]
        cmd = "sleep 1"
        depends_on = ["d"]

        [program.c]
        cmd = "sleep 1"
        depends_on = ["d"]

        [program.a]
        cmd = "sleep 1"
        depends_on = ["b", "c"]
        """
        self.config_path.write_text(content)
        _, progs = load_config(str(self.config_path))
        self.assertEqual(progs["a"].depends_on, ["b", "c"])

    def test_depends_on_cycle_with_prefix_chain(self):
        content = """
        [program.entry]
        cmd = "sleep 1"
        depends_on = ["p1"]

        [program.p1]
        cmd = "sleep 1"
        depends_on = ["p2"]

        [program.p2]
        cmd = "sleep 1"
        depends_on = ["p1"]
        """
        self.config_path.write_text(content)
        with self.assertRaises(ConfigError) as ctx:
            load_config(str(self.config_path))
        self.assertIn("dependency cycle detected: p1 -> p2 -> p1", str(ctx.exception))

    def test_load_config_orders_programs_in_topological_launch_order(self):
        content = """
        [program.frontend]
        cmd = "sleep 1"
        depends_on = ["backend"]

        [program.cache]
        cmd = "sleep 1"
        depends_on = ["db"]

        [program.backend]
        cmd = "sleep 1"
        depends_on = ["db"]

        [program.db]
        cmd = "sleep 1"
        """
        self.config_path.write_text(content)
        _, progs = load_config(str(self.config_path))
        keys = list(progs.keys())
        self.assertLess(keys.index("db"), keys.index("cache"))
        self.assertLess(keys.index("db"), keys.index("backend"))
        self.assertLess(keys.index("backend"), keys.index("frontend"))

    def test_load_config_diamond_dag_launch_order(self):
        content = """
        [program.a]
        cmd = "sleep 1"
        depends_on = ["b", "c"]

        [program.b]
        cmd = "sleep 1"
        depends_on = ["d"]

        [program.c]
        cmd = "sleep 1"
        depends_on = ["d"]

        [program.d]
        cmd = "sleep 1"
        """
        self.config_path.write_text(content)
        _, progs = load_config(str(self.config_path))
        keys = list(progs.keys())
        self.assertEqual(keys[0], "d")
        self.assertEqual(keys[-1], "a")
        self.assertIn(keys[1], {"b", "c"})
        self.assertIn(keys[2], {"b", "c"})

    def test_resolve_dependencies_returns_topological_order(self):
        from src.config.loader import _resolve_dependencies

        cfgs = {
            "web": ProgramConfig(name="web", cmd="sleep 1", depends_on=["api"]),
            "api": ProgramConfig(name="api", cmd="sleep 1", depends_on=["db"]),
            "db": ProgramConfig(name="db", cmd="sleep 1"),
        }
        order = _resolve_dependencies(cfgs)
        self.assertEqual(order, ["db", "api", "web"])


class DiffProgramsTests(unittest.TestCase):
    """Tests for diff_programs() comparison logic."""

    def setUp(self):
        self.prog1 = ProgramConfig(name="p1", cmd="sleep 10")
        self.prog2 = ProgramConfig(name="p2", cmd="sleep 20")
        self.prog3 = ProgramConfig(name="p3", cmd="sleep 30")

    def test_diff_added_and_removed(self):
        old = {"p1": self.prog1, "p2": self.prog2}
        new = {"p2": self.prog2, "p3": self.prog3}

        diff = diff_programs(old, new)
        self.assertEqual(diff.added, {"p3": self.prog3})
        self.assertEqual(diff.removed, {"p1"})
        self.assertEqual(diff.unchanged, {"p2"})
        self.assertEqual(diff.changed, {})

    def test_diff_changed_detects_field_modifications(self):
        p1_modified = ProgramConfig(name="p1", cmd="sleep 99")  # modified cmd
        old = {"p1": self.prog1}
        new = {"p1": p1_modified}

        diff = diff_programs(old, new)
        self.assertEqual(diff.added, {})
        self.assertEqual(diff.removed, set())
        self.assertEqual(diff.unchanged, set())
        self.assertEqual(diff.changed, {"p1": p1_modified})

    def test_diff_changed_detects_depends_on_modifications(self):
        p1_with_dep = ProgramConfig(name="p1", cmd="sleep 10", depends_on=["p2"])
        old = {"p1": self.prog1}
        new = {"p1": p1_with_dep}

        diff = diff_programs(old, new)
        self.assertEqual(diff.changed, {"p1": p1_with_dep})
        self.assertEqual(diff.unchanged, set())

    def test_diff_unchanged_when_configs_are_identical(self):
        old = {"p1": self.prog1, "p2": self.prog2}
        new = {"p1": ProgramConfig(name="p1", cmd="sleep 10"), "p2": self.prog2}

        diff = diff_programs(old, new)
        self.assertEqual(diff.added, {})
        self.assertEqual(diff.removed, set())
        self.assertEqual(diff.unchanged, {"p1", "p2"})
        self.assertEqual(diff.changed, {})

    def test_diff_programs_preserves_new_order_for_added_and_changed(self):
        old = {"p1": self.prog1}
        p1_mod = ProgramConfig(name="p1", cmd="sleep 99")
        p2 = ProgramConfig(name="p2", cmd="sleep 20")
        p3 = ProgramConfig(name="p3", cmd="sleep 30")
        new = {"p3": p3, "p1": p1_mod, "p2": p2}

        diff = diff_programs(old, new)
        self.assertEqual(list(diff.added.keys()), ["p3", "p2"])
        self.assertEqual(list(diff.changed.keys()), ["p1"])


if __name__ == "__main__":
    unittest.main()

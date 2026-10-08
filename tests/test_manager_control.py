"""Linux unit tests for control-shell operations on ProcessManager."""
# python3 -m unittest discover -s tests -v

import itertools
import signal
import unittest
from unittest.mock import Mock, patch

from src.config import ProgramConfig
from src.core.manager import DependencyNotReadyError, ProcessManager, ProgramNotFoundError
from src.process.group import ProcessGroup
from src.process.process import Process
from src.process.state import ProcessState, StopReason


def program(name: str = "worker", numprocs: int = 1) -> ProgramConfig:
    return ProgramConfig(
        name=name,
        cmd="/bin/sleep 60",
        autostart=False,
        numprocs=numprocs,
    )


class ProcessManagerTargetTests(unittest.TestCase):
    def setUp(self):
        self.manager = ProcessManager({"worker": program(numprocs=2)})
        self.group = self.manager.groups["worker"]

    def test_resolve_target_handles_all_group_and_one_instance(self):
        self.assertEqual(self.manager._resolve_target("all"), [(self.group, None)])
        self.assertEqual(self.manager._resolve_target("worker"), [(self.group, None)])
        self.assertEqual(
            self.manager._resolve_target("worker_1"),
            [(self.group, [self.group.processes[1]])],
        )

    def test_group_name_has_priority_over_instance_name(self):
        manager = ProcessManager(
            {
                "worker": program(numprocs=2),
                "worker_0": program(name="worker_0"),
            }
        )

        resolved_group, resolved_processes = manager._resolve_target("worker_0")[0]
        self.assertIs(resolved_group, manager.groups["worker_0"])
        self.assertIsNone(resolved_processes)

    def test_unknown_or_invalid_target_raises(self):
        with self.assertRaises(ProgramNotFoundError):
            self.manager._resolve_target("missing")
        with self.assertRaises(ProgramNotFoundError):
            self.manager._resolve_target("")

    def test_pid_reported_in_active_states_and_none_in_terminal(self):
        proc = self.group.processes[0]
        proc.popen = Mock(pid=4321)

        for state in (ProcessState.STARTING, ProcessState.RUNNING, ProcessState.STOPPING):
            proc.state = state
            self.assertEqual(proc.pid, 4321)

        for state in (ProcessState.STOPPED, ProcessState.BACKOFF, ProcessState.EXITED, ProcessState.FATAL):
            proc.state = state
            self.assertIsNone(proc.pid)

    def test_status_for_instance_contains_only_that_instance(self):
        worker_0, worker_1 = self.group.processes
        worker_0.state = ProcessState.RUNNING
        worker_0.popen = Mock(pid=100)
        worker_1.state = ProcessState.STOPPED

        status = self.manager.status("worker_1")

        self.assertEqual(status[0]["name"], "worker")
        self.assertEqual(
            status[0]["processes"],
            [
                {
                    "name": "worker_1",
                    "state": "STOPPED",
                    "pid": None,
                    "uptime_seconds": None,
                    "exit_code": None,
                    "stop_reason": "not started",
                }
            ],
        )


class ProcessManagerCommandTests(unittest.TestCase):
    def setUp(self):
        self.manager = ProcessManager({"worker": program(numprocs=2)})
        self.group = self.manager.groups["worker"]
        self.worker_1 = self.group.processes[1]
        self.group.start = Mock()
        self.group.stop = Mock()
        self.group.restart = Mock()

    def test_group_command_passes_none_to_process_group(self):
        self.assertEqual(self.manager.start("worker"), ["worker_0", "worker_1"])
        self.assertEqual(self.manager.stop("worker"), ["worker_0", "worker_1"])
        self.assertEqual(self.manager.restart("worker"), ["worker_0", "worker_1"])

        self.group.start.assert_called_once_with(None)
        self.group.stop.assert_called_once_with(None)
        self.group.restart.assert_called_once_with(None)

    def test_process_command_passes_only_the_selected_instance(self):
        self.assertEqual(self.manager.start("worker_1"), ["worker_1"])
        self.assertEqual(self.manager.stop("worker_1"), ["worker_1"])
        self.assertEqual(self.manager.restart("worker_1"), ["worker_1"])

        self.group.start.assert_called_once_with([self.worker_1])
        self.group.stop.assert_called_once_with([self.worker_1])
        self.group.restart.assert_called_once_with([self.worker_1])


class ProcessGroupAutostartTests(unittest.TestCase):
    def test_start_if_autostart_when_disabled_does_not_start(self):
        cfg = ProgramConfig(name="worker", cmd="/bin/sleep 10", autostart=False)
        group = ProcessGroup(name="worker", config=cfg)
        group.create_processes()
        group.start = Mock()

        group.start_if_autostart()
        group.start.assert_not_called()

    def test_start_if_autostart_when_fresh_calls_start(self):
        cfg = ProgramConfig(name="worker", cmd="/bin/sleep 10", autostart=True)
        group = ProcessGroup(name="worker", config=cfg)
        group.create_processes()
        group.start = Mock()

        group.start_if_autostart()
        group.start.assert_called_once_with()

    def test_start_if_autostart_does_not_start_if_processes_not_fresh(self):
        cfg = ProgramConfig(name="worker", cmd="/bin/sleep 10", autostart=True)
        group = ProcessGroup(name="worker", config=cfg)
        group.create_processes()
        group.processes[0].state = ProcessState.RUNNING
        group.start = Mock()

        group.start_if_autostart()
        group.start.assert_not_called()

    def test_is_running_property(self):
        cfg = ProgramConfig(name="worker", cmd="/bin/sleep 10", numprocs=2)
        group = ProcessGroup(name="worker", config=cfg)
        self.assertFalse(group.is_running)

        group.create_processes()
        self.assertFalse(group.is_running)

        group.processes[0].state = ProcessState.RUNNING
        self.assertFalse(group.is_running)

        group.processes[1].state = ProcessState.RUNNING
        self.assertTrue(group.is_running)


class ProcessGroupRestartTests(unittest.TestCase):
    def test_restart_of_one_process_waits_for_its_own_terminal_state(self):
        group = ProcessGroup(name="worker", config=program(numprocs=2))
        group.create_processes()
        restarting, sibling = group.processes
        restarting.state = ProcessState.RUNNING
        restarting.send_stop_signal = Mock()
        restarting.start = Mock()
        sibling.start = Mock()

        group.restart([restarting])

        self.assertEqual(group.pending_restarts, {"worker_0"})
        restarting.send_stop_signal.assert_called_once_with()
        restarting.start.assert_not_called()

        restarting.state = ProcessState.STOPPED
        group.tick()

        restarting.start.assert_called_once_with(manual=True)
        sibling.start.assert_not_called()
        self.assertEqual(group.pending_restarts, set())

    def test_group_restart_starts_each_process_as_it_becomes_terminal(self):
        group = ProcessGroup(name="worker", config=program(numprocs=2))
        group.create_processes()
        stopped, running = group.processes
        stopped.state = ProcessState.STOPPED
        running.state = ProcessState.RUNNING
        stopped.start = Mock()
        running.start = Mock()
        running.send_stop_signal = Mock()

        group.restart()
        group.tick()

        stopped.start.assert_called_once_with(manual=True)
        running.start.assert_not_called()
        self.assertEqual(group.pending_restarts, {"worker_1"})

        running.state = ProcessState.STOPPED
        group.tick()

        running.start.assert_called_once_with(manual=True)
        self.assertEqual(group.pending_restarts, set())

    def test_stop_cancels_only_the_targeted_pending_restart(self):
        group = ProcessGroup(name="worker", config=program(numprocs=2))
        group.create_processes()
        first, second = group.processes

        group.restart([first, second])
        group.stop([first])

        self.assertEqual(group.pending_restarts, {"worker_1"})

    def test_manual_start_recovers_fatal_process(self):
        group = ProcessGroup(name="worker", config=program())
        group.create_processes()
        proc = group.processes[0]
        proc.state = ProcessState.FATAL

        with patch("src.process.process.subprocess.Popen") as popen:
            popen.return_value.pid = 99
            group.start([proc])

        self.assertEqual(proc.state, ProcessState.STARTING)
        self.assertFalse(proc.shutting_down)
        self.assertEqual(proc.try_count, 1)


class ProcessSignallingTests(unittest.TestCase):
    def setUp(self):
        self.proc = Process(name="worker", config=program())
        self.proc.popen = Mock(pid=1234)

    @patch("src.process.process.os.killpg")
    def test_send_stop_signal_uses_killpg_on_process_group(self, mock_killpg):
        self.proc.state = ProcessState.RUNNING
        self.proc.send_stop_signal()

        mock_killpg.assert_called_once_with(1234, self.proc.config.stopsignal)
        self.assertEqual(self.proc.state, ProcessState.STOPPING)
        self.assertIsNotNone(self.proc.stop_time)

    @patch("src.process.process.os.killpg")
    def test_kill_uses_killpg_sigkill(self, mock_killpg):
        self.proc.state = ProcessState.STOPPING

        self.proc.kill()
        mock_killpg.assert_called_once_with(1234, signal.SIGKILL)


class ProcessDependencyControlTests(unittest.TestCase):
    def setUp(self):
        self.db_cfg = ProgramConfig(
            name="db",
            cmd="/bin/sleep 60",
            autostart=True,
            starttime=5,
        )
        self.web_cfg = ProgramConfig(
            name="web",
            cmd="/bin/sleep 60",
            autostart=True,
            depends_on=["db"],
        )

    def test_autostart_with_dependency_delays_start_until_running(self):
        with patch("src.process.process.subprocess.Popen") as mock_popen:
            mock_popen.return_value.pid = 100
            mock_popen.return_value.poll.return_value = None
            manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
            manager.start_all()

            db_proc = manager.groups["db"].processes[0]
            web_proc = manager.groups["web"].processes[0]

            self.assertEqual(db_proc.state, ProcessState.STARTING)
            self.assertEqual(web_proc.state, ProcessState.STOPPED)
            self.assertEqual(web_proc.stop_reason, StopReason.NOT_STARTED)

    def test_dependency_reaches_running_triggers_autostart(self):
        with patch("src.process.process.subprocess.Popen") as mock_popen:
            pid_counter = itertools.count(100)
            mock_popen.side_effect = lambda *args, **kwargs: Mock(
                pid=next(pid_counter),
                poll=Mock(return_value=None),
            )
            manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
            manager.start_all()

            db_proc = manager.groups["db"].processes[0]
            web_proc = manager.groups["web"].processes[0]

            # Simulate db reaching RUNNING
            db_proc.state = ProcessState.RUNNING

            # Advance event loop tick
            manager.check_children()

            self.assertEqual(web_proc.state, ProcessState.STARTING)
            self.assertNotEqual(db_proc.pid, web_proc.pid)

    def test_dependency_with_numprocs_two_waits_until_both_reach_running(self):
        db_cfg_2 = ProgramConfig(
            name="db",
            cmd="/bin/sleep 60",
            numprocs=2,
            autostart=True,
            starttime=5,
        )
        with patch("src.process.process.subprocess.Popen") as mock_popen:
            pid_counter = itertools.count(100)
            mock_popen.side_effect = lambda *args, **kwargs: Mock(
                pid=next(pid_counter),
                poll=Mock(return_value=None),
            )
            manager = ProcessManager({"db": db_cfg_2, "web": self.web_cfg})
            manager.start_all()

            db_procs = manager.groups["db"].processes
            web_proc = manager.groups["web"].processes[0]

            self.assertNotEqual(db_procs[0].pid, db_procs[1].pid)

            # Only first instance reaches RUNNING
            db_procs[0].state = ProcessState.RUNNING
            db_procs[1].state = ProcessState.STARTING

            manager.check_children()
            self.assertEqual(web_proc.state, ProcessState.STOPPED)
            self.assertEqual(web_proc.stop_reason, StopReason.NOT_STARTED)

            # Second instance reaches RUNNING
            db_procs[1].state = ProcessState.RUNNING
            manager.check_children()
            self.assertEqual(web_proc.state, ProcessState.STARTING)
            self.assertIsNotNone(web_proc.pid)
            self.assertNotEqual(web_proc.pid, db_procs[0].pid)
            self.assertNotEqual(web_proc.pid, db_procs[1].pid)

    def test_manual_start_when_dependency_not_running_raises_dependency_not_ready(self):
        self.db_cfg.autostart = False
        self.web_cfg.autostart = False

        manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
        with self.assertRaises(DependencyNotReadyError) as ctx:
            manager.start("web")

        self.assertIn("cannot start 'web'", str(ctx.exception))
        self.assertIn("dependencies not RUNNING (db)", str(ctx.exception))

    def test_manual_restart_when_dependency_not_running_raises_dependency_not_ready(self):
        self.db_cfg.autostart = False
        self.web_cfg.autostart = False

        manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
        with self.assertRaises(DependencyNotReadyError) as ctx:
            manager.restart("web")

        self.assertIn("cannot restart 'web'", str(ctx.exception))
        self.assertIn("dependencies not RUNNING", str(ctx.exception))

    def test_manual_start_when_dependency_running_succeeds(self):
        self.db_cfg.autostart = False
        self.web_cfg.autostart = False

        manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
        db_proc = manager.groups["db"].processes[0]
        db_proc.state = ProcessState.RUNNING

        with patch("src.process.process.subprocess.Popen") as mock_popen:
            mock_popen.return_value.pid = 100
            mock_popen.return_value.poll.return_value = None
            result = manager.start("web")

        self.assertEqual(result, ["web"])
        web_proc = manager.groups["web"].processes[0]
        self.assertEqual(web_proc.state, ProcessState.STARTING)

    def test_start_all_skips_groups_with_unready_dependencies(self):
        self.db_cfg.autostart = False
        self.web_cfg.autostart = False

        manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
        with patch("src.process.process.subprocess.Popen") as mock_popen:
            mock_popen.return_value.pid = 100
            mock_popen.return_value.poll.return_value = None
            started = manager.start("all")

        self.assertIn("db", started)
        self.assertNotIn("web", started)
        self.assertEqual(manager.groups["db"].processes[0].state, ProcessState.STARTING)
        self.assertEqual(manager.groups["web"].processes[0].state, ProcessState.STOPPED)

    def test_explicitly_stopped_group_is_not_re_autostarted(self):
        with patch("src.process.process.subprocess.Popen") as mock_popen:
            pid_counter = itertools.count(100)
            mock_popen.side_effect = lambda *args, **kwargs: Mock(
                pid=next(pid_counter),
                poll=Mock(return_value=None),
            )
            manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
            manager.start_all()

            db_proc = manager.groups["db"].processes[0]
            web_proc = manager.groups["web"].processes[0]

            db_proc.state = ProcessState.RUNNING
            manager.check_children()
            self.assertEqual(web_proc.state, ProcessState.STARTING)

            # Web becomes RUNNING, then is stopped by user
            web_proc.state = ProcessState.RUNNING
            manager.stop("web")
            self.assertEqual(web_proc.state, ProcessState.STOPPING)

            # Web exits cleanly
            web_proc.poll = Mock(return_value=0)
            manager.check_children()
            self.assertEqual(web_proc.state, ProcessState.STOPPED)
            self.assertEqual(web_proc.stop_reason, StopReason.BY_REQUEST)

            # Subsequent tick should NOT restart web
            manager.check_children()
            self.assertEqual(web_proc.state, ProcessState.STOPPED)
            self.assertEqual(web_proc.stop_reason, StopReason.BY_REQUEST)

    def test_daemon_dispatch_ipc_translates_dependency_not_ready_to_request_error(self):
        from src.core.daemon import TaskmasterDaemon
        from src.ipc.protocol import RequestError

        self.db_cfg.autostart = False
        self.web_cfg.autostart = False
        manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})

        daemon = TaskmasterDaemon.__new__(TaskmasterDaemon)
        daemon.manager = manager

        with self.assertRaises(RequestError) as ctx:
            daemon.dispatch_ipc({"command": "start", "target": "web"})

        self.assertEqual(ctx.exception.code, "COMMAND_FAILED")
        self.assertIn("cannot start 'web'", str(ctx.exception))
        self.assertIn("dependencies not RUNNING", str(ctx.exception))

    def test_pending_autostart_tracking_lifecycle(self):
        with patch("src.process.process.subprocess.Popen") as mock_popen:
            pid_counter = itertools.count(100)
            mock_popen.side_effect = lambda *args, **kwargs: Mock(
                pid=next(pid_counter),
                poll=Mock(return_value=None),
            )
            manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
            manager.start_all()

            # db starts immediately, web is deferred into pending_autostart
            self.assertEqual(manager.pending_autostart, {"web"})

            # While db is still STARTING, check_children keeps web in pending
            manager.check_children()
            self.assertEqual(manager.pending_autostart, {"web"})
            self.assertEqual(manager.groups["web"].processes[0].state, ProcessState.STOPPED)

            # Once db reaches RUNNING, check_children triggers autostart and clears pending
            manager.groups["db"].processes[0].state = ProcessState.RUNNING
            manager.check_children()
            self.assertEqual(manager.pending_autostart, set())
            self.assertEqual(manager.groups["web"].processes[0].state, ProcessState.STARTING)

    def test_pending_autostart_discarded_on_manual_stop_and_stop_all(self):
        with patch("src.process.process.subprocess.Popen"):
            manager = ProcessManager({"db": self.db_cfg, "web": self.web_cfg})
            manager.start_all()
            self.assertIn("web", manager.pending_autostart)

            manager.stop("web")
            self.assertNotIn("web", manager.pending_autostart)

            manager.pending_autostart.add("web")
            manager.stop_all()
            self.assertEqual(manager.pending_autostart, set())


if __name__ == "__main__":
    unittest.main()

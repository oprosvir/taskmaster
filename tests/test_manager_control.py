"""Linux unit tests for control-shell operations on ProcessManager."""
# PYTHONPATH=src python3 -m unittest discover -s tests -v

import unittest
from unittest.mock import Mock, patch

from src.config import ProgramConfig
from src.core.manager import ProcessManager, ProgramNotFoundError
from src.process.fsm import ProcessState
from src.process.group import ProcessGroup


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
        with self.assertRaises(ValueError):
            self.manager._resolve_target("")

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
        self.assertEqual(self.manager.start("worker"), ["worker"])
        self.assertEqual(self.manager.stop("worker"), ["worker"])
        self.assertEqual(self.manager.restart("worker"), ["worker"])

        self.group.start.assert_called_once_with(None)
        self.group.stop.assert_called_once_with(None)
        self.group.restart.assert_called_once_with(None)

    def test_process_command_passes_only_the_selected_instance(self):
        self.assertEqual(self.manager.start("worker_1"), ["worker"])
        self.assertEqual(self.manager.stop("worker_1"), ["worker"])
        self.assertEqual(self.manager.restart("worker_1"), ["worker"])

        self.group.start.assert_called_once_with([self.worker_1])
        self.group.stop.assert_called_once_with([self.worker_1])
        self.group.restart.assert_called_once_with([self.worker_1])


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

        with patch("process.process.subprocess.Popen") as popen:
            popen.return_value.pid = 99
            group.start([proc])

        self.assertEqual(proc.state, ProcessState.STARTING)
        self.assertFalse(proc.shutting_down)
        self.assertEqual(proc.try_count, 1)


if __name__ == "__main__":
    unittest.main()

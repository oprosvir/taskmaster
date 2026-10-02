"""Tests for the taskmasterctl input parser."""

import unittest

from src.ipc.parser import Command, ParseError, parse_line


class ParseLineTests(unittest.TestCase):
    def test_blank_line_returns_none(self):
        self.assertIsNone(parse_line(""))
        self.assertIsNone(parse_line("    "))
        self.assertIsNone(parse_line("\t  \n"))

    def test_command_name_is_case_insensitive(self):
        self.assertEqual(parse_line("STATUS"), Command("status", None))
        self.assertEqual(parse_line("Stop nginx"), Command("stop", "nginx"))

    def test_quoted_target_with_spaces(self):
        self.assertEqual(parse_line('stop "my prog"'), Command("stop", "my prog"))

    def test_unbalanced_quotes_raise_parse_error(self):
        with self.assertRaises(ParseError):
            parse_line('stop "unclosed')

    def test_unknown_command_raises_parse_error(self):
        with self.assertRaises(ParseError):
            parse_line("explode")

    def test_status_accepts_zero_or_one_argument(self):
        self.assertEqual(parse_line("status"), Command("status", None))
        self.assertEqual(parse_line("status nginx"), Command("status", "nginx"))
        with self.assertRaises(ParseError):
            parse_line("status nginx extra")

    def test_target_required_commands_reject_zero_or_two_args(self):
        for name in ("start", "stop", "restart"):
            with self.subTest(command=name):
                with self.assertRaises(ParseError):
                    parse_line(name)
                with self.assertRaises(ParseError):
                    parse_line(f"{name} a b")
                self.assertEqual(parse_line(f"{name} nginx"), Command(name, "nginx"))

    def test_no_argument_commands_reject_any_argument(self):
        for name in ("reload", "shutdown", "help", "quit"):
            with self.subTest(command=name):
                self.assertEqual(parse_line(name), Command(name, None))
                with self.assertRaises(ParseError):
                    parse_line(f"{name} nginx")

    def test_empty_string_argument_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_line('stop ""')


if __name__ == "__main__":
    unittest.main()

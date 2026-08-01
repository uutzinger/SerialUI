import unittest

from helpers.General_helper import build_text_payload


class CommandPayloadTests(unittest.TestCase):
    def test_single_command_has_selected_terminator(self):
        self.assertEqual(build_text_payload(".", b"\r\n"), b".\r\n")
        self.assertEqual(build_text_payload("z", b"\n"), b"z\n")

    def test_multiline_submission_terminates_each_command_once(self):
        self.assertEqual(
            build_text_payload("zB\nzS", b"\r\n"),
            b"zB\r\nzS\r\n",
        )
        self.assertEqual(build_text_payload("zB\n", b"\r\n"), b"zB\r\n")

    def test_all_configured_terminators_are_honored_exactly(self):
        self.assertEqual(build_text_payload(">", b"\r"), b">\r")
        self.assertEqual(build_text_payload("<", b"\n\r"), b"<\n\r")
        self.assertEqual(build_text_payload("", b"\r"), b"\r")

    def test_none_adds_no_terminator(self):
        self.assertEqual(build_text_payload("zS", b""), b"zS")
        self.assertEqual(build_text_payload("", b""), b"")
        self.assertEqual(build_text_payload("zB\r\nzS", b""), b"zB\r\nzS")


if __name__ == "__main__":
    unittest.main()

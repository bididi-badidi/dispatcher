from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from dispatcher.logging_setup import (
    DispatcherFormatter,
    configure_logging,
    redact_state,
)


class LoggingSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("dispatcher")
        self.original_handlers = list(self.logger.handlers)
        self.original_level = self.logger.level
        self.original_propagate = self.logger.propagate
        self.logger.handlers.clear()

    def tearDown(self) -> None:
        self.logger.handlers.clear()
        self.logger.handlers.extend(self.original_handlers)
        self.logger.setLevel(self.original_level)
        self.logger.propagate = self.original_propagate

    def test_configure_logging_reads_env_level(self) -> None:
        with patch.dict("os.environ", {"DISPATCHER_LOG_LEVEL": "DEBUG"}):
            configure_logging()

        self.assertEqual(self.logger.level, logging.DEBUG)

    def test_configure_logging_is_idempotent(self) -> None:
        configure_logging("INFO")
        configure_logging("WARNING")

        self.assertEqual(len(self.logger.handlers), 1)
        self.assertEqual(self.logger.level, logging.WARNING)

    def test_dispatcher_formatter_appends_extra_fields_as_json(self) -> None:
        record = logging.LogRecord(
            "dispatcher.test",
            logging.INFO,
            __file__,
            1,
            "message",
            (),
            None,
        )
        record.key = "value"

        output = DispatcherFormatter("%(levelname)s %(message)s").format(record)

        self.assertEqual(output, 'INFO message {"key": "value"}')

    def test_redact_state_json_safes_paths_and_truncates_large_fields(self) -> None:
        state = {
            "worktree": Path("/tmp/worktree"),
            "plan_content": "x" * 600,
            "quality_review_feedback": "y" * 600,
        }

        redacted = redact_state(state)

        self.assertEqual(redacted["worktree"], "/tmp/worktree")
        self.assertEqual(redacted["plan_content"], "x" * 500)
        self.assertEqual(redacted["quality_review_feedback"], "y" * 500)

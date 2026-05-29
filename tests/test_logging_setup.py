from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from dispatcher.logging_setup import configure_logging


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

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from dispatcher.session_log import (
    FlowTrace,
    compose_rollup,
    extract_agent_output,
    strip_thinking,
)


class SessionLogTests(unittest.TestCase):
    def test_strip_thinking_removes_supported_tags(self) -> None:
        text = (
            "Visible\n"
            "<thinking>hidden\nthought</thinking>\n"
            "<THINK>also hidden</THINK>\n"
            "<reasoning>private</reasoning>\n"
            "VERDICT: approved\n"
        )

        cleaned = strip_thinking(text)

        self.assertEqual(cleaned, "Visible\n\nVERDICT: approved")

    def test_strip_thinking_collapses_blank_lines_and_keeps_plain_words(self) -> None:
        text = "First\n\n<thinking>hidden</thinking>\n\n\nSecond thinking aloud"

        cleaned = strip_thinking(text)

        self.assertEqual(cleaned, "First\n\nSecond thinking aloud")

    def test_extract_agent_output_returns_stdout_only(self) -> None:
        log = "$ cmd\n\n[version]\n1.0\n\n[stdout]\nhello\n\n[stderr]\nnoise"

        self.assertEqual(extract_agent_output(log), "hello")

    def test_extract_agent_output_returns_input_without_markers(self) -> None:
        self.assertEqual(extract_agent_output("DRY RUN"), "DRY RUN")

    def test_flow_trace_renders_iterations_and_status(self) -> None:
        async def scenario() -> str:
            flow = FlowTrace()
            await flow.enter("START")
            await flow.enter("build", iteration=1)
            await flow.exit("build")
            await flow.enter("route_reviews")
            await flow.exit("route_reviews", status="changes_requested")
            await flow.enter("build", iteration=2)
            await flow.exit("build")
            await flow.exit("END")
            return flow.render()

        rendered = asyncio.run(scenario())

        self.assertIn("\u2192 START", rendered)
        self.assertIn("\u2192 build (iteration 1)", rendered)
        self.assertIn("\u2192 route_reviews [changes_requested]", rendered)
        self.assertIn("\u2192 build (iteration 2)", rendered)
        self.assertTrue(rendered.endswith("\u21e5 END"))

    def test_compose_rollup_adds_flow_conversation_and_raw_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan = root / "issue-7-plan.log"
            build = root / "issue-7-build.log"
            plan.write_text(
                "$ plan\n\n[version]\n1\n\n[stdout]\n"
                "<thinking>hide me</thinking>\nPlan output\n\n[stderr]\nsecret",
                encoding="utf-8",
            )
            build.write_text("DRY RUN: build\n\n[version]\n1\n", encoding="utf-8")

            body = compose_rollup(
                "\u2192 START\n\u21e5 END",
                [("plan", plan), ("build", build)],
            ).decode("utf-8")

        self.assertLess(body.index("=== flow ==="), body.index("=== conversation ==="))
        self.assertLess(body.index("=== conversation ==="), body.index("=== raw ==="))
        self.assertIn("--- plan ---\nPlan output", body)
        self.assertIn("--- build ---\nDRY RUN: build", body)
        self.assertNotIn("--- plan ---\n<thinking>", body)
        self.assertIn("<thinking>hide me</thinking>", body.split("=== raw ===", 1)[1])

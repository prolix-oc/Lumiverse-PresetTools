import json
import tempfile
import unittest
from pathlib import Path

from preset_tools import get_block_lines, modify_block_lines, new_block, save
from preset_tools.mcp_server import (
    mcp,
    preset_edit_block_line_range,
    preset_edit_block_lines,
    preset_get_block_line_range,
    preset_get_block_lines,
)


def _sample_preset(content: str) -> dict:
    return {
        "blocks": [
            new_block(
                name="Voice Shaping",
                content=content,
            )
        ]
    }


class BlockLineHelpersTest(unittest.TestCase):
    def test_get_block_lines_returns_numbered_slice(self) -> None:
        preset = _sample_preset("one\ntwo\nthree\n")

        result = get_block_lines(preset, "Voice Shaping", start_line=2, end_line=3)

        self.assertEqual(result["start_line"], 2)
        self.assertEqual(result["end_line"], 3)
        self.assertEqual(result["total_lines"], 3)
        self.assertEqual(result["text"], "two\nthree\n")
        self.assertEqual(
            result["lines"],
            [
                {"line": 2, "text": "two"},
                {"line": 3, "text": "three"},
            ],
        )

    def test_modify_block_lines_replaces_middle_line_and_preserves_rest(self) -> None:
        preset = _sample_preset("one\ntwo\nthree\n")

        block = modify_block_lines(
            preset,
            "Voice Shaping",
            start_line=2,
            end_line=2,
            new_content="TWO",
        )

        self.assertEqual(block["content"], "one\nTWO\nthree\n")

    def test_modify_block_lines_replaces_range_at_end(self) -> None:
        preset = _sample_preset("one\ntwo\nthree\n")

        block = modify_block_lines(
            preset,
            "Voice Shaping",
            start_line=2,
            end_line=3,
            new_content="TWO\nTHREE",
        )

        self.assertEqual(block["content"], "one\nTWO\nTHREE")

    def test_modify_block_lines_rejects_out_of_bounds_ranges(self) -> None:
        preset = _sample_preset("one\ntwo")

        with self.assertRaisesRegex(ValueError, "past end of block"):
            modify_block_lines(
                preset,
                "Voice Shaping",
                start_line=3,
                new_content="THREE",
            )

    def test_modify_block_lines_rejects_non_positive_end_line(self) -> None:
        preset = _sample_preset("one\ntwo")

        with self.assertRaisesRegex(ValueError, "end_line must be >= start_line"):
            modify_block_lines(
                preset,
                "Voice Shaping",
                start_line=1,
                end_line=0,
                new_content="ONE",
            )


class MCPBlockLineToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_line_tools_round_trip(self) -> None:
        preset = _sample_preset("one\ntwo\nthree\n")

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            preset_path = Path(tmpdir) / "sample.json"
            save(preset, str(preset_path))
            rel_path = preset_path.relative_to(Path.cwd()).as_posix()

            before_raw = await preset_get_block_lines(
                path=rel_path,
                name="Voice Shaping",
                start_line=2,
                end_line=3,
            )
            before = json.loads(before_raw)
            self.assertTrue(before["ok"])
            self.assertEqual(before["result"]["lines"][0], {"line": 2, "text": "two"})

            edit_raw = await preset_edit_block_lines(
                path=rel_path,
                name="Voice Shaping",
                start_line=2,
                end_line=3,
                content="TWO\nTHREE",
            )
            edit = json.loads(edit_raw)
            self.assertTrue(edit["ok"])
            self.assertEqual(edit["result"]["removed_line_count"], 2)
            self.assertEqual(edit["result"]["inserted_line_count"], 2)
            self.assertEqual(
                edit["result"]["lines_after"],
                [
                    {"line": 2, "text": "TWO"},
                    {"line": 3, "text": "THREE"},
                ],
            )

    async def test_mcp_exact_range_tools_round_trip(self) -> None:
        preset = _sample_preset("one\ntwo\nthree\nfour\n")

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            preset_path = Path(tmpdir) / "sample.json"
            save(preset, str(preset_path))
            rel_path = preset_path.relative_to(Path.cwd()).as_posix()

            before_raw = await preset_get_block_line_range(
                path=rel_path,
                name="Voice Shaping",
                start_line=2,
                end_line=3,
            )
            before = json.loads(before_raw)
            self.assertTrue(before["ok"])
            self.assertEqual(before["result"]["text"], "two\nthree")

            edit_raw = await preset_edit_block_line_range(
                path=rel_path,
                name="Voice Shaping",
                start_line=2,
                end_line=3,
                replacement_content="TWO\nTHREE",
            )
            edit = json.loads(edit_raw)
            self.assertTrue(edit["ok"])
            self.assertEqual(
                edit["result"]["lines_after"],
                [
                    {"line": 2, "text": "TWO"},
                    {"line": 3, "text": "THREE"},
                ],
            )


class MCPBlockLineSchemaTest(unittest.TestCase):
    def test_exact_range_edit_schema_requires_end_line(self) -> None:
        tool = mcp._tool_manager._tools["preset_edit_block_line_range"]
        params = tool.parameters

        self.assertEqual(
            list(params["properties"]),
            ["path", "name", "start_line", "end_line", "replacement_content", "expected_revision"],
        )
        self.assertEqual(
            params["required"],
            ["path", "name", "start_line", "end_line", "replacement_content"],
        )

    def test_exact_range_read_schema_requires_end_line(self) -> None:
        tool = mcp._tool_manager._tools["preset_get_block_line_range"]
        params = tool.parameters

        self.assertEqual(
            list(params["properties"]),
            ["path", "name", "start_line", "end_line"],
        )
        self.assertEqual(
            params["required"],
            ["path", "name", "start_line", "end_line"],
        )

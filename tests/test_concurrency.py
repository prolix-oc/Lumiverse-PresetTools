"""Regression coverage for concurrent MCP preset writes."""

import asyncio
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path

from preset_tools.blocks import new_block
from preset_tools.io import save
from preset_tools.mcp_server import mcp, preset_modify_block


def _apply_patch_after_barrier(path: str, line: int, content: str, barrier, results) -> None:
    """Run in a separate process so the sidecar file lock is genuinely tested."""
    barrier.wait(timeout=10)
    old = "one" if line == 1 else "three"
    raw = asyncio.run(preset_modify_block(
        path=path,
        name="Concurrent",
        content=(
            f"@@ -{line},1 +{line},1 @@\n-{old}\n\\ No newline at end of file\n"
            f"+{content}\n\\ No newline at end of file\n"
        ),
    ))
    results.put(json.loads(raw))


@unittest.skipUnless(os.name != "nt", "process lock regression uses POSIX fork")
class ConcurrentWriteTest(unittest.IsolatedAsyncioTestCase):
    async def test_independent_parallel_writes_are_serialized_without_loss(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "preset.json"
            save({"blocks": [new_block("Concurrent", "one\ntwo\nthree")]}, str(path))

            context = multiprocessing.get_context("fork")
            barrier = context.Barrier(2)
            results = context.Queue()
            first = context.Process(
                target=_apply_patch_after_barrier,
                args=(str(path), 1, "ONE", barrier, results),
            )
            second = context.Process(
                target=_apply_patch_after_barrier,
                args=(str(path), 3, "THREE", barrier, results),
            )
            first.start()
            second.start()
            first.join(timeout=15)
            second.join(timeout=15)

            self.assertEqual(first.exitcode, 0)
            self.assertEqual(second.exitcode, 0)
            replies = [results.get(timeout=2), results.get(timeout=2)]
            self.assertTrue(all(reply["ok"] for reply in replies))
            self.assertTrue(all(reply["result"]["write_serialized"] for reply in replies))

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["blocks"][0]["content"], "ONE\ntwo\nTHREE")
            self.assertFalse(path.with_name(path.name + ".lock").is_dir())

    async def test_stale_expected_revision_conflicts_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "preset.json"
            save({"blocks": [new_block("Concurrent", "one\ntwo\nthree")]}, str(path))

            first = json.loads(await preset_modify_block(
                path=str(path), name="Concurrent", content="@@ -1,1 +1,1 @@\n-one\n+ONE\n",
            ))
            stale_revision = first["result"]["base_revision"]
            await preset_modify_block(
                path=str(path), name="Concurrent", content="@@ -2,1 +2,1 @@\n-two\n+TWO\n",
            )
            rejected = json.loads(await preset_modify_block(
                path=str(path), name="Concurrent", content="@@ -3,1 +3,1 @@\n-three\n+THREE\n",
                expected_revision=stale_revision,
            ))

            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["error"], "RevisionConflict")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["blocks"][0]["content"], "ONE\nTWO\nthree")

    async def test_write_schema_and_server_instructions_expose_concurrency_contract(self) -> None:
        write_tools = [
            "regex_create_script", "regex_update_script", "regex_delete_script",
            "preset_modify_block",
            "preset_replace_text", "preset_insert_prompt_variable", "preset_update_prompt_variable",
            "preset_remove_prompt_variable", "preset_set_stored_prompt_variable",
            "preset_remove_stored_prompt_variable", "preset_insert_block", "preset_delete_block",
            "preset_move_block", "preset_clone_block", "preset_rename_block",
            "preset_toggle_block", "preset_set_seal", "preset_mass_seal", "preset_backup",
            "preset_restore_backup", "character_card_set_field", "character_card_set_fields",
        ]
        for name in write_tools:
            parameters = mcp._tool_manager._tools[name].parameters
            self.assertIn("expected_revision", parameters["properties"], name)
            self.assertNotIn("expected_revision", parameters["required"], name)
        self.assertIn("serialized", mcp.instructions)
        self.assertIn("RevisionConflict", mcp.instructions)

import json
import tempfile
import unittest
from pathlib import Path

from preset_tools.blocks import apply_unified_diff, new_block
from preset_tools.io import save
from preset_tools.mcp_server import preset_modify_block


class UnifiedBlockPatchTest(unittest.TestCase):
    def test_applies_multiple_non_adjacent_hunks(self):
        content = "one\ntwo\nthree\nfour\nfive\n"
        patch = """--- before/Voice Shaping
+++ after/Voice Shaping
@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
@@ -4,2 +4,2 @@
 four
-five
+FIVE
"""

        self.assertEqual(
            apply_unified_diff(content, patch),
            "one\nTWO\nthree\nfour\nFIVE\n",
        )

    def test_rejects_stale_context_without_changing_source(self):
        content = "one\ntwo\nthree\n"
        patch = """@@ -1,3 +1,3 @@
 one
-TWO
+two
 three
"""

        with self.assertRaisesRegex(ValueError, "context does not match"):
            apply_unified_diff(content, patch)


class MCPUnifiedBlockPatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_modify_block_applies_patch_and_returns_diff_receipt(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "preset.json"
            save({"blocks": [new_block("Voice Shaping", "one\ntwo\nthree\nfour\nfive\n")]}, str(path))
            patch = """@@ -1,3 +1,3 @@
 one
-two
+TWO
 three
@@ -4,2 +4,2 @@
 four
-five
+FIVE
"""

            raw = await preset_modify_block(path=str(path), name="Voice Shaping", content=patch)
            reply = json.loads(raw)

            self.assertTrue(reply["ok"])
            self.assertEqual(reply["result"]["mode"], "unified_diff")
            self.assertEqual(reply["result"]["additions"], 2)
            self.assertEqual(reply["result"]["deletions"], 2)
            self.assertIn("-two", reply["result"]["diff"])
            self.assertIn("+TWO", reply["result"]["diff"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["blocks"][0]["content"], "one\nTWO\nthree\nfour\nFIVE\n")

"""Tests for selecting bundled and live macro-reference catalogs."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from preset_tools.mcp_server import preset_macro_reference


def _write_reference(directory: Path, category: str) -> None:
    directory.mkdir()
    (directory / "macro_reference.json").write_text(
        json.dumps(
            {
                "categories": [category],
                "macros": [
                    {
                        "category": category,
                        "macro": "{{example}}",
                        "name": "example",
                        "purpose": "Example macro",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class MacroReferenceSourceTest(unittest.TestCase):
    def test_source_selects_bundled_or_live_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            live = root / "live"
            _write_reference(bundled, "Bundled")
            _write_reference(live, "Live")

            with patch("preset_tools.mcp_server._BUNDLED_MACRO_REF_DIR", bundled), patch(
                "preset_tools.mcp_server._LIVE_MACRO_REF_DIR", live
            ), patch("preset_tools.mcp_server._CONFIGURED_MACRO_REF_DIR", bundled):
                bundled_result = json.loads(
                    asyncio.run(preset_macro_reference(source="bundled", format="json"))
                )
                live_result = json.loads(
                    asyncio.run(preset_macro_reference(source="live", format="json"))
                )
                auto_result = json.loads(
                    asyncio.run(preset_macro_reference(source="auto", format="json"))
                )

        self.assertEqual(bundled_result["result"]["categories"], ["Bundled"])
        self.assertEqual(live_result["result"]["categories"], ["Live"])
        self.assertEqual(auto_result["result"]["categories"], ["Live"])

    def test_live_source_reports_missing_checkout(self):
        with patch("preset_tools.mcp_server._LIVE_MACRO_REF_DIR", None):
            result = json.loads(asyncio.run(preset_macro_reference(source="live", format="json")))

        self.assertFalse(result["ok"])
        self.assertIn("PRESET_TOOLS_LUMIVERSE_ROOT", result["error"])

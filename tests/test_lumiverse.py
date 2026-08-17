"""Tests for the live Lumiverse renderer and prompt-variable consistency."""

import os
import unittest
from pathlib import Path

from preset_tools.io import load, stored_prompt_vars
from preset_tools.render import RenderEnv, render_preset
from preset_tools.lumiverse import (
    available,
    diff_render,
    find_lumiverse_root,
    render_preset_live,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _live_root():
    """Return the local Lumiverse checkout, or None when unavailable."""
    try:
        return find_lumiverse_root()
    except FileNotFoundError:
        return None


LIVE_ROOT = _live_root()
_HAS_LIVE = LIVE_ROOT is not None and available(str(LIVE_ROOT))

_SELECT_PRESET = {
    "blocks": [
        {
            "id": "block-1",
            "name": "Style",
            "enabled": True,
            "content": "Mode: {{var::mode}}",
            "variables": [
                {
                    "id": "v-1",
                    "name": "mode",
                    "type": "select",
                    "defaultValue": "cinematic",
                    "options": [
                        {"id": "cinematic", "label": "Cinematic", "value": "sweeping cinematic narration"},
                        {"id": "poetic", "label": "Poetic", "value": "lush poetic prose"},
                    ],
                }
            ],
        }
    ]
}


class StoredPromptVarsTest(unittest.TestCase):
    def test_flat_schema(self):
        preset = {"blocks": [], "promptVariables": {"a": {"x": 1}}}
        self.assertEqual(stored_prompt_vars(preset), {"a": {"x": 1}})

    def test_nested_schema(self):
        preset = {"preset": {"blocks": [], "promptVariables": {"a": {"x": 1}}}}
        self.assertEqual(stored_prompt_vars(preset), {"a": {"x": 1}})

    def test_metadata_shape(self):
        preset = {"preset": {"blocks": [], "metadata": {"promptVariables": {"a": {"x": 1}}}}}
        self.assertEqual(stored_prompt_vars(preset), {"a": {"x": 1}})

    def test_missing(self):
        self.assertEqual(stored_prompt_vars({"blocks": []}), {})


class CoercionConsistencyTest(unittest.TestCase):
    def test_select_maps_option_value(self):
        result = render_preset(_SELECT_PRESET, RenderEnv.empty(), tokenize=False)
        self.assertIn("sweeping cinematic narration", result.text)

    def test_select_override_maps_option_value(self):
        result = render_preset(
            _SELECT_PRESET, RenderEnv.empty(), tokenize=False,
            prompt_var_overrides={"mode": "poetic"},
        )
        self.assertIn("lush poetic prose", result.text)

    def test_stored_value_overrides_default(self):
        preset = {
            "blocks": [
                {
                    "id": "b1",
                    "name": "Gate",
                    "enabled": True,
                    "content": "{{if::{{var::flag}} == 1}}ON{{else}}OFF{{/if}}",
                    "variables": [
                        {"id": "v1", "name": "flag", "type": "switch", "defaultValue": 0}
                    ],
                }
            ],
            "promptVariables": {"b1": {"flag": 1}},
        }
        result = render_preset(preset, RenderEnv.empty(), tokenize=False)
        self.assertEqual(result.text, "ON")

    def test_explicit_override_wins_over_stored(self):
        preset = {
            "blocks": [
                {
                    "id": "b1",
                    "name": "Gate",
                    "enabled": True,
                    "content": "{{if::{{var::flag}} == 1}}ON{{else}}OFF{{/if}}",
                    "variables": [
                        {"id": "v1", "name": "flag", "type": "switch", "defaultValue": 0}
                    ],
                }
            ],
            "promptVariables": {"b1": {"flag": 1}},
        }
        result = render_preset(
            preset, RenderEnv.empty(), tokenize=False,
            prompt_var_overrides={"flag": 0},
        )
        self.assertEqual(result.text, "OFF")

    def test_multiselect_joins_values_with_newlines(self):
        preset = {
            "blocks": [
                {
                    "id": "b1",
                    "name": "Tags",
                    "enabled": True,
                    "content": "{{var::tags}}",
                    "variables": [
                        {
                            "id": "v1", "name": "tags", "type": "multiselect",
                            "defaultValue": ["slow-burn"],
                            "options": [
                                {"id": "slow-burn", "label": "Slow Burn", "value": "favor a slow burn"},
                                {"id": "banter", "label": "Banter", "value": "keep the banter sharp"},
                            ],
                        }
                    ],
                }
            ]
        }
        result = render_preset(
            preset, RenderEnv.empty(), tokenize=False,
            prompt_var_overrides={"tags": ["slow-burn", "banter"]},
        )
        self.assertEqual(result.text, "favor a slow burn\n\nkeep the banter sharp")


@unittest.skipUnless(_HAS_LIVE, "no live Lumiverse checkout + bun available")
class LiveRenderTest(unittest.TestCase):
    def test_render_sample_preset_matches_offline(self):
        preset = load(str(FIXTURES / "sample_preset.json"))
        offline = render_preset(preset, RenderEnv.empty(), tokenize=False)
        live = render_preset_live(preset, root=str(LIVE_ROOT))
        self.assertEqual(offline.text, live.text)

    def test_prompt_var_override(self):
        preset = load(str(FIXTURES / "sample_preset.json"))
        live = render_preset_live(
            preset, root=str(LIVE_ROOT),
            prompt_var_overrides={"narration_style": "poetic"},
        )
        self.assertIn("lush poetic prose", live.text)

    def test_diff_render_shape(self):
        preset = load(str(FIXTURES / "sample_preset.json"))
        result = diff_render(preset, root=str(LIVE_ROOT))
        self.assertIn("backend_root", result)
        self.assertIn("identical", result)
        self.assertIn("diffs", result)


if __name__ == "__main__":
    unittest.main()

"""Tests for render_block — single-block isolated rendering."""

import unittest

from preset_tools.render import RenderEnv, render_block


def _preset():
    return {
        "promptVariables": {},
        "blocks": [
            {
                "id": "b0",
                "name": "Vars",
                "role": "system",
                "position": "pre_history",
                "marker": "category",
                "enabled": True,
                "content": "",
                "variables": [
                    {
                        "id": "v1",
                        "name": "mode",
                        "label": "Mode",
                        "type": "switch",
                        "defaultValue": 0,
                    }
                ],
            },
            {
                "id": "b1",
                "name": "Setter",
                "role": "system",
                "position": "pre_history",
                "marker": None,
                "enabled": True,
                "content": "{{setvar::gate::1}}Set.",
                "variables": [],
            },
            {
                "id": "b2",
                "name": "Gated",
                "role": "system",
                "position": "pre_history",
                "marker": None,
                "enabled": True,
                "content": "{{if::{{getvar::gate}} == 1}}ON{{else}}OFF{{/if}}",
                "variables": [],
            },
            {
                "id": "b3",
                "name": "Disabled Gated",
                "role": "system",
                "position": "pre_history",
                "marker": None,
                "enabled": False,
                "content": "{{if::{{getvar::gate}} == 1}}ON{{else}}OFF{{/if}}",
                "variables": [],
            },
            {
                "id": "b4",
                "name": "PromptVar Reader",
                "role": "system",
                "position": "pre_history",
                "marker": None,
                "enabled": True,
                "content": "mode={{var::mode}}",
                "variables": [],
            },
        ],
    }


class RenderBlockTests(unittest.TestCase):
    def test_isolation_gate_unset(self):
        out = render_block(_preset(), "Gated", RenderEnv.empty(), tokenize=False)
        self.assertEqual(out["text"], "OFF")
        self.assertTrue(out["enabled"])
        self.assertEqual(out["prior_blocks_rendered"], 0)

    def test_variables_seed_getvar(self):
        out = render_block(
            _preset(), "Gated", RenderEnv.empty(),
            variables={"gate": 1}, tokenize=False,
        )
        self.assertEqual(out["text"], "ON")
        self.assertEqual(out["local_variables"]["gate"], "1")

    def test_with_prior_state_reproduces_setvar_chain(self):
        out = render_block(
            _preset(), "Gated", RenderEnv.empty(),
            with_prior_state=True, tokenize=False,
        )
        self.assertEqual(out["text"], "ON")
        self.assertEqual(out["prior_blocks_rendered"], 1)  # empty "Vars" marker is skipped
        self.assertEqual(out["local_variables"]["gate"], "1")

    def test_without_prior_state_setter_not_applied(self):
        # Sanity inverse of the above: no prior state -> gate stays unset.
        out = render_block(_preset(), "Gated", RenderEnv.empty(), tokenize=False)
        self.assertNotIn("gate", out["local_variables"])

    def test_disabled_block_renders(self):
        out = render_block(_preset(), "Disabled Gated", RenderEnv.empty(), tokenize=False)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["text"], "OFF")

    def test_prompt_variable_override(self):
        out = render_block(
            _preset(), "PromptVar Reader", RenderEnv.empty(),
            prompt_var_overrides={"mode": 1}, tokenize=False,
        )
        self.assertEqual(out["text"], "mode=1")

    def test_prompt_variable_creator_default(self):
        out = render_block(
            _preset(), "PromptVar Reader", RenderEnv.empty(), tokenize=False,
        )
        self.assertEqual(out["text"], "mode=0")

    def test_unknown_block_raises(self):
        with self.assertRaises(ValueError):
            render_block(_preset(), "Nope", RenderEnv.empty(), tokenize=False)

    def test_index_points_at_original_block_order(self):
        out = render_block(_preset(), "Gated", RenderEnv.empty(), tokenize=False)
        self.assertEqual(out["index"], 2)


if __name__ == "__main__":
    unittest.main()

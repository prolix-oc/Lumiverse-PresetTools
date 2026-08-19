"""Tests for unclosed wrapper-macro validation (if, trim, and friends)."""

import unittest

from preset_tools.validate import validate


def _preset(content: str) -> dict:
    return {
        "promptVariables": {},
        "blocks": [
            {
                "id": "b0",
                "name": "T",
                "role": "system",
                "position": "pre_history",
                "marker": None,
                "enabled": True,
                "content": content,
                "variables": [],
            }
        ],
    }


def _codes(result) -> set[str]:
    return {d.code for d in result.diagnostics}


class UnclosedIfTests(unittest.TestCase):
    def test_unclosed_if_is_error(self):
        res = validate(_preset("{{if::{{getvar::x}}}}Body never gated"))
        self.assertIn("unclosed-if", _codes(res))
        self.assertFalse(res.ok)

    def test_closed_if_is_clean(self):
        res = validate(_preset("{{if::{{getvar::x}}}}Body{{/if}}"))
        self.assertNotIn("unclosed-if", _codes(res))

    def test_if_else_closed_is_clean(self):
        res = validate(_preset("{{if::{{getvar::x}}}}A{{else}}B{{/if}}"))
        self.assertNotIn("unclosed-if", _codes(res))

    def test_nested_closed_ifs_are_clean(self):
        res = validate(_preset("{{if::{{getvar::x}}}}A{{if::{{getvar::y}}}}B{{/if}}{{/if}}"))
        self.assertNotIn("unclosed-if", _codes(res))


class UnclosedWrapperTests(unittest.TestCase):
    def test_unclosed_trim_is_error(self):
        res = validate(_preset("{{trim}}text meant to be wrapped"))
        self.assertIn("unclosed-wrapper", _codes(res))
        self.assertFalse(res.ok)

    def test_closed_trim_is_clean(self):
        res = validate(_preset("{{trim}}\n  padded\n{{/trim}}"))
        self.assertNotIn("unclosed-wrapper", _codes(res))

    def test_orphan_close_tag_is_error(self):
        res = validate(_preset("body{{/trim}}"))
        self.assertIn("orphan-close", _codes(res))

    def test_mismatched_nesting_reports_orphan(self):
        # if/trim interleaved closes: pairing takes the valid inner pair and
        # the leftover closer must surface as an error, not silence.
        res = validate(_preset("{{if::1}}{{trim}}a{{/if}}{{/trim}}"))
        codes = _codes(res)
        self.assertIn("orphan-close", codes)

    def test_inline_text_transform_not_flagged(self):
        # upper/lower etc. are scoped-CAPABLE but not SCOPED_HINT — inline use
        # is idiomatic and must not be flagged as unclosed.
        res = validate(_preset("{{upper::hello}}"))
        self.assertNotIn("unclosed-wrapper", _codes(res))
        self.assertNotIn("unclosed-if", _codes(res))


class RegressionTests(unittest.TestCase):
    def test_else_outside_if_still_detected(self):
        res = validate(_preset("{{else}}oops{{/if}}"))
        codes = _codes(res)
        self.assertIn("else-outside-if", codes)

    def test_dropped_gates_pattern_is_clean(self):
        # The session regression shape: text with NO wrappers at all is
        # syntactically valid (semantic loss is invisible to a syntax check).
        res = validate(_preset("1. **Step:** runs unconditionally now"))
        for code in ("unclosed-if", "unclosed-wrapper", "orphan-close"):
            self.assertNotIn(code, _codes(res))


if __name__ == "__main__":
    unittest.main()

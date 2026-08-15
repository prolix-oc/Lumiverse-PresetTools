"""Tests for preset_tools.regex_lint — repairs, linting, and engine checks."""

import json
import unittest
from pathlib import Path

from preset_tools import regex_lint as rl

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

CORPUS_FILES = [
    "sample_preset.json",
    "sample_regex_export.json",
]


def codes(findings, severity=None):
    return [f["code"] for f in findings if severity is None or f["severity"] == severity]


class StripRegexLiteralTest(unittest.TestCase):
    def test_strips_delimiters_and_merges_flags(self):
        pattern, flags, notes = rl.strip_regex_literal("/<card>[\\s\\S]*?</card>/gi", "")
        self.assertEqual(pattern, "<card>[\\s\\S]*?</card>")
        self.assertEqual(flags, "gi")
        self.assertEqual(codes(notes), ["stripped_literal"])

    def test_flags_merge_without_duplicates(self):
        pattern, flags, _ = rl.strip_regex_literal("/x/i", "g")
        self.assertEqual((pattern, flags), ("x", "gi"))

    def test_slash_inside_pattern_survives_json_decoding(self):
        # An LLM sending "/<\/card>/g" as JSON produces "/</card>/g" here
        # because JSON decodes \/ to / — stripping still works.
        pattern, flags, notes = rl.strip_regex_literal("/</card>/g", "")
        self.assertEqual(pattern, "</card>")
        self.assertEqual(flags, "g")
        self.assertEqual(codes(notes), ["stripped_literal"])

    def test_body_may_keep_escaped_slashes(self):
        pattern, flags, _ = rl.strip_regex_literal("/a\\/b/g", "")
        self.assertEqual(pattern, "a\\/b")
        self.assertEqual(flags, "g")

    def test_unterminated_literal_warns(self):
        pattern, flags, notes = rl.strip_regex_literal("/foo", "")
        self.assertEqual((pattern, flags), ("/foo", ""))
        self.assertEqual(codes(notes, "warning"), ["unterminated_literal"])

    def test_plain_pattern_untouched(self):
        pattern, flags, notes = rl.strip_regex_literal("<card>[\\s\\S]*?</card>", "gi")
        self.assertEqual((pattern, flags, notes), ("<card>[\\s\\S]*?</card>", "gi", []))

    def test_unwraps_new_regexp(self):
        pattern, flags, notes = rl.strip_regex_literal('new RegExp("<card>x</card>", "gi")', "")
        self.assertEqual(pattern, "<card>x</card>")
        self.assertEqual(flags, "gi")
        self.assertEqual(codes(notes), ["unwrapped_new_regexp"])

    def test_broken_wrapper_warns(self):
        pattern, flags, notes = rl.strip_regex_literal("new RegExp(oops", "")
        self.assertEqual(pattern, "new RegExp(oops")
        self.assertEqual(codes(notes, "warning"), ["new_regexp_wrapper"])


class NormalizePatternTest(unittest.TestCase):
    def test_repairs_python_named_groups(self):
        pattern, flags, notes = rl.normalize_pattern_input("(?P<body>[\\s\\S]*?)", "gi")
        self.assertEqual(pattern, "(?<body>[\\s\\S]*?)")
        self.assertEqual(codes(notes), ["python_named_group"])

    def test_flags_python_backreference(self):
        _, _, notes = rl.normalize_pattern_input("(?P=name)", "g")
        self.assertIn("python_backref", codes(notes, "warning"))

    def test_collapses_doubled_backslashes(self):
        raw = "<card>" + "\\\\" + "s*(?<body>[" + "\\\\" + "s" + "\\\\" + "S]*?)</card>"
        pattern, flags, notes = rl.normalize_pattern_input(raw, "gi")
        self.assertEqual(pattern, "<card>\\s*(?<body>[\\s\\S]*?)</card>")
        self.assertEqual(codes(notes), ["collapsed_backslashes"])

    def test_keeps_doubled_backslashes_when_collapsing_breaks_syntax(self):
        # "\\1" with the u flag is a literal backslash followed by 1 (clean);
        # collapsing it to "\1" would be an out-of-range backreference.
        raw = "\\\\" + "1"
        pattern, flags, notes = rl.normalize_pattern_input(raw, "gu")
        self.assertEqual(pattern, raw)
        self.assertEqual(codes(notes, "warning"), ["doubled_backslashes"])

    def test_repair_disabled_is_verbatim(self):
        raw = " /x/g "
        pattern, flags, notes = rl.normalize_pattern_input(raw, "", repair=False)
        self.assertEqual((pattern, flags, notes), (raw, "", []))


class NormalizeReplacementTest(unittest.TestCase):
    def test_converts_over_escaped_sequences(self):
        raw = '<div class=\\"x\\">a\\tb\\n</div>'
        replacement, notes = rl.normalize_replacement_input(raw)
        self.assertEqual(replacement, '<div class="x">a\tb\n</div>')
        self.assertEqual(codes(notes), ["unescaped_replacement"])

    def test_leaves_unknown_escapes_alone(self):
        raw = "keep \\d and \\w here"
        replacement, notes = rl.normalize_replacement_input(raw)
        self.assertEqual((replacement, notes), (raw, []))

    def test_no_backslashes_is_verbatim(self):
        raw = "$<body> stays"
        self.assertEqual(rl.normalize_replacement_input(raw), (raw, []))


class LinterValidPatternsTest(unittest.TestCase):
    """Patterns that must lint with zero error findings."""

    def test_valid_patterns(self):
        valid = [
            (r"<card>(?<body>[\s\S]*?)</card>", "gi"),
            (r"<loadoutcard>\s*<destination>(?<destination>[\s\S]*?)</destination>", "gi"),
            (r"(?<=x)\d{2,5}(?:a|b)*?", "g"),
            (r"[^\]]+\$", "g"),
            (r"\u{1F600}", "gu"),
            (r"\p{L}+", "gu"),
            (r"[]a]", "g"),
            (r"a|b|c", "g"),
            (r"(?<choice1>[\s\S]*?)", "gi"),
            (r"\$\d+\.\d{2}", "g"),
            (r"^---$\n*", "gm"),
            (r"((?<a>x)|(?<b>y))", "g"),
            (r"a{,5}", "g"),  # literal braces without u flag
            (r"\n{3,}", "g"),  # open-ended quantifier
            (r"x{2,}y{0,}", "g"),
            (r"[\d\-]+", "g"),
            (r"\bword\b", "gi"),
        ]
        for pattern, flags in valid:
            with self.subTest(pattern=pattern):
                findings, names, count = rl.lint_js_pattern(pattern, flags)
                self.assertEqual(codes(findings, "error"), [], f"{pattern}: {findings}")
                # engine agreement when available
                if rl.engine_kind():
                    self.assertTrue(rl.engine_compile(pattern, flags)["ok"], pattern)


class LinterInvalidPatternsTest(unittest.TestCase):
    def test_invalid_patterns(self):
        invalid = [
            ("(", "unclosed_group"),
            ("(a", "unclosed_group"),
            ("[a", "unterminated_class"),
            (")", "unmatched_paren"),
            ("a{3,1}", "reversed_range"),
            ("*a", "nothing_to_repeat"),
            ("a**", "nothing_to_repeat"),
            ("(?#comment)", "invalid_group"),
            (r"\k<nope>(?<a>x)", "unknown_group_ref"),
            ("(?<1a>x)", "invalid_group_name"),
            (r"(?<a>x)\k<other>", "unknown_group_ref"),
            ("a{2", "lone_brace"),  # with u flag
        ]
        for pattern, code in invalid:
            flags = "gu" if code == "lone_brace" else "g"
            with self.subTest(pattern=pattern):
                findings, _, _ = rl.lint_js_pattern(pattern, flags)
                self.assertIn(code, codes(findings, "error"))
                if rl.engine_kind():
                    self.assertFalse(rl.engine_compile(pattern, flags)["ok"], pattern)

    def test_python_only_escapes_warn(self):
        for escape in ("\\A", "\\Z", "\\z"):
            findings, _, _ = rl.lint_js_pattern(escape + "x", "g")
            self.assertIn("python_escape", codes(findings, "warning"), escape)
            self.assertEqual(codes(findings, "error"), [], escape)

    def test_u_flag_rules(self):
        self.assertIn("lone_brace", codes(rl.lint_js_pattern("a{", "gu")[0], "error"))
        self.assertEqual(codes(rl.lint_js_pattern("a{", "g")[0], "error"), [])


class ReplacementRefsTest(unittest.TestCase):
    def test_valid_references_pass(self):
        text = "<div>$<body></div> $1 $2 $$ $& $` $'"
        findings = rl.check_replacement_refs(text, ["body"], 2)
        self.assertEqual(findings, [])

    def test_unknown_named_reference_errors(self):
        findings = rl.check_replacement_refs("$<boby>", ["body"], 1)
        self.assertIn("unknown_group_ref", codes(findings, "error"))
        self.assertIn("body", findings[0]["message"])

    def test_numeric_reference_out_of_range(self):
        findings = rl.check_replacement_refs("$5", [], 1)
        self.assertIn("numeric_ref_out_of_range", codes(findings, "error"))

    def test_two_digit_reference_beyond_groups_warns(self):
        findings = rl.check_replacement_refs("$12", [], 1)
        self.assertIn("ambiguous_numeric_ref", codes(findings, "warning"))
        self.assertEqual(codes(findings, "error"), [])

    def test_no_named_groups_reports_that(self):
        findings = rl.check_replacement_refs("$<anything>", [], 0)
        self.assertIn("defines no named groups", findings[0]["message"])


class EngineTest(unittest.TestCase):
    def setUp(self):
        if rl.engine_kind() is None:
            self.skipTest("no JavaScript engine available")

    def test_compile_and_error_message(self):
        self.assertEqual(rl.engine_compile(r"(?<a>x)", "g"), {"ok": True})
        result = rl.engine_compile("[unclosed", "g")
        self.assertFalse(result["ok"])
        self.assertIn("Unterminated", result["message"])

    def test_compile_many_batch(self):
        results = rl.engine_compile_many([(r"a", "g"), (r"(b", "g")])
        self.assertEqual([r["ok"] for r in results], [True, False])

    def test_render_with_named_groups(self):
        if rl.engine_kind() != "node":
            self.skipTest("render requires node")
        result = rl.engine_render(r"<card>(?<body>[\s\S]*?)</card>", "gi", "[$<body>]", "x <card>hi</card> y")
        self.assertTrue(result["ok"])
        self.assertEqual(result["rendered"], "x [hi] y")
        self.assertEqual(result["matches"][0]["groups"], {"body": "hi"})


class LintScriptTest(unittest.TestCase):
    def _script(self, **overrides):
        script = {
            "name": "t", "script_id": "t",
            "find_regex": r"<card>(?<body>[\s\S]*?)</card>",
            "replace_string": "<p>$<body></p>",
            "flags": "gi",
        }
        script.update(overrides)
        return script

    def test_clean_script_has_no_findings(self):
        self.assertEqual(rl.lint_script(self._script(), use_engine=False), [])

    def test_action_references_checked(self):
        script = self._script(actions=[{"id": "c", "type": "send", "title": "$<body>", "content": "$<boby>"}])
        findings = rl.lint_script(script, use_engine=False)
        self.assertEqual(codes(findings, "error"), ["unknown_group_ref"])
        self.assertEqual(findings[0]["field"], "actions[0].content")

    def test_engine_downgrades_structural_false_positives(self):
        # "]]" outside a class is legal JS; if the structural linter ever
        # flagged it, an engine pass must downgrade that finding.
        script = self._script(find_regex="]]", replace_string="")
        findings = rl.lint_script(script, use_engine=False)
        if rl.engine_kind():
            engine_findings = rl.lint_script(script, use_engine=True)
            self.assertEqual(codes(engine_findings, "error"), [])

    def test_engine_syntax_error_is_authoritative(self):
        if rl.engine_kind() is None:
            self.skipTest("no JavaScript engine available")
        findings = rl.lint_script(self._script(find_regex="(?<x>a){2,1}"), use_engine=True)
        self.assertIn("engine_syntax_error", codes(findings, "error"))


class CorpusRegressionTest(unittest.TestCase):
    """Every regex script shipped in tests/fixtures must lint clean."""

    def test_corpus_scripts_have_no_errors(self):
        checked = 0
        for name in CORPUS_FILES:
            path = FIXTURES_DIR / name
            if not path.exists():
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            scripts = document.get("extensions", {}).get("regex_scripts")
            if not isinstance(scripts, list):
                scripts = document.get("scripts", [])
            for script in scripts:
                checked += 1
                findings = rl.lint_script(script, use_engine=False)
                self.assertEqual(
                    codes(findings, "error"), [],
                    f"{name}/{script.get('script_id')}: {findings}",
                )
        if checked == 0:
            self.skipTest("no corpus fixtures found")
        self.assertGreater(checked, 4)


if __name__ == "__main__":
    unittest.main()

"""Tests for the replace module: validation gate, both modes, surfaces, and
the MCP search & replace tools."""

import json
import tempfile
import unittest
from pathlib import Path

from preset_tools.replace import (
    REPLACE_SURFACES,
    ReplaceRejected,
    check_replace,
    replace_in_preset,
    translate_replacement,
)
from preset_tools.mcp_server import preset_check_replace, preset_replace_text


def _preset():
    return {
        "blocks": [
            {"name": "Intro", "marker": "category", "content": "<intro>cinematic opening</intro>"},
            {"name": "System", "content": "You are the narrator.\nStyle: cinematic.\nNotes here.", "enabled": True},
            {"name": "Style", "content": "Prose mode cinematic and cinematic.", "enabled": False},
            {"name": "Ending", "marker": "category", "content": "<ending>finale</ending>"},
            {"name": "Outro", "content": "Wrap up cinematic.", "enabled": True},
        ]
    }


class TranslateReplacementTest(unittest.TestCase):
    def test_js_refs(self):
        self.assertEqual(translate_replacement("$1-$2"), r"\g<1>-\g<2>")
        self.assertEqual(translate_replacement("$<name>"), r"\g<name>")
        self.assertEqual(translate_replacement("${name}"), r"\g<name>")

    def test_literal_dollar_and_escapes(self):
        self.assertEqual(translate_replacement("costs $5 today"), "costs \\g<5> today")  # JS semantics: $5 is group 5
        self.assertEqual(translate_replacement("$$5"), "$5")  # $$ is the literal-dollar escape
        self.assertEqual(translate_replacement("$"), "$")

    def test_python_native_passthrough(self):
        self.assertEqual(translate_replacement(r"\1 \g<name>"), r"\1 \g<name>")


class CheckReplaceTest(unittest.TestCase):
    def test_ok_basic(self):
        gate = check_replace(r"(\w+)", r"<$1>", samples=[{"label": "t", "text": "hello world"}])
        self.assertTrue(gate["ok"])
        self.assertEqual(gate["replacement_template"], r"<\g<1>>")
        self.assertEqual(gate["group_count"], 1)

    def test_unknown_mode(self):
        gate = check_replace("a", "b", mode="fuzzy")
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["findings"][0]["code"], "unknown_mode")

    def test_empty_pattern(self):
        gate = check_replace("", "x", mode="literal")
        self.assertFalse(gate["ok"])
        self.assertIn("empty_pattern", [f["code"] for f in gate["findings"]])

    def test_syntax_error_carries_position_and_hint(self):
        gate = check_replace("ab(", "x")
        self.assertFalse(gate["ok"])
        err = next(f for f in gate["findings"] if f["code"] == "syntax_error")
        self.assertEqual(err["position"], 2)
        self.assertIn("^", err["excerpt"])
        self.assertIn("never closed", err["hint"])

    def test_empty_match_rejected(self):
        gate = check_replace("a*", "x")
        self.assertFalse(gate["ok"])
        self.assertIn("empty_match_possible", [f["code"] for f in gate["findings"]])

    def test_bad_group_reference(self):
        gate = check_replace(r"(a)", r"$2")
        self.assertFalse(gate["ok"])
        self.assertIn("invalid_group_reference", [f["code"] for f in gate["findings"]])

    def test_named_group_reference_checked(self):
        gate = check_replace(r"(?P<w>a)", r"$<missing>")
        self.assertFalse(gate["ok"])
        self.assertIn("invalid_group_reference", [f["code"] for f in gate["findings"]])

    def test_js_named_group_translated(self):
        gate = check_replace(r"(?<w>a)", r"$<w>", samples=[{"text": "a"}])
        self.assertTrue(gate["ok"])
        self.assertIn("(?P<w>a)", gate["pattern"])

    def test_js_literal_flags(self):
        gate = check_replace("/cinematic/i", "x", samples=[{"text": "CINEMATIC"}])
        self.assertTrue(gate["ok"])
        self.assertTrue(any(f["code"] == "stripped_literal" for f in gate["findings"]))
        self.assertEqual(gate["match_preview"][0]["label"], "sample 1")

    def test_over_broad_rejected_with_evidence(self):
        gate = check_replace(r".*", "x", samples=[{"label": "big", "text": "y" * 100}])
        self.assertFalse(gate["ok"])
        broad = next(f for f in gate["findings"] if f["code"] == "over_broad_match")
        self.assertIn("big", broad["message"])
        self.assertIn("100%", broad["message"])

    def test_over_broad_allowed_when_requested(self):
        gate = check_replace(r".+", "x", samples=[{"text": "y" * 100}], allow_broad=True)
        self.assertTrue(gate["ok"])
        self.assertTrue(any(f["code"] == "broad_match_allowed" for f in gate["findings"]))

    def test_anchors_without_multiline_hint(self):
        gate = check_replace(r"^Style:", "Mode:", samples=[{"text": "alpha\nStyle: cinematic"}])
        self.assertTrue(gate["ok"])
        self.assertIn("multiline_hint", [f["code"] for f in gate["findings"]])


class ReplaceInPresetTest(unittest.TestCase):
    def test_literal_all_surfaces(self):
        p = _preset()
        report = replace_in_preset(p, "cinematic", "clinical", mode="literal")
        self.assertTrue(report["changed"])
        self.assertEqual(p["blocks"][1]["content"], "You are the narrator.\nStyle: clinical.\nNotes here.")
        self.assertEqual(p["blocks"][2]["content"], "Prose mode clinical and clinical.")
        self.assertEqual(p["blocks"][4]["content"], "Wrap up clinical.")
        self.assertEqual(p["blocks"][0]["content"], "<intro>clinical opening</intro>")
        self.assertEqual(report["total_matches"], 5)
        self.assertEqual(report["counts"], {"block_content": 3, "category_content": 1})

    def test_literal_titles_only(self):
        p = _preset()
        report = replace_in_preset(p, "e", "3", mode="literal", surfaces=["block_title", "category_title"])
        names = [b["name"] for b in p["blocks"]]
        self.assertEqual(names, ["Intro", "Syst3m", "Styl3", "3nding", "Outro"])

    def test_regex_group_replacement(self):
        p = _preset()
        report = replace_in_preset(
            p, r"Style: (\w+)", r"Style: [\g<1>]", mode="regex", surfaces=["block_content"],
        )
        self.assertIn("Style: [cinematic]", p["blocks"][1]["content"])
        self.assertTrue(report["changed"])

    def test_case_insensitive_by_default(self):
        p = _preset()
        replace_in_preset(p, "CINEMATIC", "x", mode="literal", surfaces=["block_content"])
        self.assertNotIn("cinematic", p["blocks"][1]["content"])

    def test_case_sensitive_literal(self):
        p = _preset()
        report = replace_in_preset(p, "CINEMATIC", "x", mode="literal", case_sensitive=True, surfaces=["block_content"])
        self.assertFalse(report["changed"])

    def test_dry_run_does_not_mutate(self):
        p = _preset()
        before = json.dumps(p)
        report = replace_in_preset(p, "cinematic", "clinical", mode="literal", dry_run=True)
        self.assertTrue(report["changed"])
        self.assertTrue(report["dry_run"])
        self.assertEqual(json.dumps(p), before)

    def test_category_filter(self):
        p = _preset()
        report = replace_in_preset(p, "cinematic", "x", mode="literal", category="Intro")
        self.assertEqual(p["blocks"][1]["content"], "You are the narrator.\nStyle: x.\nNotes here.")
        self.assertIn("x", p["blocks"][2]["content"])  # Style block is inside the Intro section
        self.assertEqual(p["blocks"][2]["content"], "Prose mode x and x.")
        self.assertIn("cinematic", p["blocks"][4]["content"])  # Outro is in the Ending section

    def test_unknown_surface_raises(self):
        with self.assertRaises(ValueError):
            replace_in_preset(_preset(), "a", "b", surfaces=["variables"])

    def test_over_broad_blocks_write(self):
        p = _preset()
        with self.assertRaises(ReplaceRejected) as ctx:
            replace_in_preset(p, r"[\s\S]+", "x", mode="regex")
        codes = [f["code"] for f in ctx.exception.findings]
        self.assertIn("over_broad_match", codes)
        self.assertIn("cinematic", p["blocks"][1]["content"])  # untouched

    def test_broad_allowed_applies(self):
        p = _preset()
        report = replace_in_preset(p, r"[\s\S]+", "x", mode="regex", allow_broad=True,
                                   surfaces=["block_content", "category_content"])
        self.assertTrue(report["changed"])
        self.assertEqual(p["blocks"][1]["content"], "x")

    def test_syntax_error_blocks_write(self):
        p = _preset()
        with self.assertRaises(ReplaceRejected):
            replace_in_preset(p, "a(", "x", mode="regex")

    def test_empty_match_blocks_write(self):
        p = _preset()
        with self.assertRaises(ReplaceRejected):
            replace_in_preset(p, r"o*", "x", mode="regex")

    def test_duplicate_title_rejected(self):
        p = _preset()
        with self.assertRaises(ReplaceRejected) as ctx:
            replace_in_preset(p, "System", "Style", mode="literal", surfaces=["block_title"])
        codes = [f["code"] for f in ctx.exception.findings]
        self.assertIn("duplicate_title_result", codes)

    def test_empty_title_rejected(self):
        p = _preset()
        with self.assertRaises(ReplaceRejected) as ctx:
            replace_in_preset(p, r"System", "", mode="regex", surfaces=["block_title"])
        self.assertIn("empty_title_result", [f["code"] for f in ctx.exception.findings])

    def test_no_match_report(self):
        p = _preset()
        report = replace_in_preset(p, "zzz-not-present", "x", mode="literal")
        self.assertFalse(report["changed"])
        self.assertEqual(report["total_matches"], 0)
        self.assertEqual(report["changes"], [])

    def test_growth_guard(self):
        p = {"blocks": [{"name": "Big", "content": "n" * 3000}]}
        with self.assertRaises(ReplaceRejected) as ctx:
            replace_in_preset(p, r"([\s\S]+)", r"$1$1", mode="regex", allow_broad=True)
        self.assertIn("explosive_growth", [f["code"] for f in ctx.exception.findings])

    def test_surfaces_default_covers_all_four(self):
        self.assertEqual(len(REPLACE_SURFACES), 4)


class MCPReplaceToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_check_tool_without_path(self):
        result = json.loads(await preset_check_replace(pattern="a(", replacement="x"))
        self.assertTrue(result["ok"])
        self.assertFalse(result["result"]["valid"])
        codes = [f["code"] for f in result["result"]["findings"]]
        self.assertIn("syntax_error", codes)

    async def test_check_tool_with_path_dry_run(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps(_preset()), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()
            before = path.read_text(encoding="utf-8")
            result = json.loads(await preset_check_replace(
                pattern="cinematic", replacement="clinical", mode="literal", path=rel,
            ))
            self.assertTrue(result["ok"])
            self.assertTrue(result["result"]["valid"])
            self.assertEqual(result["result"]["report"]["total_matches"], 5)

            result = json.loads(await preset_check_replace(
                pattern=r"[\s\S]+", replacement="x", mode="regex", path=rel,
            ))
            self.assertTrue(result["ok"])
            self.assertFalse(result["result"]["valid"])
            codes = [f["code"] for f in result["result"]["findings"]]
            self.assertIn("over_broad_match", codes)
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    async def test_replace_tool_saves(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps(_preset()), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(await preset_replace_text(
                path=rel, pattern="cinematic", replacement="clinical", mode="literal",
            ))
            self.assertTrue(result["ok"])
            self.assertTrue(result["result"]["saved"])
            self.assertEqual(result["result"]["total_matches"], 5)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("cinematic", json.dumps(saved))

    async def test_replace_tool_rejects_overbroad_without_save(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps(_preset()), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()
            before = path.read_text(encoding="utf-8")

            result = json.loads(await preset_replace_text(
                path=rel, pattern=r"[\s\S]+", replacement="x", mode="regex",
            ))
            self.assertFalse(result["ok"])
            self.assertIn("NOT modified", result["error"])
            codes = [f["code"] for f in result["detail"]["findings"]]
            self.assertIn("over_broad_match", codes)
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    async def test_replace_tool_dry_run(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps(_preset()), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()
            before = path.read_text(encoding="utf-8")

            result = json.loads(await preset_replace_text(
                path=rel, pattern="cinematic", replacement="clinical", mode="literal",
                dry_run=True,
            ))
            self.assertTrue(result["ok"])
            self.assertFalse(result["result"]["saved"])
            self.assertEqual(path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()

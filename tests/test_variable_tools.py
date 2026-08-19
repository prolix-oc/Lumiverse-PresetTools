"""Tests for prompt variable repair, validation, and MCP round-trips."""

import json
import tempfile
import unittest
from pathlib import Path

from preset_tools.blocks import (
    add_prompt_variable,
    list_prompt_variables,
    update_prompt_variable,
)
from preset_tools.mcp_server import (
    mcp,
    preset_insert_prompt_variable,
    preset_list_prompt_variables,
    preset_update_prompt_variable,
)
from preset_tools.variable_lint import (
    default_value_warnings,
    lint_variable_def,
    normalize_default_value,
    repair_json_payload,
)


def _codes(findings, severity=None):
    return [f["code"] for f in findings if severity is None or f["severity"] == severity]


class RepairJsonPayloadTest(unittest.TestCase):
    def test_valid_json_passes_without_diagnostics(self):
        value, diagnostics, error = repair_json_payload('[{"id":"a","label":"A","value":"1"}]')
        self.assertEqual(value, [{"id": "a", "label": "A", "value": "1"}])
        self.assertEqual((diagnostics, error), ([], ""))

    def test_collapses_over_escaped_quotes(self):
        raw = '[{\\"id\\": \\"a\\", \\"label\\": \\"A\\", \\"value\\": \\"1\\"}]'
        value, diagnostics, error = repair_json_payload(raw)
        self.assertEqual(value, [{"id": "a", "label": "A", "value": "1"}])
        self.assertEqual(_codes(diagnostics), ["json_repair"])

    def test_normalizes_smart_quotes(self):
        raw = '[{\u201cid\u201d: \u201ca\u201d, \u201clabel\u201d: \u201cA\u201d, \u201cvalue\u201d: \u201c1\u201d}]'
        value, diagnostics, _ = repair_json_payload(raw)
        self.assertEqual(value, [{"id": "a", "label": "A", "value": "1"}])
        self.assertEqual(_codes(diagnostics), ["json_repair"])

    def test_parses_python_literals(self):
        raw = "[{'id': 'a', 'label': 'A', 'value': None}, {'id': 'b', 'label': \"B's\", 'value': True},]"
        value, diagnostics, _ = repair_json_payload(raw)
        self.assertEqual(value[0]["value"], None)
        self.assertEqual(value[1]["label"], "B's")
        self.assertEqual(value[1]["value"], True)
        self.assertEqual(_codes(diagnostics), ["python_literal"])

    def test_quotes_bare_keys(self):
        raw = '[{id: "a", label: "A", value: "1"}]'
        value, diagnostics, _ = repair_json_payload(raw)
        self.assertEqual(value, [{"id": "a", "label": "A", "value": "1"}])
        self.assertEqual(_codes(diagnostics), ["json_repair"])

    def test_failure_returns_error(self):
        value, diagnostics, error = repair_json_payload("[{id: a,,}")
        self.assertIsNone(value)
        self.assertTrue(error)

    def test_empty_input(self):
        value, _, error = repair_json_payload("   ")
        self.assertIsNone(value)
        self.assertEqual(error, "empty input")


class NormalizeDefaultValueTest(unittest.TestCase):
    def test_multiselect_over_escaped_array_is_repaired(self):
        value, diagnostics = normalize_default_value("multiselect", '[\\"x\\", \\"y\\"]')
        self.assertEqual(value, ["x", "y"])
        self.assertEqual(_codes(diagnostics), ["json_repair"])

    def test_multiselect_comma_separated_passthrough(self):
        value, diagnostics = normalize_default_value("multiselect", "x, y")
        self.assertEqual((value, diagnostics), ("x, y", []))

    def test_select_strips_stray_quotes(self):
        value, diagnostics = normalize_default_value("select", '"vivid"')
        self.assertEqual(value, "vivid")
        self.assertEqual(_codes(diagnostics), ["stripped_surrounding_quotes"])

    def test_non_string_values_verbatim(self):
        self.assertEqual(normalize_default_value("select", 5), (5, []))

    def test_warnings_for_unparseable_defaults(self):
        self.assertEqual(_codes(default_value_warnings("number", "fifty")), ["unparseable_default"])
        self.assertEqual(_codes(default_value_warnings("slider", "50")), [])
        self.assertEqual(_codes(default_value_warnings("switch", "maybe")), ["unparseable_default"])
        self.assertEqual(_codes(default_value_warnings("switch", "on")), [])
        self.assertEqual(_codes(default_value_warnings("text", "fifty")), [])


class LintVariableDefTest(unittest.TestCase):
    def _var(self, **overrides):
        var = {"id": "x", "name": "v", "label": "V", "type": "switch", "defaultValue": 1}
        var.update(overrides)
        return var

    def test_clean_definition(self):
        self.assertEqual(lint_variable_def(self._var()), [])

    def test_select_default_must_match_option(self):
        var = self._var(type="select", defaultValue="vivid", options=[{"id": "minimalist"}, {"id": "purple"}])
        findings = lint_variable_def(var)
        self.assertEqual(_codes(findings, "error"), ["unknown_option_default"])
        self.assertIn("minimalist", findings[0]["message"])

    def test_multiselect_defaults_must_match_options(self):
        var = self._var(
            type="multiselect", defaultValue=["a", "typo"],
            options=[{"id": "a"}, {"id": "b"}],
        )
        self.assertEqual(_codes(lint_variable_def(var), "error"), ["unknown_option_default"])

    def test_duplicate_option_ids(self):
        var = self._var(type="select", defaultValue="a", options=[{"id": "a"}, {"id": "a"}])
        self.assertEqual(_codes(lint_variable_def(var), "error"), ["duplicate_option_id"])

    def test_range_checks(self):
        self.assertEqual(_codes(lint_variable_def(self._var(type="slider", min=10, max=5)), "error"), ["reversed_range"])
        self.assertEqual(_codes(lint_variable_def(self._var(type="slider", min=5, max=5)), "warning"), ["degenerate_range"])
        self.assertEqual(_codes(lint_variable_def(self._var(type="number", step=0)), "error"), ["invalid_step"])

    def test_duplicate_and_unusual_names(self):
        self.assertEqual(
            _codes(lint_variable_def(self._var(name="v"), existing_names=["v"]), "error"),
            ["duplicate_variable_name"],
        )
        self.assertEqual(
            _codes(lint_variable_def(self._var(name="my var")), "warning"),
            ["unusual_variable_name"],
        )

    def test_ignored_fields_reported(self):
        findings = lint_variable_def(self._var(), ignored_fields=[{"field": "rows", "reason": "rows only applies to textarea"}])
        self.assertEqual(_codes(findings, "warning"), ["ignored_field"])


class BlocksVariableTest(unittest.TestCase):
    def _preset(self):
        return {"blocks": [{"name": "Utilities", "content": "{{var::cyoa_mode}} toggle"}]}

    def test_add_rejects_duplicate_names(self):
        preset = self._preset()
        add_prompt_variable(preset, "Utilities", "cyoa_mode", "CYOA", "switch")
        with self.assertRaisesRegex(ValueError, "already exists"):
            add_prompt_variable(preset, "Utilities", "cyoa_mode", "Again", "switch")

    def test_update_preserves_id_and_untouched_fields(self):
        preset = self._preset()
        created = add_prompt_variable(
            preset, "Utilities", "flavor", "Flavor", "select", default_value="a",
            options=[{"id": "a", "label": "A", "value": "1"}, {"id": "b", "label": "B", "value": "2"}],
        )
        updated = update_prompt_variable(preset, "Utilities", "flavor", {"defaultValue": "b"})
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["defaultValue"], "b")
        self.assertEqual(len(updated["options"]), 2)

    def test_update_recoerces_default_when_type_changes(self):
        preset = self._preset()
        add_prompt_variable(preset, "Utilities", "n", "N", "number", default_value="42")
        updated = update_prompt_variable(preset, "Utilities", "n", {"type": "switch"})
        self.assertEqual(updated["type"], "switch")
        self.assertEqual(updated["defaultValue"], 1)

    def test_update_rejects_duplicate_name(self):
        preset = self._preset()
        add_prompt_variable(preset, "Utilities", "a", "A", "switch")
        add_prompt_variable(preset, "Utilities", "b", "B", "switch")
        with self.assertRaisesRegex(ValueError, "already exists"):
            update_prompt_variable(preset, "Utilities", "b", {"name": "a"})

    def test_list_detects_macro_references(self):
        preset = self._preset()
        add_prompt_variable(preset, "Utilities", "cyoa_mode", "CYOA", "switch")
        add_prompt_variable(preset, "Utilities", "unused", "Unused", "switch", )
        listed = list_prompt_variables(preset)
        self.assertEqual(len(listed), 1)
        by_name = {v["name"]: v for v in listed[0]["variables"]}
        self.assertTrue(by_name["cyoa_mode"]["macro_in_content"])
        self.assertFalse(by_name["unused"]["macro_in_content"])


class MCPVariableToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_insert_with_structured_options(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps({"blocks": [{"name": "U", "content": ""}]}), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="style", label="Style",
                var_type="select", default_value="vivid",
                options=[{"id": "vivid", "label": "Vivid", "value": "vivid prose"}],
            ))
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["variable"]["options"][0]["id"], "vivid")
            self.assertEqual(result["result"]["diagnostics"], [])
            self.assertIn("{{var::style}}", json.loads(path.read_text())["blocks"][0]["content"])

    async def test_insert_repairs_mangled_options_json_and_multiselect_default(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps({"blocks": [{"name": "U", "content": ""}]}), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()

            mangled = '[{\\"id\\":\\"x\\",\\"label\\":\\"X\\",\\"value\\":\\"1\\"},{\\"id\\":\\"y\\",\\"label\\":\\"Y\\",\\"value\\":\\"2\\"}]'
            result = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="multi", label="Multi",
                var_type="multiselect", default_value='[\\"x\\",\\"y\\"]',
                options_json=mangled,
            ))
            self.assertTrue(result["ok"])
            saved = json.loads(path.read_text())["blocks"][0]["variables"][0]
            self.assertEqual(saved["defaultValue"], ["x", "y"])
            self.assertEqual(saved["options"][1]["label"], "Y")
            codes = [d["code"] for d in result["result"]["diagnostics"]]
            self.assertIn("json_repair", codes)

    async def test_insert_blocks_unknown_default_and_reports_ignored_fields(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps({"blocks": [{"name": "U", "content": ""}]}), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="s", label="S",
                var_type="select", default_value="vivd",
                options=[{"id": "vivid", "label": "V", "value": "v"}],
                rows=5,
            ))
            self.assertFalse(result["ok"])
            self.assertEqual(result["detail"]["findings"][0]["code"], "unknown_option_default")
            self.assertEqual(json.loads(path.read_text())["blocks"][0].get("variables"), None)

            result = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="s", label="S",
                var_type="select", default_value="vivd",
                options=[{"id": "vivid", "label": "V", "value": "v"}],
                rows=5, strict=False,
            ))
            self.assertTrue(result["ok"])
            codes = [d["code"] for d in result["result"]["diagnostics"]]
            self.assertIn("unknown_option_default", codes)
            self.assertIn("ignored_field", codes)

    async def test_insert_skips_duplicate_macro(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(
                json.dumps({"blocks": [{"name": "U", "content": "Uses {{var::mode}} already"}]}),
                encoding="utf-8",
            )
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="mode", label="Mode", var_type="switch",
            ))
            self.assertTrue(result["ok"])
            self.assertIsNone(result["result"]["inserted_macro"])
            content = json.loads(path.read_text())["blocks"][0]["content"]
            self.assertEqual(content.count("{{var::mode}}"), 1)
            codes = [d["code"] for d in result["result"]["diagnostics"]]
            self.assertIn("macro_already_present", codes)

    async def test_update_tool_repairs_options_string_and_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps({"blocks": [{"name": "U", "content": ""}]}), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()

            created = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="f", label="F", var_type="select",
                default_value="a",
                options=[{"id": "a", "label": "A", "value": "1"}],
            ))
            self.assertTrue(created["ok"])

            mangled = '[{\\"id\\":\\"a\\",\\"label\\":\\"A\\",\\"value\\":\\"1\\"},{\\"id\\":\\"b\\",\\"label\\":\\"B\\",\\"value\\":\\"2\\"}]'
            updated = json.loads(await preset_update_prompt_variable(
                path=rel, block_name="U", var_name="f",
                updates={"default_value": "b", "options": mangled},
            ))
            self.assertTrue(updated["ok"])
            self.assertEqual(updated["result"]["variable"]["defaultValue"], "b")
            self.assertEqual(len(updated["result"]["variable"]["options"]), 2)

            rejected = json.loads(await preset_update_prompt_variable(
                path=rel, block_name="U", var_name="f",
                updates={"defualt_value": "a"},
            ))
            self.assertFalse(rejected["ok"])
            self.assertIn("defualt_value", rejected["error"])

    async def test_update_failure_leaves_file_untouched(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(json.dumps({"blocks": [{"name": "U", "content": ""}]}), encoding="utf-8")
            rel = path.relative_to(Path.cwd()).as_posix()

            created = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="n", label="N", var_type="number",
                default_value="10", min_value=1, max_value=20,
            ))
            self.assertTrue(created["ok"])
            before = path.read_text(encoding="utf-8")

            failed = json.loads(await preset_update_prompt_variable(
                path=rel, block_name="U", var_name="n",
                updates={"min": 50},
            ))
            self.assertFalse(failed["ok"])
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    async def test_rename_rewrites_macro_references(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(
                json.dumps({
                    "blocks": [
                        {"name": "U", "content": "{{var::old}} and {{getvar::old}} and {{var::old::ison::k}}"},
                        {"name": "V", "content": "{{var::old}} again"},
                    ],
                    "metadata": {"promptVariables": {"u-id": {"old": 1, "other": 2}}},
                }),
                encoding="utf-8",
            )
            rel = path.relative_to(Path.cwd()).as_posix()

            created = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="old", label="Old", var_type="switch",
                insert_macro=False,
            ))
            self.assertTrue(created["ok"])

            result = json.loads(await preset_update_prompt_variable(
                path=rel, block_name="U", var_name="old", updates={"name": "new"},
            ))
            self.assertTrue(result["ok"])
            codes = [d["code"] for d in result["result"]["diagnostics"]]
            self.assertIn("rewrote_macro_references", codes)
            self.assertNotIn("stale_macro_reference", codes)

            saved = json.loads(path.read_text(encoding="utf-8"))
            contents = [b["content"] for b in saved["blocks"]]
            self.assertEqual(contents, [
                "{{var::new}} and {{getvar::new}} and {{var::new::ison::k}}",
                "{{var::new}} again",
            ])
            self.assertEqual(
                saved["metadata"]["promptVariables"]["u-id"],
                {"new": 1, "other": 2},
            )

    async def test_rename_without_rewrite_keeps_warning(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(
                json.dumps({"blocks": [{"name": "U", "content": "{{var::old}} here"}]}),
                encoding="utf-8",
            )
            rel = path.relative_to(Path.cwd()).as_posix()

            created = json.loads(await preset_insert_prompt_variable(
                path=rel, block_name="U", name="old", label="Old", var_type="switch",
                insert_macro=False,
            ))
            self.assertTrue(created["ok"])

            result = json.loads(await preset_update_prompt_variable(
                path=rel, block_name="U", var_name="old", updates={"name": "new"},
                rewrite_references=False,
            ))
            self.assertTrue(result["ok"])
            codes = [d["code"] for d in result["result"]["diagnostics"]]
            self.assertIn("stale_macro_reference", codes)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["blocks"][0]["content"], "{{var::old}} here")

    async def test_list_tool(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "p.json"
            path.write_text(
                json.dumps({"blocks": [{"name": "U", "content": "{{var::a}}", "variables": [
                    {"id": "1", "name": "a", "label": "A", "type": "switch", "defaultValue": 1},
                ]}]}),
                encoding="utf-8",
            )
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(await preset_list_prompt_variables(path=rel))
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["total_variables"], 1)
            entry = result["result"]["blocks"][0]["variables"][0]
            self.assertEqual(entry["name"], "a")
            self.assertTrue(entry["macro_in_content"])


class MCPVariableSchemaTest(unittest.TestCase):
    def test_insert_schema_has_structured_options_and_gates(self):
        params = mcp._tool_manager._tools["preset_insert_prompt_variable"].parameters
        for prop in ("options", "options_json", "repair_escapes", "strict"):
            self.assertIn(prop, params["properties"])
        self.assertTrue(params["properties"]["repair_escapes"]["default"])
        self.assertTrue(params["properties"]["strict"]["default"])

    def test_update_and_list_tools_registered(self):
        self.assertIn("preset_update_prompt_variable", mcp._tool_manager._tools)
        self.assertIn("preset_list_prompt_variables", mcp._tool_manager._tools)
        update_params = mcp._tool_manager._tools["preset_update_prompt_variable"].parameters
        self.assertEqual(update_params["required"], ["path", "block_name", "var_name", "updates"])


if __name__ == "__main__":
    unittest.main()

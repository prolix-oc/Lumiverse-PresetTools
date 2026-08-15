import json
import tempfile
import unittest
from pathlib import Path

from preset_tools.regex_scripts import (
    delete_regex_script,
    find_regex_script,
    insert_regex_script,
    new_regex_export,
    new_regex_script,
    regex_scripts,
    update_regex_script,
    validate_regex_document,
)
from preset_tools.mcp_server import (
    mcp,
    regex_create_script,
    regex_delete_script as mcp_regex_delete_script,
    regex_get_script,
    regex_list_scripts,
    regex_update_script,
    regex_validate,
)


def _script(script_id: str = "scene_card") -> dict:
    return new_regex_script(
        name="Scene Card — Interactive",
        script_id=script_id,
        find_regex=r"<card>(?<body>[\s\S]*?)</card>",
        replace_string='<section class="card">$<body></section>',
        description="Renders a scene card.",
        options={
            "folder": "Interactive Cards",
            "actions": [
                {
                    "id": "continue",
                    "type": "send",
                    "title": "Continue",
                    "content": "Continue.",
                }
            ],
        },
    )


class RegexHelpersTest(unittest.TestCase):
    def test_detects_and_edits_both_document_shapes(self) -> None:
        preset = {"blocks": [], "extensions": {"unrelated": {"keep": True}}}
        export = new_regex_export()

        preset_index, preset_kind = insert_regex_script(preset, _script(), container="preset")
        export_index, export_kind = insert_regex_script(export, _script())

        self.assertEqual((preset_index, preset_kind), (0, "preset"))
        self.assertEqual((export_index, export_kind), (0, "standalone"))
        self.assertEqual(preset["extensions"]["unrelated"], {"keep": True})
        self.assertEqual(preset["extensions"]["regex_scripts"][0]["script_id"], "scene_card")
        self.assertEqual(export["scripts"][0]["script_id"], "scene_card")

    def test_update_is_partial_and_delete_returns_removed_script(self) -> None:
        document = new_regex_export()
        insert_regex_script(document, _script())

        updated, index, kind = update_regex_script(
            document,
            "scene_card",
            {"replace_string": "<div>$<body></div>", "disabled": True},
            remove_fields=["folder"],
        )

        self.assertEqual((index, kind), (0, "standalone"))
        self.assertEqual(updated["find_regex"], r"<card>(?<body>[\s\S]*?)</card>")
        self.assertEqual(updated["replace_string"], "<div>$<body></div>")
        self.assertTrue(updated["disabled"])
        self.assertNotIn("folder", updated)

        removed, removed_index, _ = delete_regex_script(document, "Scene Card — Interactive")
        self.assertEqual(removed_index, 0)
        self.assertEqual(removed["script_id"], "scene_card")
        self.assertEqual(document["scripts"], [])

    def test_rejects_duplicate_ids_and_invalid_updates_atomically(self) -> None:
        document = new_regex_export()
        insert_regex_script(document, _script())

        with self.assertRaisesRegex(ValueError, "already exists"):
            insert_regex_script(document, _script())
        with self.assertRaisesRegex(ValueError, "unsupported JavaScript flags"):
            update_regex_script(document, "scene_card", {"flags": "giz"})

        stored, _, _ = find_regex_script(document, "scene_card")
        self.assertEqual(stored["flags"], "gi")
        self.assertEqual(len(document["scripts"]), 1)

    def test_validation_accepts_javascript_named_capture_syntax(self) -> None:
        document = new_regex_export()
        insert_regex_script(document, _script())

        result = validate_regex_document(document)

        self.assertTrue(result["ok"])
        self.assertEqual(result["container"], "standalone")
        self.assertEqual(result["script_count"], 1)

    def test_empty_regex_list_is_valid_for_preset_without_extensions(self) -> None:
        scripts, kind = regex_scripts({"blocks": []})
        result = validate_regex_document({"blocks": []})

        self.assertEqual(scripts, [])
        self.assertEqual(kind, "preset")
        self.assertTrue(result["ok"])


class MCPRegexToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_create_list_get_update_validate_delete_round_trip(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "cards.json"
            rel = path.relative_to(Path.cwd()).as_posix()

            create_raw = await regex_create_script(
                path=rel,
                container="standalone",
                name="Stella Card — Interactive",
                script_id="stella_card",
                find_regex=r"<card>(?<body>[\s\S]*?)</card>",
                replace_string="<section>$<body></section>",
                options={
                    "actions": [{"id": "choose", "type": "send", "content": "Choose."}],
                    "folder": "Stella Interactive Cards",
                },
            )
            created = json.loads(create_raw)
            self.assertTrue(created["ok"])
            self.assertEqual(created["result"]["container"], "standalone")

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["type"], "lumiverse_regex_scripts")
            self.assertEqual(saved["version"], 1)
            self.assertEqual(saved["scripts"][0]["scope_id"], None)
            self.assertEqual(saved["scripts"][0]["trim_strings"], [])
            self.assertEqual(saved["scripts"][0]["actions"][0]["id"], "choose")

            listed = json.loads(await regex_list_scripts(path=rel))
            self.assertEqual(listed["result"]["scripts"][0]["actions"], 1)

            fetched = json.loads(await regex_get_script(path=rel, identifier="stella_card"))
            self.assertEqual(fetched["result"]["script"]["folder"], "Stella Interactive Cards")

            updated = json.loads(
                await regex_update_script(
                    path=rel,
                    identifier="stella_card",
                    updates={"description": "Updated — Unicode preserved.", "sort_order": 120},
                    remove_fields=["folder"],
                )
            )
            self.assertTrue(updated["ok"])
            self.assertNotIn("folder", updated["result"]["script"])
            self.assertIn("—", path.read_text(encoding="utf-8"))

            validated = json.loads(await regex_validate(path=rel))
            self.assertTrue(validated["ok"])
            self.assertTrue(validated["result"]["ok"])

            deleted = json.loads(await mcp_regex_delete_script(path=rel, identifier="stella_card"))
            self.assertTrue(deleted["ok"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["scripts"], [])

    async def test_create_embedded_script_preserves_other_preset_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "preset.json"
            path.write_text(
                json.dumps({"blocks": [{"name": "Keep me"}], "extensions": {"other": 42}}),
                encoding="utf-8",
            )
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(
                await regex_create_script(
                    path=rel,
                    name="Hide Card",
                    script_id="hide_card",
                    find_regex=r"<card>[\s\S]*?</card>\n*",
                    replace_string="",
                    target=["prompt"],
                    options={"min_depth": 3},
                )
            )

            self.assertTrue(result["ok"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["blocks"], [{"name": "Keep me"}])
            self.assertEqual(saved["extensions"]["other"], 42)
            self.assertEqual(saved["extensions"]["regex_scripts"][0]["target"], ["prompt"])
            self.assertEqual(saved["extensions"]["regex_scripts"][0]["min_depth"], 3)

    async def test_missing_file_requires_standalone_container(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "missing.json"
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(
                await regex_create_script(
                    path=rel,
                    name="Test",
                    script_id="test",
                    find_regex="test",
                    replace_string="test",
                )
            )

            self.assertFalse(result["ok"])
            self.assertFalse(path.exists())

    async def test_create_repairs_literal_delimiters_and_doubled_backslashes(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "cards.json"
            rel = path.relative_to(Path.cwd()).as_posix()

            # Simulates the classic tool-call escaping mistake: a /.../gi
            # literal whose backslashes arrived doubled.
            raw_pattern = "/<card>(?<body>[" + "\\\\" + "s" + "\\\\" + "S]*?)</card>/gi"
            raw_replacement = '<section class=' + '\\"' + 'card' + '\\"' + '>$<body></section>'

            result = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="Repaired Card",
                    script_id="repaired_card",
                    find_regex=raw_pattern,
                    replace_string=raw_replacement,
                )
            )

            self.assertTrue(result["ok"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["scripts"][0]["find_regex"], r"<card>(?<body>[\s\S]*?)</card>")
            self.assertEqual(saved["scripts"][0]["flags"], "gi")
            self.assertEqual(saved["scripts"][0]["replace_string"], '<section class="card">$<body></section>')
            diag_codes = [d["code"] for d in result["result"]["diagnostics"]]
            self.assertIn("stripped_literal", diag_codes)
            self.assertIn("collapsed_backslashes", diag_codes)
            self.assertIn("unescaped_replacement", diag_codes)

    async def test_create_reads_payloads_from_files(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            base = Path(tmpdir)
            path = base / "cards.json"
            pattern_file = base / "pattern.txt"
            html_file = base / "card.html"
            rel = path.relative_to(Path.cwd()).as_posix()

            pattern = r"<card>\s*(?<body>[\s\S]*?)\s*</card>"
            html = '<section class="card">\n  $<body>\n</section>'
            pattern_file.write_text(pattern + "\n", encoding="utf-8")
            html_file.write_text(html, encoding="utf-8")

            result = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="File Card",
                    script_id="file_card",
                    find_regex_file=pattern_file.relative_to(Path.cwd()).as_posix(),
                    replace_string_file=html_file.relative_to(Path.cwd()).as_posix(),
                )
            )

            self.assertTrue(result["ok"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            # Pattern files are whitespace-trimmed; replacement files verbatim.
            self.assertEqual(saved["scripts"][0]["find_regex"], pattern)
            self.assertEqual(saved["scripts"][0]["replace_string"], html)

    async def test_create_rejects_conflicting_payload_sources(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "cards.json"
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="X", script_id="x",
                    find_regex="a", find_regex_file="nonexistent.txt",
                )
            )
            self.assertFalse(result["ok"])
            self.assertIn("not both", result["error"])

    async def test_create_blocks_unknown_group_reference_without_saving(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "cards.json"
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="Bad Ref", script_id="bad_ref",
                    find_regex=r"<card>(?<body>[\s\S]*?)</card>",
                    replace_string="<p>$<boby></p>",
                )
            )

            self.assertFalse(result["ok"])
            self.assertFalse(path.exists())
            findings = result["detail"]["findings"]
            self.assertEqual(findings[0]["code"], "unknown_group_ref")

            # strict=False saves anyway and reports the finding.
            result = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="Bad Ref", script_id="bad_ref",
                    find_regex=r"<card>(?<body>[\s\S]*?)</card>",
                    replace_string="<p>$<boby></p>",
                    strict=False,
                )
            )
            self.assertTrue(result["ok"])
            diag_codes = [d["code"] for d in result["result"]["diagnostics"]]
            self.assertIn("unknown_group_ref", diag_codes)

    async def test_create_blocks_engine_syntax_error(self) -> None:
        from preset_tools.regex_lint import engine_kind

        if engine_kind() is None:
            self.skipTest("no JavaScript engine available")
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "cards.json"
            rel = path.relative_to(Path.cwd()).as_posix()

            result = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="Broken", script_id="broken",
                    find_regex="(?<x>a){2,1}",
                    replace_string="x",
                )
            )
            self.assertFalse(result["ok"])
            self.assertFalse(path.exists())
            self.assertIn(
                "engine_syntax_error",
                [f["code"] for f in result["detail"]["findings"]],
            )

    async def test_update_replaces_payloads_from_files_and_leaves_file_intact_on_error(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            base = Path(tmpdir)
            path = base / "cards.json"
            html_file = base / "new.html"
            rel = path.relative_to(Path.cwd()).as_posix()

            created = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="Old Card", script_id="old_card",
                    find_regex=r"<card>(?<body>[\s\S]*?)</card>",
                    replace_string="<p>$<body></p>",
                )
            )
            self.assertTrue(created["ok"])
            before = path.read_text(encoding="utf-8")

            html_file.write_text('<div>$<nope></div>', encoding="utf-8")
            failed = json.loads(
                await regex_update_script(
                    path=rel,
                    identifier="old_card",
                    updates={},
                    replace_string_file=html_file.relative_to(Path.cwd()).as_posix(),
                )
            )
            self.assertFalse(failed["ok"])
            self.assertEqual(path.read_text(encoding="utf-8"), before)

            html_file.write_text('<div>$<body></div>', encoding="utf-8")
            updated = json.loads(
                await regex_update_script(
                    path=rel,
                    identifier="old_card",
                    updates={},
                    replace_string_file=html_file.relative_to(Path.cwd()).as_posix(),
                )
            )
            self.assertTrue(updated["ok"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["scripts"][0]["replace_string"], "<div>$<body></div>")

    async def test_update_repairs_escapes_in_updates_object(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "cards.json"
            rel = path.relative_to(Path.cwd()).as_posix()

            created = json.loads(
                await regex_create_script(
                    path=rel,
                    container="standalone",
                    name="Esc Card", script_id="esc_card",
                    find_regex=r"<card>(?<body>[\s\S]*?)</card>",
                    replace_string="<p>$<body></p>",
                )
            )
            self.assertTrue(created["ok"])

            raw_pattern = "/(?P<what>" + "\\\\" + "S*)/g"
            updated = json.loads(
                await regex_update_script(
                    path=rel,
                    identifier="esc_card",
                    updates={"find_regex": raw_pattern, "replace_string": "line1\\nline2"},
                )
            )
            self.assertTrue(updated["ok"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["scripts"][0]["find_regex"], r"(?<what>\S*)")
            self.assertEqual(saved["scripts"][0]["replace_string"], "line1\nline2")
            diag_codes = [d["code"] for d in updated["result"]["diagnostics"]]
            self.assertIn("python_named_group", diag_codes)


class MCPRegexSchemaTest(unittest.TestCase):
    def test_create_schema_requires_only_core_script_fields(self) -> None:
        params = mcp._tool_manager._tools["regex_create_script"].parameters

        self.assertEqual(params["required"], ["path", "name", "script_id"])
        for prop in (
            "find_regex", "replace_string", "find_regex_file", "replace_string_file",
            "repair_escapes", "strict",
        ):
            self.assertIn(prop, params["properties"])
        self.assertEqual(params["properties"]["container"]["default"], "auto")
        self.assertTrue(params["properties"]["repair_escapes"]["default"])
        self.assertTrue(params["properties"]["strict"]["default"])

    def test_update_schema_accepts_structured_patch(self) -> None:
        params = mcp._tool_manager._tools["regex_update_script"].parameters

        self.assertEqual(params["required"], ["path", "identifier", "updates"])
        self.assertEqual(params["properties"]["updates"]["type"], "object")
        for prop in ("find_regex_file", "replace_string_file", "repair_escapes", "strict"):
            self.assertIn(prop, params["properties"])

    def test_check_pattern_tool_registered(self) -> None:
        params = mcp._tool_manager._tools["regex_check_pattern"].parameters
        self.assertEqual(params["required"], ["pattern"])

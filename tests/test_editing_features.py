"""Tests for diff, move/clone, stored prompt-variable, and backup features."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from preset_tools.blocks import (
    clone_block,
    move_block,
    set_stored_prompt_variable,
    stored_variable_report,
)
from preset_tools.compare import diff_presets
from preset_tools.backup import backup_file, list_backups, restore_backup


def _preset():
    return {
        "blocks": [
            {"id": "a", "name": "Intro", "content": "hello world\n", "enabled": True, "variables": []},
            {"id": "b", "name": "Body", "content": "the body text\n", "enabled": True, "variables": []},
            {"id": "c", "name": "Outro", "content": "goodbye\n", "enabled": True, "variables": []},
        ]
    }


class DiffPresetsTest(unittest.TestCase):
    def test_identical(self):
        a = _preset()
        b = _preset()
        result = diff_presets(a, b)
        self.assertEqual(result["summary"]["changed"], 0)

    def test_content_change(self):
        a = _preset()
        b = _preset()
        b["blocks"][1]["content"] = "the changed body\n"
        result = diff_presets(a, b)
        self.assertEqual(result["summary"]["changed"], 1)
        self.assertEqual(result["changed_blocks"][0]["name"], "Body")
        self.assertIn("-the body text", result["changed_blocks"][0]["diff"])
        self.assertIn("+the changed body", result["changed_blocks"][0]["diff"])

    def test_only_in(self):
        a = _preset()
        b = _preset()
        b["blocks"].append({"id": "d", "name": "Extra", "content": "x", "enabled": True})
        result = diff_presets(a, b)
        self.assertEqual(result["summary"]["only_b"], 1)
        self.assertEqual(result["only_in_b"], ["Extra"])

    def test_enabled_change(self):
        a = _preset()
        b = _preset()
        b["blocks"][0]["enabled"] = False
        result = diff_presets(a, b)
        self.assertEqual(result["changed_blocks"][0]["enabled"], {"a": True, "b": False})


class MoveBlockTest(unittest.TestCase):
    def test_move_after(self):
        p = _preset()
        move_block(p, "Outro", after="Intro")
        self.assertEqual([b["name"] for b in p["blocks"]], ["Intro", "Outro", "Body"])

    def test_move_before(self):
        p = _preset()
        move_block(p, "Intro", before="Outro")
        self.assertEqual([b["name"] for b in p["blocks"]], ["Body", "Intro", "Outro"])

    def test_move_at_index(self):
        p = _preset()
        move_block(p, "Outro", at_index=0)
        self.assertEqual([b["name"] for b in p["blocks"]], ["Outro", "Intro", "Body"])

    def test_move_missing_raises(self):
        p = _preset()
        with self.assertRaises(ValueError):
            move_block(p, "Nope", after="Intro")

    def test_move_relative_to_self_raises(self):
        p = _preset()
        with self.assertRaises(ValueError):
            move_block(p, "Intro", after="Intro")

    def test_move_requires_one_target(self):
        p = _preset()
        with self.assertRaises(ValueError):
            move_block(p, "Intro")


class CloneBlockTest(unittest.TestCase):
    def test_clone_defaults_after_source(self):
        p = _preset()
        clone = clone_block(p, "Body")
        self.assertEqual(clone["name"], "Body (copy)")
        self.assertNotEqual(clone["id"], "b")
        self.assertEqual([b["name"] for b in p["blocks"]],
                         ["Intro", "Body", "Body (copy)", "Outro"])

    def test_clone_custom_name_and_position(self):
        p = _preset()
        clone = clone_block(p, "Intro", "Intro 2", before="Body")
        self.assertEqual(clone["name"], "Intro 2")
        self.assertEqual([b["name"] for b in p["blocks"]],
                         ["Intro", "Intro 2", "Body", "Outro"])

    def test_clone_regenerates_sealed_key(self):
        p = _preset()
        p["blocks"][0]["sealed"] = True
        p["blocks"][0]["sealedKey"] = "intro"
        clone = clone_block(p, "Intro", "Intro B")
        self.assertEqual(clone["sealedKey"], "intro-b")


class StoredPromptVariableTest(unittest.TestCase):
    def test_report_empty(self):
        self.assertEqual(stored_variable_report(_preset()), [])

    def test_set_and_report(self):
        p = _preset()
        p["blocks"][1]["variables"] = [
            {"id": "v", "name": "flag", "type": "switch", "defaultValue": 0}
        ]
        result = set_stored_prompt_variable(p, "Body", "flag", 1)
        self.assertEqual(result["value"], 1)
        report = stored_variable_report(p)
        self.assertEqual(report[0]["block"], "Body")
        self.assertEqual(report[0]["values"], {"flag": 1})

    def test_set_unknown_variable_raises(self):
        p = _preset()
        with self.assertRaises(ValueError):
            set_stored_prompt_variable(p, "Body", "nope", 1)

    def test_remove(self):
        p = _preset()
        p["blocks"][1]["variables"] = [
            {"id": "v", "name": "flag", "type": "switch", "defaultValue": 0}
        ]
        set_stored_prompt_variable(p, "Body", "flag", 1)
        set_stored_prompt_variable(p, "Body", "flag", None, remove=True)
        self.assertEqual(stored_variable_report(p), [])

    def test_switch_coercion(self):
        p = _preset()
        p["blocks"][1]["variables"] = [
            {"id": "v", "name": "flag", "type": "switch", "defaultValue": 0}
        ]
        result = set_stored_prompt_variable(p, "Body", "flag", "true")
        self.assertEqual(result["value"], 1)


class BackupTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.file = self.dir / "preset.json"
        self.file.write_text(json.dumps(_preset()), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_backup_creates_copy(self):
        self.assertEqual(list_backups(str(self.file)), [])
        path = backup_file(str(self.file))
        self.assertIsNotNone(path)
        self.assertEqual(len(list_backups(str(self.file))), 1)
        self.assertEqual(Path(path).read_text(encoding="utf-8"),
                         self.file.read_text(encoding="utf-8"))

    def test_restore(self):
        original = self.file.read_text(encoding="utf-8")
        backup_path = backup_file(str(self.file))
        self.file.write_text("modified", encoding="utf-8")
        restore_backup(str(self.file), Path(backup_path).name)
        self.assertEqual(self.file.read_text(encoding="utf-8"), original)

    def test_restore_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            restore_backup(str(self.file), "nonexistent.json")

    def test_backup_dir_env(self):
        os.environ["PRESET_TOOLS_BACKUP_DIR"] = str(self.dir / "custom-backups")
        try:
            path = backup_file(str(self.file))
            self.assertIn("custom-backups", path)
        finally:
            del os.environ["PRESET_TOOLS_BACKUP_DIR"]


if __name__ == "__main__":
    unittest.main()

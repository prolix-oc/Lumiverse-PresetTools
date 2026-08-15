import json
import tempfile
import unittest
from pathlib import Path

from preset_tools.mcp_server import (
    character_card_field_stats,
    character_card_get_field,
    character_card_get_summary,
    character_card_read,
    character_card_set_field,
    character_card_set_fields,
    character_card_validate,
)


def _sample_card(**overrides) -> dict:
    card = {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": {
            "name": "Test Character",
            "description": "A test description.",
            "personality": "Friendly.",
            "scenario": "A test scenario.",
            "first_mes": "Hello!",
            "mes_example": "",
            "creator": "",
            "creator_notes": "",
            "system_prompt": "",
            "post_history_instructions": "",
            "tags": ["test", "unit"],
            "alternate_greetings": [],
            "character_version": "1.0",
            "extensions": {
                "talkativeness": 0.5,
                "world": "",
                "depth_prompt": {"prompt": "", "depth": 4, "role": "system"},
            },
        },
    }
    card["data"].update(overrides)
    return card


class CharacterCardToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_validate_passes_for_good_card(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_validate(path=rel)
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertTrue(result["result"]["ok"])
            self.assertEqual(result["result"]["errors"], [])

    async def test_validate_fails_for_missing_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps({"spec": "chara_card_v3"}))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_validate(path=rel)
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertFalse(result["result"]["ok"])
            self.assertIn("Missing top-level 'data' key", result["result"]["errors"])

    async def test_read_whole_data(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_read(path=rel)
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["data"]["name"], "Test Character")

    async def test_read_filtered_fields(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_read(path=rel, fields=["name", "scenario"])
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["fields"]["name"], "Test Character")
            self.assertEqual(result["result"]["fields"]["scenario"], "A test scenario.")
            self.assertNotIn("description", result["result"]["fields"])

    async def test_get_field_dot_notation(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_get_field(path=rel, field="extensions.talkativeness")
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["value"], 0.5)

    async def test_set_field_and_save(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_set_field(path=rel, field="personality", value="Grumpy.")
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertTrue(result["result"]["saved"])

            saved = json.loads(path.read_text())
            self.assertEqual(saved["data"]["personality"], "Grumpy.")

    async def test_set_field_dot_notation_creates_intermediate_dict(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_set_field(
                path=rel, field="extensions.custom.foo", value="bar"
            )
            result = json.loads(raw)
            self.assertTrue(result["ok"])

            saved = json.loads(path.read_text())
            self.assertEqual(saved["data"]["extensions"]["custom"]["foo"], "bar")

    async def test_get_summary(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_get_summary(path=rel)
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            summary = result["result"]["summary"]
            self.assertEqual(summary["name"]["chars"], len("Test Character"))
            self.assertEqual(summary["tags"]["items"], 2)
            self.assertIn("talkativeness", summary["extensions"])

    async def test_set_fields_batch(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_set_fields(
                path=rel,
                updates={
                    "name": "Updated Name",
                    "extensions.talkativeness": 0.8,
                },
            )
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["updated_fields"], ["name", "extensions.talkativeness"])

            saved = json.loads(path.read_text())
            self.assertEqual(saved["data"]["name"], "Updated Name")
            self.assertEqual(saved["data"]["extensions"]["talkativeness"], 0.8)

    async def test_field_stats(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            path = Path(tmpdir) / "card.json"
            path.write_text(json.dumps(_sample_card()))
            rel = path.relative_to(Path.cwd()).as_posix()

            raw = await character_card_field_stats(path=rel, field="description")
            result = json.loads(raw)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["chars"], len("A test description."))
            self.assertEqual(result["result"]["type"], "str")

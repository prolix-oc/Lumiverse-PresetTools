"""Tests for the unified preset search (blocks, variables, categories)."""

import unittest

from preset_tools.search import (
    block_categories,
    list_categories,
    search_preset,
)


def _preset():
    return {
        "blocks": [
            {
                "id": "c1",
                "name": "Voice Shaping",
                "marker": "category",
                "enabled": True,
                "content": "</prev>\n\n<voice>",
                "variables": [],
            },
            {
                "id": "b1",
                "name": "Dialogue",
                "marker": None,
                "enabled": True,
                "content": "Keep the banter sharp. {{var::snark}}",
                "variables": [
                    {
                        "id": "v1",
                        "name": "snark",
                        "label": "Snark Level",
                        "type": "slider",
                        "defaultValue": 3,
                        "min": 0,
                        "max": 5,
                    }
                ],
            },
            {
                "id": "b2",
                "name": "Pacing",
                "marker": None,
                "enabled": False,
                "content": "Sweeping cinematic narration with slow-burn reveals.",
                "variables": [
                    {
                        "id": "v2",
                        "name": "pov",
                        "label": "Point of View",
                        "type": "select",
                        "defaultValue": "third",
                        "description": "Choose who tells the story.",
                        "options": [
                            {"id": "first", "label": "First Person", "value": "first-person"},
                            {"id": "third", "label": "Third Person", "value": "third-person"},
                        ],
                    }
                ],
            },
            {
                "id": "c2",
                "name": "Story Arc",
                "marker": "category",
                "enabled": True,
                "content": "</voice>\n\n<arc>",
                "variables": [],
            },
        ]
    }


class BlockCategoriesTest(unittest.TestCase):
    def test_category_membership(self):
        cats = block_categories(_preset())
        self.assertEqual([c["category"] for c in cats], [
            "Voice Shaping", "Voice Shaping", "Voice Shaping", "Story Arc",
        ])

    def test_list_categories(self):
        self.assertEqual(list_categories(_preset()), ["Voice Shaping", "Story Arc"])


class SearchPresetTest(unittest.TestCase):
    def test_block_name_case_insensitive(self):
        result = search_preset(_preset(), "dialogue")
        types = [m["type"] for m in result["matches"]]
        self.assertIn("block_name", types)
        self.assertEqual(result["counts"]["blocks"], 1)

    def test_block_content_snippet(self):
        result = search_preset(_preset(), "banter")
        content_hits = [m for m in result["matches"] if m["type"] == "block_content"]
        self.assertEqual(len(content_hits), 1)
        self.assertIn("banter", content_hits[0]["snippet"])

    def test_prompt_variable_name(self):
        result = search_preset(_preset(), "snark")
        hits = [m for m in result["matches"] if m["type"] == "prompt_variable"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["block"], "Dialogue")
        self.assertIn("name", hits[0]["field"])

    def test_prompt_variable_description(self):
        result = search_preset(_preset(), "who tells the story")
        hits = [m for m in result["matches"] if m["type"] == "prompt_variable"]
        self.assertEqual(len(hits), 1)
        self.assertIn("description", hits[0]["field"])

    def test_prompt_variable_options(self):
        result = search_preset(_preset(), "Third Person")
        hits = [m for m in result["matches"] if m["type"] == "prompt_variable"]
        self.assertEqual(len(hits), 1)
        self.assertIn("options", hits[0]["field"])

    def test_category_name(self):
        result = search_preset(_preset(), "story arc")
        hits = [m for m in result["matches"] if m["type"] == "category"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["block"], "Story Arc")

    def test_category_block_name_not_duplicated(self):
        result = search_preset(_preset(), "voice shaping")
        types = [m["type"] for m in result["matches"]]
        self.assertIn("category", types)
        self.assertNotIn("block_name", types)

    def test_category_filter(self):
        result = search_preset(_preset(), "narration", category="Voice Shaping")
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["block"], "Pacing")

    def test_category_filter_unknown_raises(self):
        with self.assertRaises(ValueError):
            search_preset(_preset(), "x", category="Nope")

    def test_enabled_only_skips_disabled(self):
        result = search_preset(_preset(), "narration", enabled_only=True)
        self.assertEqual(len(result["matches"]), 0)
        result = search_preset(_preset(), "narration", enabled_only=False)
        self.assertEqual(len(result["matches"]), 1)

    def test_case_sensitive(self):
        result = search_preset(_preset(), "PACING")
        self.assertEqual(len(result["matches"]), 1)
        result = search_preset(_preset(), "PACING", case_sensitive=True)
        self.assertEqual(len(result["matches"]), 0)

    def test_regex(self):
        result = search_preset(_preset(), r"^Pac", regex=True)
        types = [m["type"] for m in result["matches"]]
        self.assertIn("block_name", types)

    def test_surfaces_filter(self):
        result = search_preset(_preset(), "sharp", surfaces=["variables"])
        self.assertEqual(result["counts"], {"blocks": 0, "variables": 0, "categories": 0})

    def test_unknown_surface_raises(self):
        with self.assertRaises(ValueError):
            search_preset(_preset(), "x", surfaces=["bogus"])

    def test_empty_query_raises(self):
        with self.assertRaises(ValueError):
            search_preset(_preset(), "")

    def test_limit(self):
        result = search_preset(_preset(), "e", limit=1)
        self.assertLessEqual(len(result["matches"]), 1)


if __name__ == "__main__":
    unittest.main()

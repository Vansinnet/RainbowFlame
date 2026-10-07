"""Focused checks for offline Zealot flamer impact preset authoring."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_flamer_impact_presets as author


class FlamerImpactPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts, cls.report = author.run(check_only=True)

    def test_exact_paths_colors_and_hashes(self):
        self.assertEqual(tuple(author.PRESETS),
                         ("red", "orange", "yellow", "green", "cyan", "blue", "violet", "pink"))
        self.assertEqual(self.report["particle_identities"],
                         [author.EFFECT_PREFIX + preset for preset in author.PRESETS])
        self.assertEqual(len({value for row in author.HASHES.values() for value in row}), 56)

    def test_exact_graph_and_program_ranges(self):
        self.assertEqual(author.COLOR_PROGRAMS_1CC, tuple(range(1, 32, 4)))
        self.assertEqual(author.COLOR_PROGRAMS_BE93, tuple(range(1, 48, 4)))
        for preset in author.PRESETS:
            row = self.report["presets"][preset]
            self.assertEqual(row["parent_be93"]["targets"], list(author.COLOR_PROGRAMS_BE93))
            self.assertEqual(row["parent_be93"]["unchanged_programs"], 36)
            self.assertTrue(row["parent_be93"]["byte_exact_parent_reverse"])
            self.assertTrue(row["parent_1cc"]["byte_exact_parent_reverse"])
            self.assertEqual([child["stock_child"] for child in row["children"]],
                             [f"{child[0]:016x}" for child in author.CHILDREN])

    def test_counts_manifest_and_deterministic_rebuild(self):
        self.assertEqual((self.report["stock_records"], self.report["added_records"],
                          self.report["candidate_records"]), (43, 56, 99))
        manifest = json.loads(self.artifacts["manifest.json"])
        self.assertEqual((manifest["record_count"], manifest["stream_count"], manifest["preset_count"]),
                         (99, 48, 8))
        self.assertEqual(set(manifest["artifacts"]), set(self.artifacts) - {"manifest.json"})
        self.assertTrue(all(self.report["checks"].values()))


if __name__ == "__main__":
    unittest.main()

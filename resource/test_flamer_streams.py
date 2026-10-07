"""Focused invariants for the retained flamer stream cloud builder."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
RESOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(RESOURCE))
import build_flamer_streams as builder


class FlamerStreamBuilderTests(unittest.TestCase):
    def test_exact_requested_record_and_name_plan(self):
        self.assertEqual(
            [(spec["kind"], spec["records"], builder.names_for(spec)) for spec in builder.SPECS],
            [
                ("continuous", (2, 3, 5, 6), tuple(
                    f"RainbowFlame_flamer_continuous_{letter}" for letter in "abcd")),
                ("burst", (1, 2, 3, 5, 6), tuple(
                    f"RainbowFlame_flamer_burst_{letter}" for letter in "abcde")),
                ("3p", (0, 1, 3), tuple(
                    f"RainbowFlame_flamer_3p_{letter}" for letter in "abc")),
            ],
        )

    def test_authored_outputs_rebuild_exactly(self):
        artifacts, manifest = builder.build(check_only=True)
        self.assertEqual(len(manifest["global_unique_cloud_names"]), 12)
        self.assertEqual(len(set(manifest["global_unique_cloud_ids32"])), 12)
        for spec in builder.SPECS:
            report = json.loads(artifacts[f"RainbowFlame_flamer_{spec['kind']}.json"])
            self.assertEqual([row["record"] for row in report["clouds"]], list(spec["records"]))
            self.assertTrue(report["exact_logical_reverse"])
            self.assertTrue(report["whole_cloud_profile_verified"])


if __name__ == "__main__":
    unittest.main()

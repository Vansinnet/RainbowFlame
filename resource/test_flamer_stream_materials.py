"""Focused deterministic checks for authored Zealot flamer live-control materials."""
import colorsys
import copy
import json
import math
from pathlib import Path
import re
import struct
import sys
import unittest

sys.dont_write_bytecode = True
RESOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(RESOURCE))
import build
import export_resources as exports
import flamer_stream_materials as author
import surface_tables
from test_live import execute


class FlamerStreamMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old, cls.shaders, cls.repack, _, cls.checks = build.dependencies()
        cls.manifest = json.loads((author.REFLECTION / "manifest.json").read_text())
        cls.rows = {row["material"]: row for row in cls.manifest}
        cls.report = json.loads((author.OUTPUT / "report.json").read_text())

    def hash32(self, name):
        return self.old.murmur64(name.encode()) >> 32

    def model(self, data):
        _, offset, size, *_ = struct.unpack_from("<7I", data)
        return exports.material_template(data[offset:offset + size])

    def test_sealed_artifacts_and_source_syntax(self):
        sums = json.loads((author.OUTPUT / "SHA256SUMS.json").read_text())
        for name, expected in sums.items():
            self.assertEqual(Path(name).name, name)
            self.assertEqual(author.identity((author.OUTPUT / name).read_bytes()), expected, name)
        for name in ("flamer_stream_materials.py", "test_flamer_stream_materials.py"):
            path = Path(__file__).with_name(name)
            compile(path.read_bytes(), str(path), "exec")

    def test_exact_target_plan_and_report(self):
        self.assertEqual(author.SPECS["da27aa083a052838"]["targets"], (1, 5, 9, 13))
        self.assertEqual(author.SPECS["be9333164c3ddf4a"]["targets"], tuple(range(1, 48, 4)))
        self.assertTrue(self.report["preservation"]["da27_compute_programs_16_18"])
        self.assertTrue(self.report["preservation"]["exact_parent_and_child_reverse"])

    def test_deterministic_parent_rebuild_and_reverse(self):
        for name, spec in author.SPECS.items():
            original = author.source(name)
            replacements = {index: (author.OUTPUT / f"{name}-program-{index:02d}.dxbc").read_bytes()
                            for index in spec["targets"]}
            material, shader, verification = author.material_for(
                name, original, self.rows[name]["programs"], replacements, self.old, self.repack)
            self.assertEqual(material, (author.OUTPUT / (name + ".material")).read_bytes())
            self.assertEqual(shader, (author.OUTPUT / (name + ".shader43")).read_bytes())
            self.assertTrue(verification["byte_exact_reverse"])

    def test_child_parent_descriptors_values_and_sentinels(self):
        original = (author.STOCK / author.CHILD_STREAM).read_bytes()
        child = (author.OUTPUT / (author.CHILD + ".material")).read_bytes()
        self.assertEqual(child, author.child_for(original, self.hash32))
        header = struct.unpack_from("<7I", child)
        self.assertEqual(header[3:], (0xffffffff, 0, 0xffffffff, 0))
        before, after = self.model(original), self.model(child)
        for key in before:
            if key not in ("descriptors", "values"):
                self.assertEqual(before[key], after[key], key)
        self.assertEqual(after["descriptors"][:-2], before["descriptors"])
        self.assertEqual(after["values"][:-24], before["values"])
        self.assertEqual(after["values"][-24:], bytes(24))
        self.assertEqual(struct.unpack_from("<Q", after["head"], 4)[0], int("da27aa083a052838", 16))

    def test_registration_defaults_and_non_targets(self):
        for name, spec in author.SPECS.items():
            original = author.source(name)
            _, _, _, so, ss, _, _ = struct.unpack_from("<7I", original)
            old_shader = original[so:so + ss]
            new_shader = (author.OUTPUT / (name + ".shader43")).read_bytes()
            old_start, old_length = struct.unpack_from("<2I", old_shader, 32)
            new_start, new_length = struct.unpack_from("<2I", new_shader, 32)
            old_groups = author.parse_groups(old_shader[old_start:old_start + old_length], spec)
            new_groups = author.parse_groups(new_shader[new_start:new_start + new_length], spec, True)
            graphics = spec["graphics"] // 4
            self.assertEqual(new_groups[graphics:], old_groups[graphics:])
            for before, after in zip(old_groups[:graphics], new_groups[:graphics], strict=True):
                self.assertEqual(after["buffers"][3]["descriptors"][:-2], before["buffers"][3]["descriptors"])
                self.assertEqual([row[3:] for row in after["buffers"][3]["descriptors"][-2:]],
                                 [[spec["exports"][0][2], 16], [spec["exports"][1][2], 8]])
            old_default = struct.unpack_from("<I", old_shader, 20)[0]
            new_default = struct.unpack_from("<I", new_shader, 20)[0]
            old_defaults = exports.default_table(old_shader[old_default:])
            new_defaults = exports.default_table(new_shader[new_default:])
            self.assertEqual(new_defaults[:-2], old_defaults)
            self.assertEqual([value for _, value in new_defaults[-2:]], [bytes(16), bytes(8)])
            frames = self.report["parents"][name]["verification"]["frames"]
            for index, (stock, authored) in enumerate(zip(self.rows[name]["programs"], frames, strict=True)):
                old_begin, old_end = stock["frame"]
                new_begin, new_end = authored["frame"]
                if index not in spec["targets"]:
                    self.assertEqual(new_shader[new_begin:new_end], old_shader[old_begin:old_end], (name, index))
                before_meta = surface_tables.metadata(old_shader, old_end)
                after_meta = surface_tables.metadata(new_shader, new_end)
                for table_index, (before_table, after_table) in enumerate(zip(before_meta["tables"], after_meta["tables"], strict=True)):
                    expected = copy.deepcopy(before_table["rows"])
                    if table_index == 0:
                        for row in expected:
                            if row[0] == self.hash32("c_material_exports"):
                                row[2] = spec["new_size"]
                    self.assertEqual(after_table["rows"], expected, (name, index, table_index))

    def test_target_dxil_reflection_and_stat(self):
        for name, spec in author.SPECS.items():
            for index in spec["targets"]:
                stock = (author.REFLECTION / name / f"program-{index:02d}.ll.txt").read_text()
                reflected = (author.OUTPUT / f"{name}-program-{index:02d}.ll.txt").read_text()
                module = (author.OUTPUT / f"{name}-program-{index:02d}.input.ll").read_text()
                stat = (author.OUTPUT / f"{name}-program-{index:02d}-STAT.ll.txt").read_text()
                author.verify_buffer_definitions(stock, reflected, spec)
                self.assertEqual(build.canonical(module, self.shaders), build.canonical(reflected, self.shaders))
                self.assertEqual(self.checks.count_instructions(reflected), self.checks.counters(stat))

    def test_only_control_fragment_and_three_operands_change(self):
        for name, spec in author.SPECS.items():
            index = spec["targets"][0]
            stock = (author.REFLECTION / name / f"program-{index:02d}.ll.txt").read_text()
            module = (author.OUTPUT / f"{name}-program-{index:02d}.input.ll").read_text()
            body = self.shaders.body(module)
            body = "\n".join(line for line in body.splitlines() if not line.startswith(("  %rf.", "  %hc.")))
            for channel, source, consumer in zip("rgb", spec["rgb"], spec["consumers"]):
                body = body.replace(consumer.replace(source, "%rf." + channel), consumer)
            self.assertEqual(body, self.shaders.body(stock))

    def fragment(self, name):
        spec = author.SPECS[name]
        index = spec["targets"][0]
        module = (author.OUTPUT / f"{name}-program-{index:02d}.input.ll").read_text()
        fragment = "\n".join(line for line in module.splitlines() if line.startswith(("  %rf.", "  %hc."))) + "\n"
        for source, replacement in zip((*spec["rgb"], spec["time"]), ("%r", "%g", "%b", "%time")):
            fragment = re.sub(re.escape(source) + r"(?!\d)", replacement, fragment)
        hsv_register = spec["exports"][0][2] // 16
        cycle_register = spec["exports"][1][2] // 16
        fragment = fragment.replace(f"i32 {hsv_register})", "i32 5)").replace(f"i32 {cycle_register})", "i32 6)")
        return fragment

    def test_control_behavior_oracles(self):
        for name in author.SPECS:
            fragment = self.fragment(name)
            rgb = (.125, .5, 1)
            self.assertEqual(execute(fragment, rgb, 5, (.7, .2, 2, 0), (1, .125)), rgb)
            for opacity in (0, .25, 1):
                self.assertEqual(execute(fragment, rgb, 5, (.3, opacity, 2, -1), (1, .125)),
                                 tuple(value * opacity for value in rgb))
            for degree in range(0, 361, 15):
                expected = colorsys.hsv_to_rgb(degree / 360, 1, max(rgb) * .75)
                actual = execute(fragment, rgb, 5, (degree / 360, .5, 1.5, 1), (0, .125))
                for left, right in zip(actual, expected):
                    self.assertAlmostEqual(left, right, delta=8e-6)
            for step in range(1001):
                phase = step / 1000
                p = phase - math.floor(phase)
                if p < .5:
                    hue, weight = p / .75, 0
                elif p <= .75:
                    hue = 2 / 3
                    triangle = 1 - abs(p - .625) * 8
                    weight = triangle * triangle * (3 - 2 * triangle)
                else:
                    hue, weight = (p - .25) / .75, 0
                wheel = colorsys.hsv_to_rgb(hue, 1, 1)
                expected = tuple(.75 * (a * (1 - weight) + b * weight) for a, b in zip(wheel, rgb))
                actual = execute(fragment, rgb, phase / .125, (.2, .5, 1.5, 1), (1, .125))
                for left, right in zip(actual, expected):
                    self.assertAlmostEqual(left, right, delta=4e-6)

    def test_corrupt_sources_and_registration_rejected(self):
        for name, spec in author.SPECS.items():
            original = author.source(name)
            with self.assertRaisesRegex(ValueError, "Parent identity"):
                author.inspect_parent(name, original[:-1] + bytes([original[-1] ^ 1]))
            _, _, _, offset, size, _, _ = struct.unpack_from("<7I", original)
            shader = original[offset:offset + size]
            start, length = struct.unpack_from("<2I", shader, 32)
            raw = shader[start:start + length]
            with self.assertRaises(ValueError):
                author.parse_groups(raw[:-1], spec)
        child = (author.STOCK / author.CHILD_STREAM).read_bytes()
        with self.assertRaisesRegex(ValueError, "Child identity"):
            author.child_for(child[:-1] + bytes([child[-1] ^ 1]), self.hash32)


if __name__ == "__main__":
    unittest.main()

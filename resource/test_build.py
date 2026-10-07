"""Independent HSV oracle and executable insertion checks; no game code execution."""
import colorsys
import hashlib
import json
import math
import random
import re
import struct
import unittest

import build


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def execute(text, rgb, time):
    values: dict[str, float] = dict(zip(('%r', '%g', '%b', '%time'), map(f32, (*rgb, time))))

    def value(token):
        if token.startswith('%'):
            return values[token]
        if token.startswith('0x'):
            return struct.unpack('>d', bytes.fromhex(token[2:]))[0]
        return float(token)

    for line in text.splitlines():
        name, operation = line.strip().split(' = ')
        if operation.startswith('call'):
            operands = re.findall(r', float ([^,) ]+)', operation)
            args = [value(token) for token in operands]
            match = re.search(r'i32 (\d+)', operation)
            assert match is not None
            opcode = int(match[1])
            if opcode == 35:
                result = max(args)
            elif opcode == 22:
                result = args[0] - math.floor(args[0])
            elif opcode == 6:
                result = abs(args[0])
            elif opcode == 7:
                result = min(1, max(0, args[0]))
            else:
                raise AssertionError(operation)
        else:
            opcode, operands_text = operation.split(' float ')
            a, b = map(value, operands_text.split(', '))
            if opcode == 'fmul':
                result = a * b
            elif opcode == 'fadd':
                result = a + b
            elif opcode == 'fsub':
                result = a - b
            else:
                raise AssertionError(operation)
        values[name] = f32(result)
    return tuple(values['%hc.' + channel] for channel in 'rgb')


class ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old, cls.shaders, cls.repack, _, _ = build.dependencies()

    def test_invalid_settings(self):
        for key, invalids in {
            'hue': [-1, 361, float('nan'), float('inf'), True, '120'],
            'saturation': [-0.01, 1.01], 'brightness': [-0.01, 2.01],
            'speed': [0, -1, 4.01, float('-inf')],
            'rainbow': [0, 1, None], 'enabled': [0, 1, None],
        }.items():
            for invalid in invalids:
                with self.subTest(key=key, value=invalid), self.assertRaises(ValueError):
                    build.settings(**{key: invalid})

    def test_emitted_ir_against_colorsys(self):
        randomizer = random.Random(20260918)
        cases = [(h, s, v, rainbow, time) for h in (0, 60, 120, 180, 240, 300, 360)
                 for s in (0, 0.5, 1) for v in (0, 1, 2) for rainbow in (False, True)
                 for time in (0, 0.25, 4, 8, -1)]
        cases += [(randomizer.uniform(0, 360), randomizer.random(), randomizer.uniform(0, 2),
                   True, randomizer.uniform(-10, 10)) for _ in range(300)]
        for h, s, v, rainbow, time in cases:
            rgb = tuple(randomizer.random() for _ in range(3))
            config = build.settings(h, s, v, rainbow)
            ir = build.instructions(('%r', '%g', '%b'), '%time', config, self.shaders.float_ir)
            actual = execute(ir, rgb, time)
            expected = colorsys.hsv_to_rgb((h/360 + (time*0.125 if rainbow else 0)) % 1, s, v*max(rgb))
            for a, b in zip(actual, expected):
                self.assertAlmostEqual(a, b, delta=0.000006)

    def test_fixed_is_time_independent_and_cycle_period(self):
        for rainbow in (False, True):
            config = build.settings(hue=273, saturation=0.37, brightness=1.8, rainbow=rainbow, speed=0.25)
            ir = build.instructions(('%r', '%g', '%b'), '%time', config, self.shaders.float_ir)
            for t in (0, 0.5, 1, 2):
                a = execute(ir, (0.2, 0.7, 0.4), t)
                b = execute(ir, (0.2, 0.7, 0.4), t + (4 if rainbow else 123))
                for x, y in zip(a, b):
                    self.assertAlmostEqual(x, y, delta=0.000003)

    def test_stock_module_and_only_color_consumers(self):
        for name in ('a8dc696a363ec3d3', '49697971309d8a04'):
            stem = name + '-second'
            text = self.old.sealed(self.old.J1 / (stem + '.ll.txt'), self.old.J1).decode()
            stock = build.module_for(stem, text, build.settings(enabled=False), self.shaders)
            self.assertEqual(self.shaders.body(stock), self.shaders.body(text))
            custom = build.module_for(stem, text, build.settings(), self.shaders)
            rgb, time, outputs = (('%152', '%153', '%154'), '%156', (190, 191, 192)) if name.startswith('a8') else (('%146', '%147', '%148'), '%150', (184, 185, 186))
            recovered = self.shaders.body(custom).replace(build.instructions(rgb, time, build.settings(), self.shaders.float_ir), '')
            for channel, source, target, gain in zip('rgb', rgb, outputs, (7, 8, 9)):
                recovered = recovered.replace(f'%{target} = fmul fast float %hc.{channel}, %{gain}',
                                              f'%{target} = fmul fast float {source}, %{gain}')
            self.assertEqual(recovered, self.shaders.body(text))

    def test_output_boundary_before_native_tools(self):
        for path in ('mods/active/RainbowFlame', 'docs/analysis-flame-huecycle-build-20260918-o1',
                     'docs/analysis-rainbow-flame-escape/child'):
            with self.assertRaises(ValueError):
                build.build(path, build.settings())

    def test_malformed_material_and_frame_bounds(self):
        for payload in (b'', bytes(31), bytes(262144)):
            with self.assertRaises(ValueError):
                self.repack.stored_frame(payload)
        for info in self.repack.material_info():
            source = self.repack.material_original(info)
            for broken in (source[:-1], source + b'\0', b'\0\0\0\0' + source[4:]):
                with self.assertRaises(ValueError):
                    self.repack.material_sections(broken)

    def test_built_artifacts(self):
        known = self.repack.known_frames()
        for folder in ('analysis-rainbow-flame-hsv-20260918-s2',
                       'analysis-rainbow-flame-fixed-20260918-s3',
                       'analysis-rainbow-flame-stock-20260918-s4'):
            root = build.WORKSPACE / 'docs' / folder
            manifest = json.loads((root / 'manifest.json').read_text())
            seal = json.loads((root / 'SHA256SUMS.json').read_text())
            for name, record in seal.items():
                data = (root / name).read_bytes()
                self.assertEqual(len(data), record['size'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), record['sha256'])
            for target, info in zip(manifest['targets'], self.repack.material_info()):
                source = self.repack.material_original(info)
                data = (root / target['file']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), target['sha256'])
                _, _, off, size = self.repack.material_sections(source)
                before_shader = source[off:off+size]
                before = self.repack.parse_shader(before_shader, known)
                _, _, off, size = self.repack.material_sections(data)
                after_shader = data[off:off+size]
                after = self.repack.parse_shader(after_shader, known)
                self.assertEqual(before['default_size'], after['default_size'])
                self.assertEqual(before_shader[before['default']:before['default']+before['default_size']],
                                 after_shader[after['default']:after['default']+after['default_size']])
                self.assertFalse(any(after_shader[after['default']+after['default_size']:]))
                for index in range(4):
                    a, b = before['programs'][index], after['programs'][index]
                    begin_a, end_a = a['metadata']['span']
                    begin_b, end_b = b['metadata']['span']
                    self.assertEqual(before_shader[begin_a+16:end_a], after_shader[begin_b+16:end_b])
                    if index != 1:
                        self.assertEqual(a['data'], b['data'])
                stem = target['material'] + '-second'
                original = self.old.sealed(self.old.J1 / (stem + '.ll.txt'), self.old.J1).decode()
                expected = build.module_for(stem, original, manifest['settings'], self.shaders)
                actual = (root / (stem + '.ll.txt')).read_text()
                self.assertEqual(build.canonical(expected, self.shaders), build.canonical(actual, self.shaders))


if __name__ == '__main__':
    unittest.main(verbosity=2)

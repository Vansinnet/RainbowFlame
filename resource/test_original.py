"""Independent float32 checks for the original-ramp rainbow candidate."""
import colorsys
import unittest

import build
import live_shader
from test_live import execute


class OriginalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, shaders, *_ = build.dependencies()
        cls.fragment = live_shader.instructions(('%r', '%g', '%b'), '%time', shaders, True)

    def sample(self, phase, rgb=(0.125, 0.5, 1), hue=0.37, opacity=1.0, brightness=1.0, enabled=1, cycle=1):
        return execute(self.fragment, rgb, phase * 8, (hue, opacity, brightness, enabled), (cycle, .125))

    def test_original_anchor_and_disabled(self):
        for rgb in ((.125, .5, 1), (1, .25, .5), (0, 0, 0), (2, .125, .75)):
            self.assertEqual(self.sample(.625, rgb), rgb)
            self.assertEqual(self.sample(.625, rgb, brightness=2), tuple(2*x for x in rgb))
            self.assertEqual(self.sample(.625, rgb, opacity=.25), tuple(.25*x for x in rgb))
            for phase in (0, .5, .625, .75, .99):
                self.assertEqual(self.sample(phase, rgb, opacity=0, brightness=0, enabled=0), rgb)

    def test_original_mode_opacity_and_brightness_independence(self):
        rgb = (.125, .5, 1)
        for opacity in (0, .25, 1):
            expected = tuple(opacity*x for x in rgb)
            self.assertEqual(self.sample(.2, rgb, opacity=opacity, brightness=0, enabled=-1, cycle=0), expected)
            self.assertEqual(self.sample(.8, rgb, opacity=opacity, brightness=2, enabled=-1, cycle=0), expected)

    def test_full_wheel_and_custom(self):
        for degree in range(361):
            hue = degree / 360
            phase = hue * .75 + (.25 if hue > 2/3 else 0)
            expected = colorsys.hsv_to_rgb(hue, 1, 1)
            for actual in (self.sample(phase), self.sample(.625, hue=hue, cycle=0)):
                for a, b in zip(actual, expected):
                    self.assertAlmostEqual(a, b, delta=2e-6)

    def test_independent_smooth_blend_oracle_and_continuity(self):
        previous = None
        bound = 0
        for i in range(12001):
            phase = i / 12000
            p = phase % 1
            if p < .5:
                hue, weight = p / .75, 0
            elif p <= .75:
                hue = 2/3
                t = 1 - abs(p - .625) * 8
                weight = t*t*(3-2*t)
            else:
                hue, weight = (p-.25) / .75, 0
            wheel = colorsys.hsv_to_rgb(hue, 1, 1)
            expected = tuple(a*(1-weight)+b*weight for a, b in zip(wheel, (.125, .5, 1)))
            actual = self.sample(phase)
            for a, b in zip(actual, expected):
                self.assertAlmostEqual(a, b, delta=2e-6)
            if previous:
                bound = max(bound, *(abs(a-b) for a, b in zip(actual, previous)))
            previous = actual
        self.assertEqual(self.sample(0), self.sample(1))
        self.assertLess(bound, .0011)
        print('Original-cycle max adjacent channel step:', bound)


if __name__ == '__main__':
    unittest.main(verbosity=2)

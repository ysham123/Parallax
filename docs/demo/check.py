"""Run explicit acceptance checks without third-party dependencies."""
import unittest
from maths import clamp, safe_divide
from stats import mean, median


class Acceptance(unittest.TestCase):
    def test_clamp_inside_and_both_boundaries(self):
        self.assertEqual(clamp(4, 0, 10), 4)
        self.assertEqual(clamp(-3, 0, 10), 0)
        self.assertEqual(clamp(13, 0, 10), 10)
        self.assertEqual(clamp(4, 2, 2), 2)

    def test_clamp_reversed_bounds_rejected(self):
        with self.assertRaises(ValueError):
            clamp(4, 10, 0)

    def test_division(self):
        self.assertEqual(safe_divide(6, 3), 2)
        self.assertEqual(safe_divide(-7, 2), -3.5)
        self.assertEqual(safe_divide(0, 2), 0)

    def test_division_zero_rejected(self):
        for denominator in (0, -0.0):
            with self.assertRaises(ValueError):
                safe_divide(5, denominator)

    def test_mean_lists_and_generators(self):
        self.assertEqual(mean([2, 4, 6]), 4)
        self.assertEqual(mean(iter([-2, 2])), 0)
        self.assertEqual(mean((x for x in [1, 2])), 1.5)
        self.assertEqual(mean([8]), 8)

    def test_mean_empty_rejected(self):
        for values in ([], iter([])):
            with self.assertRaises(ValueError):
                mean(values)

    def test_median_odd_even_and_input_preserved(self):
        data = [4, 1, 3, 2]
        self.assertEqual(median(data), 2.5)
        self.assertEqual(data, [4, 1, 3, 2])
        self.assertEqual(median(iter([4, 1, 3])), 3)
        self.assertEqual(median([-3, -1]), -2)
        self.assertEqual(median([8]), 8)

    def test_median_empty_rejected(self):
        for values in ([], iter([])):
            with self.assertRaises(ValueError):
                median(values)


if __name__ == '__main__':
    unittest.main(verbosity=2)

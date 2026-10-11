import unittest

from average import average


class AverageTests(unittest.TestCase):
    def test_empty_input_has_an_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "^empty input$"):
            average([])

    def test_existing_numeric_behavior(self):
        self.assertEqual(average([2, 4, 6]), 4)
        self.assertEqual(average([-4, 4]), 0)
        self.assertEqual(average([1.5, 2.5]), 2)
        self.assertEqual(average([7]), 7)


if __name__ == "__main__":
    unittest.main()

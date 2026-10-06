import unittest
from service import total
class InvoiceTests(unittest.TestCase):
    def test_empty(self): self.assertEqual(total([]), 0)
    def test_total(self): self.assertEqual(total([2, 3]), 5)
    def test_negative_adjustment(self): self.assertEqual(total([10, -3]), 7)

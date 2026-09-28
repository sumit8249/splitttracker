"""Unit tests for receipt parsing and cost allocation."""

import unittest
from decimal import Decimal

from bill_split import (
    calculate_itemized_split,
    normalize_receipt,
    parse_assistant_response,
    split_equally,
)


class ReceiptParsingTests(unittest.TestCase):
    def test_normalize_receipt_ignores_unreadable_values(self) -> None:
        receipt = normalize_receipt(
            {
                "currency": "usd",
                "items": [
                    {"name": "Soup", "amount": "12.50"},
                    {"name": "Unknown", "amount": None},
                ],
                "total": "15.00",
            }
        )
        self.assertEqual(receipt["currency"], "USD")
        self.assertEqual(receipt["items"], [{"name": "Soup", "amount": Decimal("12.50")}])
        self.assertEqual(receipt["total"], Decimal("15.00"))

    def test_parse_response_falls_back_to_plain_text(self) -> None:
        message, receipt = parse_assistant_response("Please upload a clearer photo.")
        self.assertEqual(message, "Please upload a clearer photo.")
        self.assertIsNone(receipt)


class CostAllocationTests(unittest.TestCase):
    def test_equal_split_distributes_remaining_cent(self) -> None:
        shares = split_equally("10.00", ["Alex", "Sam", "Priya"])
        self.assertEqual(
            shares,
            {
                "Alex": Decimal("3.34"),
                "Sam": Decimal("3.33"),
                "Priya": Decimal("3.33"),
            },
        )
        self.assertEqual(sum(shares.values()), Decimal("10.00"))

    def test_item_split_respects_participants_and_shares_unassigned(self) -> None:
        shares = calculate_itemized_split(
            [
                {"amount": "12.00", "participants": "Alex"},
                {"amount": "9.00", "participants": "Alex, Sam"},
                {"amount": "3.00", "participants": ""},
            ],
            ["Alex", "Sam", "Priya"],
        )
        self.assertEqual(shares["Alex"], Decimal("17.50"))
        self.assertEqual(shares["Sam"], Decimal("5.50"))
        self.assertEqual(shares["Priya"], Decimal("1.00"))
        self.assertEqual(sum(shares.values()), Decimal("24.00"))


if __name__ == "__main__":
    unittest.main()
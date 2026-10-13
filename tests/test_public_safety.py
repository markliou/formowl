from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import ContractValidationError, assert_no_public_raw_references


class PublicSafetyTests(unittest.TestCase):
    def test_business_prose_is_not_misclassified_as_sql(self) -> None:
        for text in (
            (
                "Keep a copy and notify the sender immediately. "
                "Information that does not relate to this request should be ignored."
            ),
            "Please call Converge (the supplier) before confirming the order.",
        ):
            with self.subTest(text=text):
                assert_no_public_raw_references(text, "business_prose")

    def test_sql_copy_and_call_statements_remain_rejected(self) -> None:
        for text in (
            "COPY candidate_assertions TO STDOUT",
            "COPY candidate_assertions FROM STDIN",
            "COPY candidate_assertions FROM '/tmp/private.csv'",
            "CALL refresh_candidate_assertions()",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ContractValidationError):
                    assert_no_public_raw_references(text, "public_payload")


if __name__ == "__main__":
    unittest.main()

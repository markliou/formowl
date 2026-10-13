from __future__ import annotations

import unittest

import _paths  # noqa: F401
from formowl_contract import (
    ContractValidationError,
    semantic_request_json_schema,
    validate_semantic_request,
)


def _request() -> dict[str, object]:
    return {
        "query_class": "attribute_filter",
        "object_type_mention": "sample record",
        "predicate_mention": "signal class",
        "operator": "equals",
        "value_mention": "phase β",
        "projection_mention": "sample record",
        "cardinality": "all_matching",
        "page_size": 25,
        "page_number": 1,
    }


class SemanticRequestContractTests(unittest.TestCase):
    def test_shared_schema_is_closed_and_matches_the_validator(self) -> None:
        request = _request()

        schema = semantic_request_json_schema()

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(request))
        self.assertEqual(set(schema["properties"]), set(request))
        self.assertEqual(validate_semantic_request(request), request)

    def test_validator_rejects_extra_fields_and_unsupported_operators(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_semantic_request({**_request(), "unexpected": "value"})
        with self.assertRaises(ContractValidationError):
            validate_semantic_request({**_request(), "operator": "contains"})


if __name__ == "__main__":
    unittest.main()

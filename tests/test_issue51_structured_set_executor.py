from __future__ import annotations

from dataclasses import replace
import importlib
from typing import Any, Mapping, Sequence
import unittest

import _paths  # noqa: F401

from formowl_contract import (
    ContractValidationError,
    CoverageLedger,
    DisplayPagination,
    ExecutableSemanticPlan,
    StructuralCell,
    StructuralColumn,
    StructuralObservation,
    StructuralRow,
)


_SOURCE_FINGERPRINT = "sha256:" + ("1" * 64)
_PARSER_FINGERPRINT = "sha256:" + ("2" * 64)


def _executor():
    """Resolve the narrow public executor only when a test executes.

    This keeps the module collectible on the pre-implementation base while
    making the expected public API explicit for the implementation branch.
    """

    module = importlib.import_module("formowl_mail.query")
    executor = getattr(module, "execute_authorized_structured_set", None)
    if not callable(executor):
        raise AssertionError(
            "missing public API "
            "formowl_mail.query.execute_authorized_structured_set"
        )
    return executor


def _plan(
    *,
    object_type: str = "record",
    predicate: str = "state",
    value: str = "active",
    projection: str = "label",
    page_size: int = 10,
    page_number: int = 1,
) -> ExecutableSemanticPlan:
    return ExecutableSemanticPlan(
        query_class="attribute_filter",
        object_type=object_type,
        predicate=predicate,
        operator="equals",
        value=value,
        cardinality="all_matching",
        projection=projection,
        order_by="projection",
        order_direction="ascending",
        page_size=page_size,
        page_number=page_number,
        object_type_match_forms=(object_type,),
        predicate_match_forms=(predicate,),
        value_match_forms=(value,),
        projection_match_forms=(projection,),
    )


def _observation(
    *,
    observation_id: str,
    inventory_item_id: str,
    headers: tuple[str, str, str] = ("record", "state", "label"),
    rows: Sequence[tuple[str, ...]],
) -> StructuralObservation:
    structural_rows = tuple(
        StructuralRow(
            row_ordinal=row_ordinal,
            cells=tuple(
                StructuralCell(
                    cell_state="populated",
                    row_ordinal=row_ordinal,
                    column_ordinal=column_ordinal,
                    value=value,
                    normalized_value=value,
                )
                for column_ordinal, value in enumerate(row)
            ),
        )
        for row_ordinal, row in enumerate(rows)
    )
    return StructuralObservation(
        structural_observation_id=observation_id,
        source_inventory_item_id=inventory_item_id,
        source_asset_id="synthetic_asset",
        source_observation_id=f"source_{observation_id}",
        structure_kind="table",
        columns=tuple(
            StructuralColumn(
                column_ordinal=ordinal,
                original_header=header,
                normalized_header=header,
            )
            for ordinal, header in enumerate(headers)
        ),
        rows=structural_rows,
        header_relationships=(),
        source_fingerprint=_SOURCE_FINGERPRINT,
        parser_fingerprint=_PARSER_FINGERPRINT,
    )


def _ledger(*, inventory_item_ids: Sequence[str], observations: Sequence[StructuralObservation]) -> CoverageLedger:
    return CoverageLedger.create(
        query_id="query_structured_set",
        claim_requirement_id="claim_structured_set",
        source_inventory_id="inventory_structured_set",
        relevant_inventory_item_ids=tuple(inventory_item_ids),
        searched_structural_observation_ids=tuple(
            observation.structural_observation_id for observation in observations
        ),
        display_pagination=DisplayPagination(page_size=10),
    )


def _execute(
    *,
    plan: Any,
    observations: Sequence[StructuralObservation],
    authorized_inventory_item_ids: Sequence[str],
    ledger: CoverageLedger,
) -> Any:
    return _executor()(
        plan=plan,
        structural_observations=tuple(observations),
        authorized_inventory_item_ids=frozenset(authorized_inventory_item_ids),
        coverage_ledger=ledger,
    )


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _projection_values(execution: Any) -> tuple[str, ...]:
    values = []
    for match in execution.matches:
        projection_value = next(
            (
                _field(match, field_name)
                for field_name in ("projection_value", "display_value", "value")
                if _field(match, field_name) is not None
            ),
            None,
        )
        if not isinstance(projection_value, str):
            raise AssertionError("structured-set match omits a public projection value")
        values.append(projection_value)
    return tuple(values)


class StructuredSetExecutorContractTests(unittest.TestCase):
    """Synthetic contract for the public authorized structural-set executor."""

    def test_authorized_rows_match_in_deterministic_projection_order_with_pagination(self) -> None:
        observation = _observation(
            observation_id="observation_authorized",
            inventory_item_id="inventory_authorized",
            rows=(
                ("record", "active", "bravo"),
                ("record", "active", "alpha"),
                ("record", "inactive", "ignored"),
            ),
        )
        ledger = _ledger(inventory_item_ids=("inventory_authorized",), observations=(observation,))

        first_page = _execute(
            plan=_plan(page_size=1, page_number=1),
            observations=(observation,),
            authorized_inventory_item_ids=("inventory_authorized",),
            ledger=ledger,
        )
        second_page = _execute(
            plan=_plan(page_size=1, page_number=2),
            observations=(observation,),
            authorized_inventory_item_ids=("inventory_authorized",),
            ledger=ledger,
        )

        self.assertEqual(_projection_values(first_page), ("alpha",))
        self.assertEqual(_projection_values(second_page), ("bravo",))
        self.assertEqual(len(first_page.matched_structural_facts), 1)
        self.assertEqual(first_page.display_pagination.page_size, 1)
        self.assertEqual(first_page.display_pagination.page_number, 1)
        self.assertTrue(first_page.display_pagination.has_more)
        self.assertFalse(second_page.display_pagination.has_more)

    def test_unauthorized_inventory_item_is_excluded_from_matches(self) -> None:
        authorized = _observation(
            observation_id="observation_allowed",
            inventory_item_id="inventory_allowed",
            rows=(("record", "active", "alpha"),),
        )
        unauthorized = _observation(
            observation_id="observation_denied",
            inventory_item_id="inventory_denied",
            rows=(("record", "active", "shadow"),),
        )
        ledger = _ledger(
            inventory_item_ids=("inventory_allowed",),
            observations=(authorized,),
        )

        execution = _execute(
            plan=_plan(),
            observations=(authorized, unauthorized),
            authorized_inventory_item_ids=("inventory_allowed",),
            ledger=ledger,
        )

        self.assertEqual(_projection_values(execution), ("alpha",))
        self.assertNotIn("shadow", _projection_values(execution))
        self.assertTrue(
            all(
                _field(match, "source_inventory_item_id") != "inventory_denied"
                for match in execution.matches
            )
        )

    def test_invalid_plan_or_malformed_structural_row_is_rejected(self) -> None:
        valid = _observation(
            observation_id="observation_valid",
            inventory_item_id="inventory_valid",
            rows=(("record", "active", "alpha"),),
        )
        malformed = _observation(
            observation_id="observation_malformed",
            inventory_item_id="inventory_valid",
            rows=(("record", "active"),),
        )
        ledger = _ledger(inventory_item_ids=("inventory_valid",), observations=(valid,))

        with self.subTest("plan"):
            with self.assertRaises(ContractValidationError):
                _execute(
                    plan=object(),
                    observations=(valid,),
                    authorized_inventory_item_ids=("inventory_valid",),
                    ledger=ledger,
                )
        with self.subTest("row"):
            with self.assertRaises(ContractValidationError):
                _execute(
                    plan=_plan(),
                    observations=(malformed,),
                    authorized_inventory_item_ids=("inventory_valid",),
                    ledger=ledger,
                )

    def test_generic_structural_terms_execute_without_query_specific_terms(self) -> None:
        observation = _observation(
            observation_id="observation_generic",
            inventory_item_id="inventory_generic",
            headers=("entity", "phase", "title"),
            rows=(
                ("entity", "ready", "delta"),
                ("entity", "waiting", "echo"),
            ),
        )
        ledger = _ledger(inventory_item_ids=("inventory_generic",), observations=(observation,))

        execution = _execute(
            plan=_plan(
                object_type="entity",
                predicate="phase",
                value="ready",
                projection="title",
            ),
            observations=(observation,),
            authorized_inventory_item_ids=("inventory_generic",),
            ledger=ledger,
        )

        self.assertEqual(_projection_values(execution), ("delta",))
        self.assertEqual(len(execution.matched_structural_facts), 1)


if __name__ == "__main__":
    unittest.main()

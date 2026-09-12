"""Every concept in both goldens maps deterministically at EXACT or SYNONYM.
Spec Phase 4 gate. Values compared as Decimal at full internal precision."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from fincopilot.extract.locate import locate_statements
from fincopilot.extract.pdf import extract_pdf, validate_input
from fincopilot.extract.periods import detect_periods
from fincopilot.extract.units import normalize_document
from fincopilot.mapping.synonyms import map_rows
from fincopilot.mapping.validate import validate_mappings
from fincopilot.types import (
    CanonicalConcept,
    ExtractionConfidence,
    FinancialValue,
    Period,
    RowMapping,
    StatementKind,
    UnavailableReason,
    is_unavailable,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _report(name: str):
    data = (FIXTURES / name).read_bytes()
    doc = extract_pdf(data, validate_input(data))
    statements = locate_statements(doc)
    periods = detect_periods(statements)
    normalized = normalize_document(statements, periods, doc)
    return validate_mappings(map_rows(normalized), normalized, periods), normalized, periods


def _expected(name: str) -> dict:
    return json.loads((FIXTURES / "expected" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture", ["golden_indian", "golden_us"])
def test_every_expected_concept_maps_deterministically(fixture):
    report, _, _ = _report(f"{fixture}.pdf")
    expected = _expected(f"{fixture}.json")
    assert not report.conflicts
    for name, spec in expected["mapped"].items():
        concept = CanonicalConcept(name)
        for year_key, base_units in spec.items():
            if not year_key.isdigit():
                continue
            fv = report.get(concept, Period(int(year_key), year_key))
            assert isinstance(fv, FinancialValue), (name, year_key, fv)
            assert fv.value == Decimal(base_units), (name, year_key)
            assert fv.source_label == spec["source_label"]
            assert fv.source_page == spec["page"]
            assert fv.extraction_confidence in (
                ExtractionConfidence.EXACT_MATCH,
                ExtractionConfidence.SYNONYM_MATCH,
            )
            assert fv.currency == expected["currency"]


def test_golden_indian_gross_profit_is_unmapped_not_guessed():
    report, _, _ = _report("golden_indian.pdf")
    assert CanonicalConcept.GROSS_PROFIT in report.unmapped
    missing = report.get(CanonicalConcept.GROSS_PROFIT, Period(2024, "2024"))
    assert is_unavailable(missing)
    assert missing.reason is UnavailableReason.MISSING_INPUT


def test_total_income_never_becomes_revenue():
    report, _, _ = _report("golden_indian.pdf")
    rev = report.get(CanonicalConcept.REVENUE, Period(2024, "2024"))
    assert rev.source_label == "Revenue from operations"
    assert rev.value == Decimal("124500000000")  # not 12,770.50 crore


def test_golden_us_balance_sheet_has_no_2022_and_says_so():
    report, _, _ = _report("golden_us.pdf")
    v = report.get(CanonicalConcept.TOTAL_ASSETS, Period(2022, "2022"))
    assert is_unavailable(v)
    assert v.reason is UnavailableReason.MISSING_INPUT


def test_hostile_unparseable_cells_carry_their_cause():
    report, _, _ = _report("hostile.pdf")
    v = report.get(CanonicalConcept.OPERATING_INCOME, Period(2024, "2024"))
    assert is_unavailable(v)
    assert v.reason is UnavailableReason.UNPARSEABLE
    assert v.root().reason is UnavailableReason.UNPARSEABLE
    cogs = report.get(CanonicalConcept.COGS, Period(2024, "2024"))
    assert cogs.value == Decimal(0)
    assert cogs.cell.dash_zero is True


def test_duplicate_claims_for_one_concept_are_a_conflict_not_a_choice():
    _, normalized, periods = _report("golden_indian.pdf")
    inc = normalized.income
    revenue_row = next(r for r in inc.table.rows if r.label == "Revenue from operations")
    other_row = next(r for r in inc.table.rows if r.label == "Other income")
    mappings = (
        RowMapping(
            CanonicalConcept.REVENUE,
            revenue_row.ref.ref_id,
            StatementKind.INCOME,
            ExtractionConfidence.SYNONYM_MATCH,
        ),
        RowMapping(
            CanonicalConcept.REVENUE,
            other_row.ref.ref_id,
            StatementKind.INCOME,
            ExtractionConfidence.LLM_MAPPED,
        ),
    )
    out = validate_mappings(mappings, normalized, periods)
    assert len(out.conflicts) == 1
    assert out.conflicts[0].reason is UnavailableReason.CONFLICT
    assert is_unavailable(out.get(CanonicalConcept.REVENUE, Period(2024, "2024")))


def test_wrong_statement_claim_is_rejected():
    _, normalized, periods = _report("golden_indian.pdf")
    bs_row = normalized.balance.table.rows[0]
    mappings = (
        RowMapping(
            CanonicalConcept.REVENUE,
            bs_row.ref.ref_id,
            StatementKind.BALANCE,
            ExtractionConfidence.LLM_MAPPED,
        ),
    )
    out = validate_mappings(mappings, normalized, periods)
    assert out.conflicts and CanonicalConcept.REVENUE in out.unmapped


def test_unknown_ref_is_rejected():
    _, normalized, periods = _report("golden_indian.pdf")
    mappings = (
        RowMapping(
            CanonicalConcept.REVENUE,
            "page_99_table_9_row_9",
            StatementKind.INCOME,
            ExtractionConfidence.LLM_MAPPED,
        ),
    )
    out = validate_mappings(mappings, normalized, periods)
    assert out.conflicts and CanonicalConcept.REVENUE in out.unmapped

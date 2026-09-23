"""Every eval outcome, with hand-built mapped values. Scale MILLION -> tolerance 500,000."""

from decimal import Decimal

from evals.score import score, summarize
from evals.truth_xbrl import TruthValue

from fincopilot.types import (
    AnalysisResult,
    AnalyticalConfidence,
    ExtractionConfidence,
    FinancialValue,
    MappingReport,
    MetricSet,
    NormalizedCell,
    Period,
    ReconciliationReport,
    Scale,
    ScaleSource,
    StatementBasis,
    StatementSet,
    TrendSet,
    Unavailable,
    UnavailableReason,
)
from fincopilot.types import CanonicalConcept as C
from tests.helpers import make_source_ref


def _fv(concept: C, year: int, value: str, *, row: int = 0) -> FinancialValue:
    cell = NormalizedCell(
        ref=make_source_ref(page=3, row_idx=row, row_label=f"{concept.value} row"),
        raw_token=value,
        value=Decimal(value),
        scale=Scale.MILLION,
        scale_source=ScaleSource.TABLE,
        currency="USD",
    )
    return FinancialValue.from_cell(
        concept=concept,
        period=Period(year, str(year)),
        cell=cell,
        extraction_confidence=ExtractionConfidence.EXACT_MATCH,
        analytical_confidence=AnalyticalConfidence.HIGH,
    )


def _result(*values: FinancialValue, unavailable=None) -> AnalysisResult:
    gone = Unavailable(UnavailableReason.NOT_LOCATED, "not needed here")
    return AnalysisResult(
        document_id="doc-test",
        statements=StatementSet(StatementBasis.CONSOLIDATED, gone, gone, gone),
        periods=gone,
        values=values,
        metrics=(),
        trends=(),
        reconciliations=(),
        red_flags=(),
        mapping=MappingReport(values=values, unavailable={}, unmapped=(), conflicts=()),
        metric_set=MetricSet(values=values, metrics=(), unavailable=unavailable or {}),
        trend_set=TrendSet((), {}),
        reconciliation_report=ReconciliationReport(()),
    )


def _one(result: AnalysisResult, *truth: TruthValue):
    records = score(result, list(truth), ticker="TEST", accession="0000000001-23-000001")
    return records[0]


def _t(concept: C, year: int, *values: str) -> TruthValue:
    return TruthValue(concept.value, year, values, ("SomeTag",))


def test_correct_exactly_at_the_tolerance_boundary():
    r = _one(_result(_fv(C.REVENUE, 2023, "1000500000")), _t(C.REVENUE, 2023, "1000000000"))
    assert (r.outcome, r.sub) == ("correct", None)
    assert (r.app_value, r.ref_id, r.row_label, r.page) == (
        "1000500000",
        "page_3_table_0_row_0",
        "revenue row",
        3,
    )


def test_wrong_just_past_the_tolerance():
    r = _one(_result(_fv(C.REVENUE, 2023, "1000500001")), _t(C.REVENUE, 2023, "1000000000"))
    assert (r.outcome, r.sub) == ("wrong", "value")


def test_any_accepted_truth_value_counts():
    truth = _t(C.REVENUE, 2023, "900000000", "905000000")
    r = _one(_result(_fv(C.REVENUE, 2023, "905000000")), truth)
    assert r.outcome == "correct"


def test_opposite_sign_is_a_sign_mismatch():
    r = _one(_result(_fv(C.NET_INCOME, 2023, "-200000000")), _t(C.NET_INCOME, 2023, "200000000"))
    assert (r.outcome, r.sub) == ("wrong", "sign_mismatch")


def test_sign_agnostic_concept_is_correct_either_sign():
    r = _one(_result(_fv(C.CAPEX, 2023, "-50000000")), _t(C.CAPEX, 2023, "50000000"))
    assert (r.outcome, r.sub) == ("correct", None)


def test_value_of_another_year_is_wrong_period():
    result = _result(_fv(C.TOTAL_ASSETS, 2023, "4500000000"))
    r = _one(result, _t(C.TOTAL_ASSETS, 2023, "5000000000"), _t(C.TOTAL_ASSETS, 2022, "4500000000"))
    assert (r.outcome, r.sub) == ("wrong", "wrong_period")


def test_withheld_records_the_root_reason():
    root = Unavailable(UnavailableReason.AMBIGUOUS, "two rows claim cash")
    missing = Unavailable(UnavailableReason.MISSING_INPUT, "cash unavailable", cause=root)
    result = _result(unavailable={("cash", Period(2023, "FY23")): missing})
    r = _one(result, _t(C.CASH, 2023, "10"))
    assert (r.outcome, r.app_value) == ("withheld", None)
    assert r.reason == "ambiguous: two rows claim cash"


def test_withheld_without_an_entry_is_not_mapped():
    r = _one(_result(), _t(C.CASH, 2023, "10"))
    assert (r.outcome, r.reason) == ("withheld", "not_mapped")


def test_mapped_value_without_truth_is_unverified_and_outside_every_ratio():
    result = _result(_fv(C.CASH, 2023, "10"), _fv(C.TOTAL_DEBT, 2023, "10", row=1))
    records = score(result, [], ticker="TEST", accession="0000000001-23-000001")
    # total_debt is not in CONCEPT_TAGS, so it is never scored, not even as unverified.
    assert [(r.concept, r.outcome) for r in records] == [("cash", "unverified")]
    totals = summarize(records)["totals"]
    assert totals["unverified"] == 1
    assert totals["precision"] == totals["coverage"] == "n/a"


def test_summary_ratios_per_concept_and_per_filing():
    result = _result(_fv(C.REVENUE, 2023, "100"), _fv(C.REVENUE, 2022, "9000000"))
    truth = [_t(C.REVENUE, 2023, "100"), _t(C.REVENUE, 2022, "5000000"), _t(C.CASH, 2023, "1")]
    summary = summarize(score(result, truth, ticker="TEST", accession="A"))
    t = summary["totals"]
    assert (t["correct"], t["wrong"], t["withheld"], t["value"]) == (1, 1, 1, 1)
    assert (t["precision"], t["coverage"], t["wrong_rate"]) == ("0.5000", "0.6667", "0.3333")
    assert summary["per_concept"]["revenue"]["precision"] == "0.5000"
    assert summary["per_filing"]["TEST_A"] == t

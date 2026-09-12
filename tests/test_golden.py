"""Phase 8 golden tests. Spec 9, 10.1.

test_golden_deterministic: NullMapper, no I/O after extraction, every
expected value at Decimal precision, complete provenance chain, zero
fabricated values. test_golden_with_fallback: scripted fake LLM including
an invalid row ID. Both run in CI with no Ollama installed.
"""

import json
import urllib.request
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pipeline
import pytest

from fincopilot.ai.client import NullMapper
from fincopilot.calc.ratios import RATIO_CONTEXT
from fincopilot.types import (
    AnalyticalConfidence,
    ExtractionConfidence,
    FinancialValue,
    Period,
    RuleOutcome,
    StatementBasis,
    is_unavailable,
)
from fincopilot.types import CanonicalConcept as C

FIXTURES = Path(__file__).parent / "fixtures"
GOLDENS = ("golden_indian", "golden_us")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any HTTP attempt fails the test. The deterministic path performs none."""

    def forbidden(*a, **k):
        raise AssertionError("network I/O attempted during a golden test")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)


def _expected(name):
    return json.loads((FIXTURES / "expected" / f"{name}.json").read_text(encoding="utf-8"))


def _run(name, llm=None):
    return pipeline.analyze((FIXTURES / f"{name}.pdf").read_bytes(), llm=llm)


def _assert_every_expected_value(result, expected):
    for concept, spec in expected["mapped"].items():
        for year, base in spec.items():
            if not year.isdigit():
                continue
            fv = result.metric_set.value(C(concept), Period(int(year), year))
            assert isinstance(fv, FinancialValue), (concept, year, fv)
            assert fv.value == Decimal(base), (concept, year)  # full Decimal precision
            assert fv.source_label == spec["source_label"]
            assert fv.source_page == spec["page"]
            assert fv.cell is not None and fv.derived_from is None
    for concept, spec in expected["derived"].items():
        for year, base in spec.items():
            if not year.isdigit():
                continue
            fv = result.metric_set.value(C(concept), Period(int(year), year))
            assert isinstance(fv, FinancialValue), (concept, year, fv)
            assert fv.value == Decimal(base), (concept, year)
            assert fv.derived_from == tuple(spec["from"])
    for concept in expected.get("unmapped", []):
        assert C(concept) in result.mapping.unmapped
        assert not any(v.concept is C(concept) for v in result.values)


def _assert_provenance_chain(result, name):
    """PDF -> cell -> SourceRef -> NormalizedCell -> FinancialValue -> Metric -> RedFlag."""
    by_ref = {v.cell.ref.ref_id: v for v in result.values if v.cell is not None}
    with pdfplumber.open(FIXTURES / f"{name}.pdf") as pdf:
        page_text = {
            p: (pdf.pages[p - 1].extract_text() or "")
            for p in {r.page for r in (v.cell.ref for v in by_ref.values())}
        }
    for v in by_ref.values():
        cell = v.cell
        assert v.value == cell.value  # FinancialValue <- NormalizedCell
        assert cell.ref.ref_id in by_ref  # NormalizedCell <- SourceRef
        assert cell.raw_token in page_text[cell.ref.page]  # SourceRef <- PDF page
        assert cell.ref.row_label in page_text[cell.ref.page]
    concepts_with_cells = {v.concept.value for v in by_ref.values()}
    derived = {v.concept.value: v for v in result.values if v.cell is None}

    def resolves(ref: str) -> bool:
        # A ref is a cell ref, a derived concept whose inputs are cell-backed, or a
        # period-tagged concept from an averaged denominator (e.g. total_assets_2024).
        if ref in by_ref or ref in concepts_with_cells:
            return True
        if ref in derived:
            return all(resolves(x) for x in derived[ref].derived_from)
        base, _, year = ref.rpartition("_")
        return year.isdigit() and (base in concepts_with_cells or base in derived)

    for m in result.metrics:  # Metric <- FinancialValue(s)
        assert m.inputs
        for ref in m.inputs:
            assert resolves(ref), (m.name, ref)
    fired_or_clear = [f for f in result.red_flags if f.outcome is not RuleOutcome.NOT_EVALUATED]
    assert fired_or_clear
    assert any(f.refs for f in fired_or_clear)
    for f in fired_or_clear:  # RedFlag <- Metric/FinancialValue refs
        for ref in f.refs:
            assert resolves(ref), (f.rule_id, ref)


def _assert_zero_fabrication(result):
    concepts_present = {v.concept for v in result.values}
    for v in result.values:
        if v.cell is None:
            assert v.derived_from
            for name in v.derived_from:
                assert C(name) in concepts_present
        else:
            assert v.value == v.cell.value
    for v in result.values:
        assert v.value.is_finite()


@pytest.mark.parametrize("name", GOLDENS)
def test_golden_deterministic(name):
    expected = _expected(name)
    result = _run(name, llm=NullMapper())

    assert result.basis is StatementBasis.CONSOLIDATED
    assert [p.end_year for p in result.periods.ordered] == [
        p["end_year"] for p in expected["periods"]
    ]
    assert not result.mapping.conflicts
    _assert_every_expected_value(result, expected)
    _assert_provenance_chain(result, name)
    _assert_zero_fabrication(result)
    assert all(
        v.extraction_confidence
        in (ExtractionConfidence.EXACT_MATCH, ExtractionConfidence.SYNONYM_MATCH)
        for v in result.values
    )
    assert all(v.analytical_confidence is AnalyticalConfidence.HIGH for v in result.values)


def test_golden_deterministic_runs_with_no_client_at_all():
    result = _run("golden_us", llm=None)
    assert result.metric_set.value(C.REVENUE, Period(2024, "2024")).value == Decimal("8420000000")


def test_golden_us_ratios_at_declared_precision():
    result = _run("golden_us", llm=NullMapper())
    e = _expected("golden_us")["mapped"]
    p24 = Period(2024, "2024")
    div = RATIO_CONTEXT.divide
    assert result.metric_set.metric("gross_margin", p24).value == div(
        Decimal(e["gross_profit"]["2024"]), Decimal(e["revenue"]["2024"])
    )
    assert result.metric_set.metric("ocf_to_net_income", p24).value == div(
        Decimal(e["operating_cash_flow"]["2024"]), Decimal(e["net_income"]["2024"])
    )
    assert is_unavailable(result.metric_set.metric("roa", Period(2022, "2022")))


def test_golden_red_flags_are_all_evaluated_or_explained():
    result = _run("golden_us", llm=NullMapper())
    flags = {f.rule_id: f for f in result.red_flags}
    assert len(flags) == 10
    assert flags["low_confidence_kpi"].outcome is RuleOutcome.CLEAR
    assert flags["reconciliation_warning"].outcome is RuleOutcome.CLEAR
    assert flags["revenue_decline"].outcome is RuleOutcome.CLEAR
    for f in result.red_flags:
        if f.outcome is RuleOutcome.NOT_EVALUATED:
            assert f.reason is not None and f.reason.root().detail


class ScriptedClient:
    """Canned row IDs per concept, including one that does not exist."""

    def __init__(self, answers):
        self.answers = answers
        self.prompts = []

    def complete_json(self, prompt, schema):
        self.prompts.append(prompt)
        concept = prompt.split("Concept: ")[1].splitlines()[0]
        return json.dumps({"source_row_id": self.answers.get(concept)})


def test_golden_with_fallback():
    baseline = _run("golden_indian", llm=NullMapper())
    # Row 1 of the P&L is "Other income": a VALID but semantically wrong pick.
    client = ScriptedClient(
        {"gross_profit": "page_41_table_0_row_1", "ebitda": "page_99_table_9_row_9"}
    )
    result = _run("golden_indian", llm=client)

    assert client.prompts
    for prompt in client.prompts:
        assert "12,450.00" not in prompt and "124500000000" not in prompt

    # The hallucinated ID was rejected; ebitda is still derived, not mapped.
    ebitda = result.metric_set.value(C.EBITDA, Period(2024, "2024"))
    assert ebitda.derived_from == ("operating_income", "d_and_a")
    assert not result.mapping.conflicts

    # The valid pick became LLM_MAPPED, capped at MEDIUM, and Python took the number.
    gp = result.metric_set.value(C.GROSS_PROFIT, Period(2024, "2024"))
    assert gp.extraction_confidence is ExtractionConfidence.LLM_MAPPED
    assert gp.analytical_confidence is AnalyticalConfidence.MEDIUM
    assert gp.value == Decimal("3205000000")
    assert gp.source_label == "Other income"
    gm = result.metric_set.metric("gross_margin", Period(2024, "2024"))
    assert gm.value == RATIO_CONTEXT.divide(Decimal("3205000000"), Decimal("124500000000"))
    assert gm.analytical_confidence is AnalyticalConfidence.MEDIUM

    # Every deterministic value is byte-for-byte what NullMapper produced.
    def key(v):  # document_id is a fresh UUID per run; everything else must match
        cell = (v.cell.ref.ref_id, v.cell.raw_token) if v.cell else None
        return (
            v.value,
            v.currency,
            v.extraction_confidence,
            v.analytical_confidence,
            cell,
            v.derived_from,
        )

    det = {(v.concept, v.period): key(v) for v in baseline.values}
    for v in result.values:
        if v.concept is not C.GROSS_PROFIT:
            assert det[(v.concept, v.period)] == key(v)
    _assert_every_expected_value(result, _expected("golden_indian") | {"unmapped": []})
    _assert_provenance_chain(result, "golden_indian")
    _assert_zero_fabrication(result)
    flags = {f.rule_id: f for f in result.red_flags}
    assert (
        flags["low_confidence_kpi"].outcome is RuleOutcome.CLEAR
    )  # revenue/NI still deterministic

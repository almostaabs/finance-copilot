"""End-to-end on the six edge fixtures. Each fails in its named way, nothing crashes."""

from decimal import Decimal
from pathlib import Path

import pipeline
import pytest

from fincopilot.ai.client import NullMapper
from fincopilot.extract.pdf import ScannedPDFUnsupported
from fincopilot.types import CanonicalConcept as C
from fincopilot.types import Period, RuleOutcome, StatementBasis, UnavailableReason, is_unavailable

FIXTURES = Path(__file__).parent / "fixtures"
P24 = Period(2024, "2024")


def _run(name):
    return pipeline.analyze((FIXTURES / f"{name}.pdf").read_bytes(), llm=NullMapper())


def test_scanned_is_rejected_at_the_gate():
    with pytest.raises(ScannedPDFUnsupported):
        _run("scanned")


def test_standalone_only_labels_the_fallback_at_every_level():
    r = _run("standalone_only")
    assert r.basis is StatementBasis.STANDALONE_FALLBACK
    assert r.statements.income.basis is StatementBasis.STANDALONE_FALLBACK
    assert r.metric_set.value(C.REVENUE, P24).value == Decimal("34200000000")
    assert is_unavailable(r.statements.cash_flow)
    assert {f.rule_id: f for f in r.red_flags}["negative_ocf"].outcome is RuleOutcome.NOT_EVALUATED


def test_stitched_maps_total_assets_from_the_second_page():
    r = _run("stitched")
    ta = r.metric_set.value(C.TOTAL_ASSETS, P24)
    assert ta.value == Decimal("136200000000")
    assert ta.source_page == 6
    assert ta.cell.ref.ref_id == "page_6_table_0_row_2"
    assert r.statements.balance.table.pages == (5, 6)


def test_ambiguous_periods_is_unavailable_for_the_whole_document():
    r = _run("ambiguous_periods")
    assert is_unavailable(r.periods)
    assert r.periods.reason is UnavailableReason.AMBIGUOUS
    assert r.values == () and r.metrics == ()
    for f in r.red_flags:
        assert f.outcome is RuleOutcome.NOT_EVALUATED
        assert f.reason.root().reason is UnavailableReason.AMBIGUOUS


def test_no_scale_yields_no_values_and_an_ambiguous_reason():
    r = _run("no_scale")
    assert r.values == ()
    rev = r.mapping.get(C.REVENUE, P24)
    assert is_unavailable(rev)


def test_hostile_completes_with_every_malformed_value_explained():
    r = _run("hostile")
    ms = r.metric_set
    assert ms.value(C.REVENUE, P24).value == Decimal("9999999999999999990000000")
    assert ms.value(C.COGS, P24).value == Decimal(0) and ms.value(C.COGS, P24).cell.dash_zero
    assert ms.value(C.COGS, Period(2023, "2023")).reason is UnavailableReason.MISSING_INPUT
    assert ms.value(C.OPERATING_INCOME, P24).reason is UnavailableReason.UNPARSEABLE
    assert ms.value(C.D_AND_A, P24).value == Decimal("1234560000000")
    assert ms.value(C.NET_INCOME, P24).value == Decimal("-12455000000")
    assert ms.value(C.EQUITY, P24).value == Decimal("-8200000000")
    de = ms.metric("debt_to_equity", P24)
    assert is_unavailable(de) and de.reason is UnavailableReason.AMBIGUOUS
    flags = {f.rule_id: f for f in r.red_flags}
    assert flags["high_leverage"].outcome is RuleOutcome.NOT_EVALUATED
    assert flags["weak_liquidity"].outcome is RuleOutcome.FIRED  # 1,640 / 2,920
    for v in r.values:
        assert v.value.is_finite()
    # The injection text changed nothing: revenue is the document number.
    assert not any("99,999.99" in (v.source_text or "") for v in r.values)

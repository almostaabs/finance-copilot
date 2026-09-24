"""XBRL companyfacts -> truth values, against a hand-written excerpt."""

import json
from pathlib import Path

import pytest
from evals.concept_tags import CONCEPT_TAGS
from evals.truth_xbrl import (
    TruthValue,
    fy_check,
    fy_mismatch,
    read_truth,
    truth_for_filing,
    write_truth,
)

from fincopilot.types import CanonicalConcept as C

FACTS = json.loads(
    (Path(__file__).parent / "fixtures" / "evals" / "companyfacts_min.json").read_text("utf-8")
)
ACCN = "0001234567-23-000010"


@pytest.fixture(scope="module")
def result():
    truth, notes = truth_for_filing(FACTS, ACCN)
    return {(t.concept, t.end_year): t for t in truth}, notes


def test_only_facts_from_the_requested_accession_are_truth(result):
    truth, _ = result
    assert ("revenue", 2021) not in truth  # that fact belongs to the prior 10-K


def test_quarterly_facts_are_dropped(result):
    truth, notes = result
    assert "250000" not in truth[("revenue", 2023)].values
    assert any(n.startswith("revenue/Revenues: dropped 1") for n in notes)


def test_year_comes_from_end_date_not_fy(result):
    truth, _ = result
    # Comparative carries fy=2023 but ends in 2022.
    assert truth[("revenue", 2022)].values == ("900000", "905000")


def test_instants_are_kept_for_balance_concepts(result):
    truth, _ = result
    assert truth[("total_assets", 2023)].values == ("5000000",)
    assert truth[("total_assets", 2022)].values == ("4500000",)


def test_wrong_kind_of_fact_is_dropped_with_a_note(result):
    truth, notes = result
    assert truth[("net_income", 2023)].values == ("200000",)  # instant 999 dropped
    assert not any(c == "current_assets" for c, _ in truth)  # duration on an instant concept
    assert any(n.startswith("net_income/NetIncomeLoss: dropped 1") for n in notes)
    assert any(n.startswith("current_assets/AssetsCurrent: dropped 1") for n in notes)


def test_same_tag_conflicting_values_exclude_the_year_with_a_note(result):
    truth, notes = result
    assert ("operating_cash_flow", 2023) not in truth
    assert truth[("operating_cash_flow", 2022)].values == ("280000",)
    assert any("operating_cash_flow 2023: excluded" in n for n in notes)


def test_multiple_tags_all_accepted_and_recorded(result):
    truth, _ = result
    both = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert truth[("revenue", 2023)] == TruthValue("revenue", 2023, ("1000000",), both)
    assert truth[("revenue", 2022)].tags == both


def test_truth_file_round_trips(tmp_path):
    truth, notes = truth_for_filing(FACTS, ACCN)
    path = write_truth(tmp_path, "TEST", ACCN, truth, notes)
    assert path.name == f"TEST_{ACCN}.json"
    assert read_truth(path) == (truth, notes, None)


def test_derived_concepts_have_no_truth_tags():
    assert {C.EBITDA, C.TOTAL_DEBT, C.FREE_CASH_FLOW}.isdisjoint(CONCEPT_TAGS)
    assert len(CONCEPT_TAGS) == 16


def _filing(fy: int, *periods: tuple[str, str], fys: tuple[int, ...] = ()) -> dict:
    """One filing's NetIncomeLoss facts: (start, end) pairs, all with `fy` unless `fys`."""
    facts = [
        {"start": s, "end": e, "val": 100 + i, "accn": "A", "fy": (fys or (fy,) * 9)[i]}
        for i, (s, e) in enumerate(periods)
    ]
    return {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": facts}}}}}


def _years(facts: dict, offset: int = 0, tmp_path=None) -> dict[int, tuple[str, ...]]:
    """Truth years as run.py sees them: frozen by end year, shifted by the corpus offset."""
    truth, notes = truth_for_filing(facts, "A")
    path = write_truth(tmp_path, "T", "A", truth, notes, fy_check(facts, "A"))
    return {t.end_year: t.values for t in read_truth(path, offset)[0]}


def test_january_filers_keep_the_end_year_by_default_whatever_fy_says(tmp_path):
    # Lowe's prints "January 30, 2026"; Salesforce calls its year ending 2026-01-31
    # "fiscal 2026". Both carry fy 2025, and fy must not move the truth year.
    low = _filing(2025, ("2025-02-01", "2026-01-30"), ("2024-02-03", "2025-01-31"))
    crm = _filing(2025, ("2025-02-01", "2026-01-31"), ("2024-02-01", "2025-01-31"))
    for facts in (low, crm):
        assert _years(facts, tmp_path=tmp_path) == {2026: ("100",), 2025: ("101",)}
        assert fy_mismatch(fy_check(facts, "A"), 0)  # listed for a header check


def test_evidenced_override_shifts_every_year_back_one(tmp_path):
    # Home Depot prints the year ending 2026-02-01 as "Fiscal 2025": corpus offset -1.
    facts = _filing(2025, ("2025-02-03", "2026-02-01"), ("2024-02-05", "2025-02-02"))
    assert _years(facts, -1, tmp_path) == {2025: ("100",), 2024: ("101",)}
    assert not fy_mismatch(fy_check(facts, "A"), -1)


def test_december_filer_keeps_the_end_year_and_is_not_listed(tmp_path):
    facts = _filing(2025, ("2025-01-01", "2025-12-31"), ("2024-01-01", "2024-12-31"))
    assert _years(facts, tmp_path=tmp_path) == {2025: ("100",), 2024: ("101",)}
    assert fy_check(facts, "A") == {"fy": [2025], "latest_end": "2025-12-31"}
    assert not fy_mismatch(fy_check(facts, "A"), 0)


def test_inconsistent_fy_keeps_the_truth_and_is_listed(tmp_path):
    facts = _filing(
        2025, ("2025-01-01", "2025-12-31"), ("2024-01-01", "2024-12-31"), fys=(2025, 2024)
    )
    assert _years(facts, tmp_path=tmp_path) == {2025: ("100",), 2024: ("101",)}
    assert fy_mismatch(fy_check(facts, "A"), 0)


def test_net_income_accepts_profit_loss_after_net_income_loss():
    assert CONCEPT_TAGS[C.NET_INCOME].tags == ("NetIncomeLoss", "ProfitLoss")

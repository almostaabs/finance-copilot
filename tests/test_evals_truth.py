"""XBRL companyfacts -> truth values, against a hand-written excerpt."""

import json
from pathlib import Path

import pytest
from evals.concept_tags import CONCEPT_TAGS
from evals.truth_xbrl import TruthValue, read_truth, truth_for_filing, write_truth

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
    assert read_truth(path) == (truth, notes)


def test_derived_concepts_have_no_truth_tags():
    assert {C.EBITDA, C.TOTAL_DEBT, C.FREE_CASH_FLOW}.isdisjoint(CONCEPT_TAGS)
    assert len(CONCEPT_TAGS) == 16

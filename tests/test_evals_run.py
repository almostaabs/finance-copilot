"""T1.1: eval CLI pieces that need no network: split, filing lock, and --compare exit code."""

from __future__ import annotations

import hashlib
import json

import pytest
from evals import run as R

from fincopilot.sources.edgar import Filing


def _f(accession: str, filed: str, reported: str) -> Filing:
    return Filing("0000000001", accession, "10-K", filed, reported, "doc.htm")


# Newest first, as EdgarClient.annual_filings returns them.
FILINGS = [
    _f("A-26-2", "2026-08-01", "2026-06-30"),
    _f("A-26-1", "2026-06-30", "2025-12-31"),
    _f("A-24", "2024-07-30", "2024-06-30"),
    _f("A-23", "2023-11-03", "2023-09-30"),
]


def test_split_is_the_sha256_rule_and_stable():
    for ticker in ("AAPL", "MSFT", "BRK-B", "T"):
        n = int(hashlib.sha256(ticker.encode()).hexdigest(), 16) % 10
        assert R.split_for(ticker) == ("holdout" if n < 3 else "dev")
    assert R.split_for("AAPL") == "holdout"
    assert R.split_for("MSFT") == "dev"


def test_corpus_is_the_fixed_50_with_four_local_pdfs():
    rows = R.read_corpus()
    assert len(rows) == 50
    assert {r["bucket"] for r in rows} == {"general", "financial"}
    assert sum(r["bucket"] == "financial" for r in rows) == 8
    local = {r["ticker"]: r["local_pdf"] for r in rows if r["local_pdf"]}
    assert local == {
        "AAPL": "apple_10k_2023.pdf",
        "MSFT": "microsoft_fy24.pdf",
        "BRK-B": "berkshire_2023.pdf",
        "MBIN": "merchants_bank_2024.pdf",
    }


@pytest.mark.parametrize(
    ("name", "year"),
    [
        ("apple_10k_2023.pdf", 2023),
        ("microsoft_fy24.pdf", 2024),
        ("berkshire_2023.pdf", 2023),
        ("merchants_bank_2024.pdf", 2024),
    ],
)
def test_fiscal_year_comes_from_the_end_of_the_file_name(name, year):
    assert R.fiscal_year_of(name) == year


def test_latest_filing_on_or_before_the_cutoff_is_selected():
    assert R.select_filing(FILINGS, "").accession == "A-26-1"


def test_local_pdf_selects_the_10k_whose_report_date_matches_its_year():
    assert R.select_filing(FILINGS, "apple_10k_2023.pdf").accession == "A-23"
    assert R.select_filing(FILINGS, "microsoft_fy24.pdf").accession == "A-24"


def test_local_pdf_with_no_or_two_matching_10ks_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="0 10-Ks"):
        R.select_filing(FILINGS, "old_2019.pdf")
    two = [*FILINGS, _f("A-23b", "2023-12-01", "2023-12-31")]
    with pytest.raises(ValueError, match="2 10-Ks"):
        R.select_filing(two, "apple_10k_2023.pdf")


def test_no_filing_before_the_cutoff_is_an_error():
    with pytest.raises(ValueError, match="no 10-K"):
        R.select_filing(FILINGS[:1], "")


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def cik_for_ticker(self, ticker: str) -> str:
        self.calls += 1
        return "0000000001"

    def annual_filings(self, cik: str) -> list[Filing]:
        return FILINGS


def test_first_run_selects_and_writes_the_lock_later_runs_only_read_it(tmp_path):
    path = tmp_path / "corpus.lock.json"
    client = FakeClient()
    lock = R.read_lock(path)
    assert lock == {}
    assert R.locked_filing("X", "", lock, client, path).accession == "A-26-1"
    assert client.calls == 1
    assert json.loads(path.read_text())["X"]["accession"] == "A-26-1"

    reread = R.read_lock(path)
    assert reread == {"X": FILINGS[1]}
    assert R.locked_filing("X", "apple_10k_2023.pdf", reread, client, path) == FILINGS[1]
    assert client.calls == 1  # never re-selected


def _report(wrong: int, precision: str) -> dict:
    totals = dict.fromkeys(R._TOTAL_COLS, 0) | {
        "wrong": wrong,
        "precision": precision,
        "coverage": "n/a",
        "wrong_rate": "n/a",
    }
    return {"summary": {"all": {"totals": totals}}}


@pytest.mark.parametrize(
    ("old", "new", "regressed"),
    [
        (_report(2, "0.9000"), _report(2, "0.9000"), False),
        (_report(2, "0.9000"), _report(1, "0.9500"), False),
        (_report(2, "0.9000"), _report(3, "0.9500"), True),
        (_report(2, "0.9000"), _report(2, "0.8999"), True),
        (_report(0, "n/a"), _report(0, "0.9000"), False),
    ],
)
def test_compare_flags_more_wrong_or_lower_precision(old, new, regressed):
    assert R.compare(new, old)[1] is regressed


def test_compare_on_identical_totals_reports_no_change():
    lines, regressed = R.compare(_report(2, "0.9000"), _report(2, "0.9000"))
    assert lines == ["all: no change"]
    assert not regressed


@pytest.mark.parametrize(("old_wrong", "code"), [(5, 0), (0, 1)])
def test_main_exits_1_only_when_compare_regresses(tmp_path, monkeypatch, old_wrong, code):
    record = {
        "ticker": "MSFT", "accession": "A", "concept": "revenue", "end_year": 2024,
        "outcome": "wrong", "sub": "value", "app_value": "1", "truth_values": ["2"],
        "tags": ["Revenues"], "ref_id": "r", "row_label": "Revenue", "page": 1,
        "reason": None, "bucket": "general",
    }  # fmt: skip
    company = {"ticker": "MSFT", "bucket": "general", "split": "dev", "status": "ok", "error": None}
    monkeypatch.setattr(R, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(R, "EXPOSED", tmp_path / "none.json")
    monkeypatch.setattr(R.EdgarClient, "from_env", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(R, "run", lambda rows, workers, client: ([company], [record]))
    old = tmp_path / "old.json"
    old.write_text(json.dumps(_report(old_wrong, "0.0000")))
    assert R.main(["--only", "MSFT", "--compare", str(old)]) == code
    assert (tmp_path / "latest_dev.json").exists()


def _rec(ticker: str, bucket: str, outcome: str) -> dict:
    return {
        "ticker": ticker, "accession": "A", "concept": "revenue", "end_year": 2024,
        "outcome": outcome, "sub": "value" if outcome == "wrong" else None,
        "app_value": "1", "truth_values": ["1"], "tags": ["Revenues"], "ref_id": "r",
        "row_label": "Revenue", "page": 1, "reason": None, "bucket": bucket,
    }  # fmt: skip


def test_exposed_holdout_company_is_kept_out_of_headline_totals_and_reported_alone():
    companies = [
        {"ticker": "AAPL", "bucket": "general", "split": "holdout", "status": "ok"},
        {"ticker": "INTC", "bucket": "general", "split": "holdout", "status": "ok"},
        {"ticker": "KO", "bucket": "general", "split": "dev", "status": "ok"},
    ]
    records = [_rec("AAPL", "general", "wrong"), _rec("INTC", "general", "correct")]
    records.append(_rec("KO", "general", "correct"))
    exposed = {"AAPL": "viewed", "KO": "viewed"}  # KO is dev: exposure only matters in holdout
    report = R.build_report(
        companies, records, split="holdout", bucket="all", only=[], exposed=exposed
    )
    assert report["exposed"] == ["AAPL"]
    assert report["summary"]["all"]["totals"]["wrong"] == 0
    assert report["summary"]["all"]["totals"]["correct"] == 2
    assert report["summary"]["general"]["totals"]["wrong"] == 0
    assert report["summary"]["exposed"]["totals"]["wrong"] == 1
    assert report["summary"]["exposed"]["per_filing"].keys() == {"AAPL_A"}
    assert [c["exposed"] for c in companies] == ["viewed", None, None]
    assert "exposed (holdout" in R.markdown(report)


def test_exposed_file_lists_the_pilot_holdout_companies():
    exposed = R.read_exposed()
    pilot = ("AAPL", "MSFT", "KO", "XOM", "JPM")
    assert set(exposed) == {t for t in pilot if R.split_for(t) == "holdout"} == {"AAPL"}

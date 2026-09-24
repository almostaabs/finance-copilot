"""T1.1: EDGAR client. A fake opener stands in for the network; nothing here goes online."""

from __future__ import annotations

import http.client
import json

import pytest

from fincopilot.sources.edgar import EdgarClient, Filing, SourceError

UA = "finance-copilot test@example.invalid"


class FakeOpener:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.requests = []

    def __call__(self, request) -> bytes:
        self.requests.append(request)
        body = self.responses.get(request.full_url)
        if body is None:
            raise OSError("no route")
        return body


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


def _client(tmp_path, responses, clock=None):
    opener = FakeOpener(responses)
    clock = clock or FakeClock()
    client = EdgarClient(UA, tmp_path, opener=opener, clock=clock, sleep=clock.sleep)
    return client, opener


def _submissions(forms, files=()):
    n = len(forms)
    return {
        "filings": {
            "recent": {
                "form": list(forms),
                "accessionNumber": [f"0000000001-2{i}-000001" for i in range(n)],
                "filingDate": [f"202{i}-02-01" for i in range(n)],
                "reportDate": [f"202{i - 1}-12-31" for i in range(n)],
                "primaryDocument": [f"doc{i}.htm" for i in range(n)],
            },
            "files": [{"name": name} for name in files],
        }
    }


SUBS_URL = "https://data.sec.gov/submissions/CIK0000000001.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
TICKERS = json.dumps(
    {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire Hathaway"},
    }
).encode()


def test_user_agent_header_is_sent(tmp_path):
    client, opener = _client(tmp_path, {TICKERS_URL: TICKERS})
    client.cik_for_ticker("AAPL")
    assert opener.requests[0].get_header("User-agent") == UA


def test_missing_sec_user_agent_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SourceError, match="SEC_USER_AGENT is not set"):
        EdgarClient.from_env(tmp_path)


def test_blank_user_agent_is_rejected(tmp_path):
    with pytest.raises(SourceError, match="SEC_USER_AGENT"):
        EdgarClient("  ", tmp_path)


def test_cache_hit_makes_no_request(tmp_path):
    client, opener = _client(tmp_path, {TICKERS_URL: TICKERS})
    assert client.cik_for_ticker("AAPL") == "0000320193"
    fresh, fresh_opener = _client(tmp_path, {})
    assert fresh.cik_for_ticker("brk-b") == "0001067983"
    assert len(opener.requests) == 1
    assert fresh_opener.requests == []


def test_unknown_ticker_raises(tmp_path):
    client, _ = _client(tmp_path, {TICKERS_URL: TICKERS})
    with pytest.raises(SourceError, match="not found"):
        client.cik_for_ticker("ZZZZ")


def test_annual_filings_keeps_only_10k_newest_first(tmp_path):
    subs = _submissions(["10-K", "10-Q", "10-K/A", "8-K", "10-K"])
    client, _ = _client(tmp_path, {SUBS_URL: json.dumps(subs).encode()})
    filings = client.annual_filings("1")
    assert [f.form for f in filings] == ["10-K", "10-K"]
    assert [f.filing_date for f in filings] == ["2024-02-01", "2020-02-01"]
    assert filings[0] == Filing(
        cik="0000000001",
        accession="0000000001-24-000001",
        form="10-K",
        filing_date="2024-02-01",
        report_date="2023-12-31",
        primary_document="doc4.htm",
    )


def test_annual_filings_reads_older_pages(tmp_path):
    page_url = "https://data.sec.gov/submissions/CIK0000000001-submissions-001.json"
    subs = _submissions(["8-K"], files=["CIK0000000001-submissions-001.json"])
    older = _submissions(["10-K"])["filings"]["recent"]
    client, _ = _client(
        tmp_path,
        {SUBS_URL: json.dumps(subs).encode(), page_url: json.dumps(older).encode()},
    )
    assert [f.accession for f in client.annual_filings("0000000001")] == ["0000000001-20-000001"]


def test_document_url_uses_int_cik_and_undashed_accession(tmp_path):
    filing = Filing("0000320193", "0000320193-23-000106", "10-K", "", "", "aapl-20230930.htm")
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
    client, _ = _client(tmp_path, {url: b"<html></html>"})
    assert client.document(filing) == b"<html></html>"


def test_network_error_names_url_and_is_wrapped(tmp_path):
    client, _ = _client(tmp_path, {})
    with pytest.raises(SourceError, match=r"companyfacts/CIK0000000001\.json"):
        client.company_facts("1")


def test_a_truncated_response_is_wrapped_and_not_cached(tmp_path):
    class Truncating(FakeOpener):
        def __call__(self, request) -> bytes:
            self.requests.append(request)
            raise http.client.IncompleteRead(b"{", 100)

    opener = Truncating({})
    clock = FakeClock()
    client = EdgarClient(UA, tmp_path, opener=opener, clock=clock, sleep=clock.sleep)
    with pytest.raises(SourceError, match="IncompleteRead"):
        client.cik_for_ticker("AAPL")
    assert not any(tmp_path.iterdir())


def test_invalid_json_is_wrapped_and_not_cached(tmp_path):
    client, opener = _client(tmp_path, {TICKERS_URL: b"<html>rate limited</html>"})
    with pytest.raises(SourceError, match="invalid JSON") as info:
        client.cik_for_ticker("AAPL")
    assert "rate limited" not in str(info.value)
    with pytest.raises(SourceError):
        client.cik_for_ticker("AAPL")
    assert len(opener.requests) == 2


def test_requests_are_spaced_by_min_interval(tmp_path):
    clock = FakeClock()
    urls = [f"https://data.sec.gov/api/xbrl/companyfacts/CIK000000000{i}.json" for i in (1, 2, 3)]
    client, _ = _client(tmp_path, dict.fromkeys(urls, b"{}"), clock=clock)
    client.company_facts("1")
    assert clock.sleeps == []
    clock.now += 0.05
    client.company_facts("2")
    assert clock.sleeps == [pytest.approx(0.10)]
    clock.now += 1.0
    client.company_facts("3")
    assert clock.sleeps == [pytest.approx(0.10)]

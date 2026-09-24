"""SEC EDGAR fetch with an on-disk cache. Used by the eval harness only.

Owns: HTTP requests to sec.gov / data.sec.gov, the SEC User-Agent and rate
limit, and a response cache keyed by sha256(url). It holds no financial
logic: it returns raw bytes and parsed JSON, never a FinancialValue.

It must never hardcode or log the User-Agent (it carries a contact email),
and error messages carry the URL only, never a response body.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

USER_AGENT_ENV = "SEC_USER_AGENT"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"

_TIMEOUT_S = 60

Opener = Callable[[urllib.request.Request], bytes]


class SourceError(Exception):
    """A fetch or parse failure. The message names the URL, never the body."""


@dataclass(frozen=True, slots=True)
class Filing:
    cik: str  # 10-digit, zero-padded
    accession: str  # with dashes, e.g. "0000320193-23-000106"
    form: str  # "10-K"
    filing_date: str  # ISO date
    report_date: str  # ISO date (period end)
    primary_document: str


def _urlopen(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        return response.read()


def _cik10(cik: str | int) -> str:
    return f"{int(cik):010d}"


class EdgarClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Path,
        min_interval_s: float = 0.15,
        *,
        opener: Opener = _urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent.strip():
            raise SourceError(f"{USER_AGENT_ENV} is empty; set it to 'finance-copilot <email>'")
        self._user_agent = user_agent
        self._cache_dir = Path(cache_dir)
        self._min_interval_s = min_interval_s
        self._opener = opener
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    @classmethod
    def from_env(cls, cache_dir: Path, **kwargs: Any) -> EdgarClient:
        user_agent = os.environ.get(USER_AGENT_ENV, "")
        if not user_agent.strip():
            raise SourceError(
                f"{USER_AGENT_ENV} is not set. The SEC requires a descriptive User-Agent: "
                f"set {USER_AGENT_ENV}='finance-copilot <your contact email>'"
            )
        return cls(user_agent, cache_dir, **kwargs)

    def cik_for_ticker(self, ticker: str) -> str:
        table = self._json(TICKERS_URL)
        wanted = ticker.strip().upper()
        try:
            for row in table.values():
                if str(row["ticker"]).upper() == wanted:
                    return _cik10(row["cik_str"])
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            raise SourceError(f"unexpected shape in {TICKERS_URL}") from e
        raise SourceError(f"ticker {ticker!r} not found in {TICKERS_URL}")

    def annual_filings(self, cik: str) -> list[Filing]:
        """Every 10-K (not 10-K/A) for the CIK, newest filing first."""
        cik10 = _cik10(cik)
        url = SUBMISSIONS_URL.format(name=f"CIK{cik10}.json")
        data = self._json(url)
        try:
            recent = data["filings"]["recent"]
            older = [f["name"] for f in data["filings"].get("files", [])]
        except (KeyError, TypeError) as e:
            raise SourceError(f"unexpected shape in {url}") from e
        filings = self._tenks(cik10, recent, url)
        for name in older:
            page_url = SUBMISSIONS_URL.format(name=name)
            filings.extend(self._tenks(cik10, self._json(page_url), page_url))
        return sorted(filings, key=lambda f: f.filing_date, reverse=True)

    def document(self, filing: Filing) -> bytes:
        """The filing's primary HTML document."""
        url = ARCHIVE_URL.format(
            cik_int=int(filing.cik),
            accession=filing.accession.replace("-", ""),
            document=urllib.parse.quote(filing.primary_document),
        )
        return self._get(url)

    def company_facts(self, cik: str) -> dict:
        return self._json(FACTS_URL.format(cik10=_cik10(cik)))

    @staticmethod
    def _tenks(cik10: str, page: dict, url: str) -> list[Filing]:
        try:
            columns = zip(
                page["form"],
                page["accessionNumber"],
                page["filingDate"],
                page["reportDate"],
                page["primaryDocument"],
                strict=True,
            )
            return [
                Filing(cik10, accession, form, filed, reported, document)
                for form, accession, filed, reported, document in columns
                if form == "10-K"
            ]
        except (KeyError, TypeError, ValueError) as e:
            raise SourceError(f"unexpected shape in {url}") from e

    def _json(self, url: str) -> Any:
        body = self._get(url)
        try:
            return json.loads(body)
        except ValueError as e:
            self._cache_path(url).unlink(missing_ok=True)
            raise SourceError(f"invalid JSON from {url}") from e

    def _cache_path(self, url: str) -> Path:
        return self._cache_dir / hashlib.sha256(url.encode()).hexdigest()

    def _get(self, url: str) -> bytes:
        path = self._cache_path(url)
        if path.exists():
            return path.read_bytes()
        if self._last_request is not None:
            wait = self._min_interval_s - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()
        request = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        try:
            body = self._opener(request)
        except (OSError, ValueError) as e:
            raise SourceError(f"request failed for {url}: {type(e).__name__}: {e}") from e
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return body

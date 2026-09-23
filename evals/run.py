"""XBRL eval CLI: run the pipeline on the corpus and score it against SEC truth.

Owns the corpus split, the filing lock, per-company orchestration (lock ->
fetch -> PDF -> analyze -> frozen truth -> score), the results file and the
Markdown summary. It runs the pipeline with no LLM and never feeds a truth
value back into it. A company that fails is recorded as `status=error` and
the run continues; errors are counted and printed, never dropped.

    uv run python -m evals.run [--split dev|holdout|all] [--bucket general|financial|all]
                               [--only TICKER ...] [--compare PATH] [--workers N]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pipeline

from evals.score import OutcomeRecord, score, summarize
from evals.truth_xbrl import read_truth, truth_for_filing, truth_path, write_truth
from fincopilot.sources.edgar import EdgarClient, Filing

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
CORPUS = EVALS / "corpus.csv"
LOCK = EVALS / "corpus.lock.json"
EXPOSED = EVALS / "exposed.json"  # holdout tickers whose results were viewed
TRUTH_DIR = EVALS / "truth"
RESULTS_DIR = EVALS / "results"
CACHE_DIR = EVALS / ".cache"
LOCAL_PDF_DIR = ROOT / "tests" / "fixtures" / "real"
FILED_BY = "2026-06-30"

_FILE_YEAR = re.compile(r"(?:fy)?(\d{2}|\d{4})$")


def split_for(ticker: str) -> str:
    """Deterministic ~30% holdout. Never hand-edited."""
    return "holdout" if int(hashlib.sha256(ticker.encode()).hexdigest(), 16) % 10 < 3 else "dev"


def read_corpus(path: Path = CORPUS) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fiscal_year_of(file_name: str) -> int:
    """`apple_10k_2023.pdf` -> 2023, `microsoft_fy24.pdf` -> 2024."""
    match = _FILE_YEAR.search(Path(file_name).stem.lower())
    if match is None:
        raise ValueError(f"no fiscal year at the end of {file_name!r}")
    year = int(match.group(1))
    return year + 2000 if year < 100 else year


def select_filing(filings: list[Filing], local_pdf: str) -> Filing:
    """The 10-K a local PDF is (reportDate year = file-name year), else the newest filed by
    FILED_BY. `filings` is newest first, as `EdgarClient.annual_filings` returns it."""
    if local_pdf:
        year = str(fiscal_year_of(local_pdf))
        found = [f for f in filings if f.report_date[:4] == year]
        if len(found) != 1:
            raise ValueError(f"{len(found)} 10-Ks have a {year} reportDate for {local_pdf!r}")
        return found[0]
    for f in filings:
        if f.filing_date <= FILED_BY:
            return f
    raise ValueError(f"no 10-K filed on or before {FILED_BY}")


def read_lock(path: Path = LOCK) -> dict[str, Filing]:
    if not path.exists():
        return {}
    return {t: Filing(**f) for t, f in json.loads(path.read_text(encoding="utf-8")).items()}


def write_lock(lock: dict[str, Filing], path: Path = LOCK) -> None:
    payload = {t: asdict(f) for t, f in lock.items()}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def locked_filing(
    ticker: str, local_pdf: str, lock: dict[str, Filing], client: EdgarClient, path: Path = LOCK
) -> Filing:
    """Read the lock; select and record only on the first run for a ticker."""
    if ticker in lock:
        return lock[ticker]
    filing = select_filing(client.annual_filings(client.cik_for_ticker(ticker)), local_pdf)
    lock[ticker] = filing
    write_lock(lock, path)
    return filing


def _prepare(row: dict[str, str], lock: dict[str, Filing], client: EdgarClient) -> dict:
    """Network stage, run serially (one rate-limited client). Returns the job for _analyze."""
    ticker, local_pdf = row["ticker"], row["local_pdf"]
    filing = locked_filing(ticker, local_pdf, lock, client)
    tpath = truth_path(TRUTH_DIR, ticker, filing.accession)
    if not tpath.exists():
        truth, notes = truth_for_filing(client.company_facts(filing.cik), filing.accession)
        write_truth(TRUTH_DIR, ticker, filing.accession, truth, notes)
    local = LOCAL_PDF_DIR / local_pdf if local_pdf else None
    if local is not None and local.exists():
        pdf = local
    else:
        pdf = CACHE_DIR / "pdf" / f"{filing.accession}.pdf"
        if not pdf.exists():
            from fincopilot.sources.render import html_to_pdf

            base = (
                f"https://www.sec.gov/Archives/edgar/data/{int(filing.cik)}/"
                f"{filing.accession.replace('-', '')}/"
            )
            rendered = html_to_pdf(client.document(filing), base_url=base)
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(rendered)
    return {"ticker": ticker, "accession": filing.accession, "pdf": str(pdf), "truth": str(tpath)}


def _analyze(job: dict) -> list[dict]:
    """CPU stage; safe in a worker process. Deterministic, no LLM."""
    truth, _ = read_truth(Path(job["truth"]))
    result = pipeline.analyze(Path(job["pdf"]).read_bytes())
    records = score(result, truth, ticker=job["ticker"], accession=job["accession"])
    return [asdict(r) for r in records]


def _git_sha() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def run(rows: list[dict[str, str]], workers: int, client: EdgarClient) -> tuple[list, list]:
    """(companies, records). Every company ends as status ok or error."""
    lock = read_lock()
    companies: dict[str, dict] = {}
    jobs: list[dict] = []
    for row in rows:
        entry = {k: row[k] for k in ("ticker", "bucket", "sector", "local_pdf")}
        entry |= {"split": split_for(row["ticker"]), "status": "ok", "error": None}
        companies[row["ticker"]] = entry
        try:
            job = _prepare(row, lock, client)
        except Exception as exc:
            entry |= {"status": "error", "error": _error(exc)}
            print(f"  {row['ticker']:6} error  {entry['error']}", flush=True)
            continue
        entry |= {"accession": job["accession"], "pdf": Path(job["pdf"]).name}
        jobs.append(job)

    records: list[dict] = []

    def collect(job: dict, get: Callable[[], list[dict]]) -> None:
        entry = companies[job["ticker"]]
        try:
            recs = get()
        except Exception as exc:
            entry |= {"status": "error", "error": _error(exc)}
            print(f"  {job['ticker']:6} error  {entry['error']}", flush=True)
            return
        for r in recs:
            r["bucket"] = entry["bucket"]
        records.extend(recs)
        print(f"  {job['ticker']:6} ok     {len(recs)} records", flush=True)

    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [(job, pool.submit(_analyze, job)) for job in jobs]
            for job, fut in futures:
                collect(job, fut.result)
    else:
        for job in jobs:
            collect(job, lambda job=job: _analyze(job))
    return list(companies.values()), records


def _as_records(dicts: list[dict]) -> list[OutcomeRecord]:
    fields = OutcomeRecord.__slots__
    return [
        OutcomeRecord(
            **{k: tuple(v) if isinstance(v, list) else v for k, v in d.items() if k in fields}
        )
        for d in dicts
    ]


def read_exposed(path: Path = EXPOSED) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def build_report(
    companies: list[dict],
    records: list[dict],
    *,
    split: str,
    bucket: str,
    only: list[str],
    exposed: dict[str, str],
) -> dict:
    """Totals overall and per bucket: financials are reported separately, never blended.

    A holdout company whose results were looked at is `exposed`: it is kept out of the
    headline totals and summarised on its own, so the holdout number stays unseen."""
    hidden = {c["ticker"] for c in companies if c["split"] == "holdout" and c["ticker"] in exposed}
    for c in companies:
        c["exposed"] = exposed[c["ticker"]] if c["ticker"] in hidden else None
    headline = [r for r in records if r["ticker"] not in hidden]
    summary = {"all": summarize(_as_records(headline))}
    for b in sorted({c["bucket"] for c in companies}):
        summary[b] = summarize(_as_records([r for r in headline if r["bucket"] == b]))
    if hidden:
        summary["exposed"] = summarize(_as_records([r for r in records if r["ticker"] in hidden]))
    return {
        "split": split,
        "bucket": bucket,
        "only": only,
        "git_sha": _git_sha(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "errors": sum(c["status"] == "error" for c in companies),
        "exposed": sorted(hidden),
        "companies": companies,
        "summary": summary,
        "records": records,
    }


_TOTAL_COLS = (
    "correct", "wrong", "withheld", "unverified", "sign_mismatch", "wrong_period",
    "precision", "coverage", "wrong_rate",
)  # fmt: skip


def _row(cells: list[object]) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _table(title: str, rows: dict[str, dict]) -> list[str]:
    out = [_row([title, *_TOTAL_COLS]), _row(["---"] * (len(_TOTAL_COLS) + 1))]
    out += [_row([k, *(v[c] for c in _TOTAL_COLS)]) for k, v in rows.items()]
    return out


def markdown(report: dict) -> str:
    s = report["summary"]
    lines = [f"# XBRL eval: split={report['split']} bucket={report['bucket']}", ""]
    lines += [f"git {report['git_sha']} at {report['timestamp']}", "", "## Totals", ""]
    lines += [*_table("scope", {k: v["totals"] for k, v in s.items()}), ""]
    if report["exposed"]:
        lines += [
            f"exposed (holdout, results already viewed; not in all/general/financial): "
            f"{', '.join(report['exposed'])}",
            "",
        ]
    lines += ["## Per concept (all buckets), by wrong desc", ""]
    per_concept = sorted(s["all"]["per_concept"].items(), key=lambda kv: -kv[1]["wrong"])
    lines += [*_table("concept", dict(per_concept)), ""]
    lines += ["## Per filing", "", *_table("filing", s["all"]["per_filing"]), ""]
    wrong = [r for r in report["records"] if r["outcome"] == "wrong"]
    head = ("ticker", "concept", "year", "app", "truth", "sub", "row label", "page")
    lines += [f"## Wrong values ({len(wrong)})", "", _row(head), _row(["---"] * len(head))]
    lines += [
        _row(
            [
                *(r[k] for k in ("ticker", "concept", "end_year", "app_value")),
                " / ".join(r["truth_values"]),
                r["sub"],
                r["row_label"],
                r["page"],
            ]
        )
        for r in wrong
    ]
    errors = [c for c in report["companies"] if c["status"] == "error"]
    lines += ["", f"## Errors ({len(errors)})", ""]
    lines += [f"- {c['ticker']}: {c['error']}" for c in errors] or ["none"]
    return "\n".join(lines) + "\n"


def compare(new: dict, old: dict) -> tuple[list[str], bool]:
    """(delta lines, regressed). Regressed = wrong went up or precision fell in any scope."""
    lines, regressed = [], False
    for scope, summary in new["summary"].items():
        if scope not in old["summary"]:
            lines.append(f"{scope}: not in the compared file")
            continue
        a, b = old["summary"][scope]["totals"], summary["totals"]
        deltas = [f"{k} {a[k]} -> {b[k]}" for k in _TOTAL_COLS if a[k] != b[k]]
        lines.append(f"{scope}: " + ("; ".join(deltas) if deltas else "no change"))
        if b["wrong"] > a["wrong"]:
            regressed = True
        if "n/a" not in (a["precision"], b["precision"]) and Decimal(b["precision"]) < Decimal(
            a["precision"]
        ):
            regressed = True
    return lines, regressed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__.split("\n")[0])
    ap.add_argument("--split", choices=("dev", "holdout", "all"), default="dev")
    ap.add_argument("--bucket", choices=("general", "financial", "all"), default="all")
    ap.add_argument("--only", nargs="+", metavar="TICKER", default=[])
    ap.add_argument("--compare", type=Path, metavar="PATH")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")  # row labels are untrusted PDF text

    corpus = read_corpus()
    unknown = sorted({t.upper() for t in args.only} - {r["ticker"] for r in corpus})
    if unknown:
        ap.error(f"not in {CORPUS.name}: {', '.join(unknown)}")
    splits = [split_for(r["ticker"]) for r in corpus]
    print(f"corpus split: dev {splits.count('dev')}, holdout {splits.count('holdout')}")
    rows = [
        r
        for r in corpus
        if args.split in ("all", split_for(r["ticker"]))
        and args.bucket in ("all", r["bucket"])
        and (not args.only or r["ticker"] in {t.upper() for t in args.only})
    ]
    print(f"running {len(rows)} companies: {' '.join(r['ticker'] for r in rows)}", flush=True)

    client = EdgarClient.from_env(CACHE_DIR / "http")
    companies, records = run(rows, args.workers, client)
    report = build_report(
        companies,
        records,
        split=args.split,
        bucket=args.bucket,
        only=args.only,
        exposed=read_exposed(),
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"latest_{args.split}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print()
    print(markdown(report))
    print(f"wrote {out}; errors: {report['errors']}/{len(companies)}")

    if args.compare:
        old = json.loads(args.compare.read_text(encoding="utf-8"))
        lines, regressed = compare(report, old)
        print(f"\n## Compare vs {args.compare}\n")
        print("\n".join(lines))
        if regressed:
            print("REGRESSION: wrong increased or precision fell")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

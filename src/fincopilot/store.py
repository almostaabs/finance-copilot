"""Phase 11: SQLite persistence. Spec 11.

Deliberately thin. Five tables, stdlib sqlite3, Decimal stored as text so
nothing is rounded on the way in or out. The PDF itself is never stored:
only its SHA-256, so a re-upload can be recognised.

`questions` exists for the P1 document Q&A feature and is never written here.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from fincopilot.types import AnalysisResult, Insight, Narrative

_SCHEMA = """
create table if not exists documents (
    document_id text primary key,
    name        text not null,
    sha256      text not null,
    size_bytes  integer not null,
    basis       text not null,
    periods     text not null,
    analyzed_at text not null
);
create table if not exists financial_values (
    document_id            text not null references documents(document_id) on delete cascade,
    concept                text not null,
    period                 integer not null,
    value                  text not null,
    currency               text not null,
    extraction_confidence  text not null,
    analytical_confidence  text not null,
    ref_id                 text,
    source_page            integer,
    source_label           text,
    derived_from           text,
    primary key (document_id, concept, period)
);
create table if not exists calculated_metrics (
    document_id           text not null references documents(document_id) on delete cascade,
    name                  text not null,
    period                integer not null,
    value                 text not null,
    unit                  text not null,
    analytical_confidence text not null,
    primary key (document_id, name, period)
);
create table if not exists insights (
    document_id text not null references documents(document_id) on delete cascade,
    position    integer not null,
    kind        text not null,
    text        text not null,
    cites       text not null,
    model       text not null,
    primary key (document_id, position)
);
create table if not exists questions (
    document_id text not null references documents(document_id) on delete cascade,
    asked_at    text not null,
    question    text not null,
    answer      text
);
"""


@dataclass(frozen=True, slots=True)
class DocumentRow:
    document_id: str
    name: str
    sha256: str
    size_bytes: int
    basis: str
    periods: tuple[int, ...]
    analyzed_at: str


@dataclass(frozen=True, slots=True)
class ValueRow:
    concept: str
    period: int
    value: str
    currency: str
    extraction_confidence: str
    analytical_confidence: str
    ref_id: str | None
    source_page: int | None
    source_label: str | None
    derived_from: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricRow:
    name: str
    period: int
    value: str
    unit: str
    analytical_confidence: str


def _display_name(name: str) -> str:
    """User filenames are display text only. Strip every path component."""
    base = PureWindowsPath(PurePosixPath(name).name).name
    return base or "upload.pdf"


class Store:
    def __init__(self, path: Path | str) -> None:
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("pragma foreign_keys = on")
        self.conn.executescript(_SCHEMA)  # raises DatabaseError on a non-sqlite file

    def close(self) -> None:
        self.conn.close()

    # --- write ------------------------------------------------------------

    def save(self, result: AnalysisResult, *, name: str, data: bytes) -> None:
        ordered = getattr(result.periods, "ordered", ())
        periods = ",".join(str(p.end_year) for p in ordered)
        with self.conn:
            self.conn.execute("delete from documents where document_id = ?", (result.document_id,))
            self.conn.execute(
                "insert into documents values (?,?,?,?,?,?,?)",
                (
                    result.document_id,
                    _display_name(name),
                    hashlib.sha256(data).hexdigest(),
                    len(data),
                    result.basis.value,
                    periods,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
            self.conn.executemany(
                "insert into financial_values values (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        result.document_id,
                        v.concept.value,
                        v.period.end_year,
                        str(v.value),
                        v.currency,
                        v.extraction_confidence.value,
                        v.analytical_confidence.value,
                        v.cell.ref.ref_id if v.cell else None,
                        v.source_page if v.cell else None,
                        v.source_label if v.cell else None,
                        ",".join(v.derived_from) if v.derived_from else None,
                    )
                    for v in result.values
                ],
            )
            self.conn.executemany(
                "insert into calculated_metrics values (?,?,?,?,?,?)",
                [
                    (
                        result.document_id,
                        m.name,
                        m.period.end_year,
                        str(m.value),
                        m.unit.value,
                        m.analytical_confidence.value,
                    )
                    for m in result.metrics
                ],
            )

    def save_narrative(self, document_id: str, narrative: Narrative) -> None:
        rows = [(document_id, 0, "summary", narrative.summary, "", narrative.model)]
        rows += [
            (document_id, i + 1, "insight", ins.text, ",".join(ins.cites), narrative.model)
            for i, ins in enumerate(narrative.insights)
        ]
        with self.conn:
            self.conn.execute("delete from insights where document_id = ?", (document_id,))
            self.conn.executemany("insert into insights values (?,?,?,?,?,?)", rows)

    def delete(self, document_id: str) -> None:
        with self.conn:
            self.conn.execute("delete from documents where document_id = ?", (document_id,))

    # --- read -------------------------------------------------------------

    def list_documents(self) -> list[DocumentRow]:
        rows = self.conn.execute("select * from documents order by analyzed_at desc").fetchall()
        return [
            DocumentRow(
                r[0], r[1], r[2], r[3], r[4], tuple(int(p) for p in r[5].split(",") if p), r[6]
            )
            for r in rows
        ]

    def load_values(self, document_id: str) -> list[ValueRow]:
        rows = self.conn.execute(
            "select concept, period, value, currency, extraction_confidence,"
            " analytical_confidence, ref_id, source_page, source_label, derived_from"
            " from financial_values where document_id = ? order by concept, period",
            (document_id,),
        ).fetchall()
        return [ValueRow(*r[:9], tuple(r[9].split(",")) if r[9] else ()) for r in rows]

    def load_metrics(self, document_id: str) -> list[MetricRow]:
        rows = self.conn.execute(
            "select name, period, value, unit, analytical_confidence from calculated_metrics"
            " where document_id = ? order by name, period",
            (document_id,),
        ).fetchall()
        return [MetricRow(*r) for r in rows]

    def load_narrative(self, document_id: str) -> Narrative | None:
        rows = self.conn.execute(
            "select kind, text, cites, model from insights where document_id = ? order by position",
            (document_id,),
        ).fetchall()
        if not rows:
            return None
        summary = next((r[1] for r in rows if r[0] == "summary"), "")
        insights = tuple(
            Insight(r[1], tuple(c for c in r[2].split(",") if c)) for r in rows if r[0] == "insight"
        )
        return Narrative(summary, insights, model=rows[0][3])

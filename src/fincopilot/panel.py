"""The hand-built Results panel: KPI cards and the red-flag grid.

Streamlit's own widgets cannot carry the motion or the density this needs, so
the panel is one self-contained HTML document rendered in a component frame.
It has no external dependencies: no CDN, no font download, no network. The
product is local-first and the front end must stay that way.

Nothing here computes. It receives rows that views.py already built from the
analysis, escapes every string, and draws them.
"""

from __future__ import annotations

import html
from typing import Any

from fincopilot import views
from fincopilot.charts import (
    GRID,
    INK,
    MUTED,
    NEGATIVE,
    POSITIVE,
    PRIMARY,
    SURFACE,
    WARNING,
)

STAGGER_MS = 40  # each card enters just after the one before it


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def flag_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"fired": 0, "not_evaluated": 1, "clear": 2}
    return sorted(
        (
            {
                "rule": r["rule"],
                "status": r["status"],
                "word": views.STATUS_WORD.get(r["status"], r["status"]),
                "message": r["message"],
            }
            for r in rows
        ),
        key=lambda r: (order.get(r["status"], 9), r["rule"]),
    )


_STYLE = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:transparent;color:{INK};
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}}
.grid{{display:grid;gap:10px}}
/* min-width:0 on the items, and a 0 floor in minmax, so a long label cannot
   force a wider track and push the last card onto its own row. */
.kpis{{grid-template-columns:repeat(6,minmax(0,1fr))}}
.flags{{grid-template-columns:repeat(5,minmax(0,1fr))}}
@media (max-width:1180px){{
  .kpis{{grid-template-columns:repeat(3,minmax(0,1fr))}}
  .flags{{grid-template-columns:repeat(3,minmax(0,1fr))}}}}
@media (max-width:720px){{.kpis,.flags{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
.card{{border:1px solid {GRID};border-radius:13px;background:{SURFACE};padding:15px 16px;
  display:flex;flex-direction:column;position:relative;overflow:hidden;min-width:0;
  transition:border-color .18s ease,transform .18s ease,box-shadow .18s ease;
  animation:rise .34s cubic-bezier(.2,.7,.3,1) both}}
@keyframes rise{{from{{opacity:0;transform:translateY(9px)}}to{{opacity:1;transform:none}}}}
.card::before{{content:"";position:absolute;inset:0 0 auto 0;height:2px;background:{MUTED};
  opacity:.55}}
.card.ok::before{{background:{POSITIVE}}}
.card.low::before{{background:{WARNING}}}
.card.na::before{{background:{GRID}}}
.card.fired::before{{background:{NEGATIVE}}}
.card.clear::before{{background:{POSITIVE}}}
.card.not_evaluated::before{{background:{GRID}}}
.card:hover{{border-color:{PRIMARY};transform:translateY(-2px);
  box-shadow:0 8px 24px rgba(0,0,0,.45)}}
.card.na:hover,.card.not_evaluated:hover{{border-color:{MUTED};transform:none;box-shadow:none}}
.label{{font-size:.67rem;font-weight:700;letter-spacing:.11em;text-transform:uppercase;
  color:{MUTED};min-height:2.1em;line-height:1.15}}
.value{{font-size:clamp(1.25rem,1.9vw,1.75rem);font-weight:700;
  letter-spacing:-.03em;margin:7px 0 2px;
  font-variant-numeric:tabular-nums;
  font-family:ui-monospace,"SF Mono","Cascadia Mono","Segoe UI Mono","Roboto Mono",monospace}}
.na .value{{font-size:1.15rem;font-style:italic;font-weight:500;color:{MUTED};font-family:inherit}}
.delta{{font-size:.79rem;font-weight:600;font-variant-numeric:tabular-nums}}
.delta.positive{{color:{POSITIVE}}} .delta.negative{{color:{NEGATIVE}}}
.delta.neutral{{color:{MUTED}}}
.note{{font-size:.72rem;color:{MUTED};margin-top:auto;padding-top:7px;line-height:1.35}}
.state{{font-size:.65rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase}}
.fired .state{{color:{NEGATIVE}}} .clear .state{{color:{POSITIVE}}}
.not_evaluated .state{{color:{MUTED}}}
.rule{{font-size:.87rem;font-weight:600;margin:5px 0 0}}
.not_evaluated .rule{{color:{MUTED}}}
.why{{font-size:.74rem;color:{MUTED};margin-top:6px;line-height:1.4}}
@media (prefers-reduced-motion: reduce){{
  .card{{animation:none;transition:none}}
  .card:hover{{transform:none}}
}}
"""


def _delay(i: int) -> str:
    return f"animation-delay:{i * STAGGER_MS}ms"


def kpi_html(cards: list[views.Kpi]) -> str:
    """The KPI row: one card per headline ratio, entering in sequence."""
    items = "".join(
        f'<div class="card {_e(c.status)}" style="{_delay(i)}">'
        f'<div class="label">{_e(c.label)}</div>'
        f'<div class="value">{_e(c.value)}</div>'
        + (
            f'<div class="delta {_e(c.delta_reads)}">{_e(c.delta)} vs prior year</div>'
            if c.delta
            else ""
        )
        + f'<div class="note">{_e(c.note)}</div></div>'
        for i, c in enumerate(cards)
    )
    return f'<style>{_STYLE}</style><div class="grid kpis">{items}</div>'


def flag_html(rows: list[dict[str, Any]]) -> str:
    """The verdict grid: every rule as a card, fired ones first."""
    items = "".join(
        f'<div class="card {_e(f["status"])}" style="{_delay(i)}">'
        f'<div class="state">{_e(f["word"])}</div>'
        f'<div class="rule">{_e(f["rule"])}</div>'
        f'<div class="why">{_e(f["message"])}</div></div>'
        for i, f in enumerate(flag_payload(rows))
    )
    return f'<style>{_STYLE}</style><div class="grid flags">{items}</div>'

"""The hand-built Results panel. It draws what views.py produced and nothing else."""

from __future__ import annotations

from pathlib import Path

import pipeline
import pytest

from fincopilot import panel, views

GOLDEN_US = Path("tests/fixtures/golden_us.pdf")
HOSTILE = Path("tests/fixtures/hostile.pdf")


@pytest.fixture(scope="module")
def golden():
    return pipeline.analyze(GOLDEN_US.read_bytes())


@pytest.fixture(scope="module")
def hostile():
    return pipeline.analyze(HOSTILE.read_bytes())


def test_kpi_html_contains_a_card_per_metric_and_no_network_call(golden):
    cards = views.kpi_cards(golden)
    html = panel.kpi_html(cards)
    assert html.count('class="card') == len(cards)
    for token in ("http://", "https://", "//cdn", "@import"):
        assert token not in html


def test_flag_html_puts_fired_rules_first(hostile):
    rows = views.red_flag_rows(hostile)
    payload = panel.flag_payload(rows)
    statuses = [f["status"] for f in payload]
    assert statuses == sorted(statuses, key=lambda s: {"fired": 0, "not_evaluated": 1}.get(s, 2))
    assert len(payload) == len(rows)


def test_panel_escapes_document_text(hostile):
    html = panel.flag_html(views.red_flag_rows(hostile)) + panel.kpi_html(views.kpi_cards(hostile))
    assert "<script>alert" not in html
    for row in views.red_flag_rows(hostile):
        assert "<" not in row["message"] or "&lt;" in html


def test_motion_is_optional():
    """Cards enter in sequence, but a reader who asked for less motion gets none."""
    assert "prefers-reduced-motion" in panel._STYLE
    assert "animation:none" in panel._STYLE


def test_cards_enter_in_sequence(golden):
    html = panel.kpi_html(views.kpi_cards(golden))
    assert "animation-delay:0ms" in html
    assert f"animation-delay:{panel.STAGGER_MS}ms" in html


def test_unavailable_cards_keep_their_reason(hostile):
    html = panel.kpi_html(views.kpi_cards(hostile))
    assert 'class="card na"' in html and "N/A" in html

from decimal import Decimal

import pytest

from fincopilot.types import Unavailable, UnavailableReason, is_unavailable


def test_unavailable_carries_reason_detail_and_refs():
    u = Unavailable(
        reason=UnavailableReason.MISSING_INPUT,
        detail="equity unmapped",
        refs=("page_12_table_1_row_4",),
    )
    assert u.reason is UnavailableReason.MISSING_INPUT
    assert u.detail == "equity unmapped"
    assert u.refs == ("page_12_table_1_row_4",)
    assert u.cause is None


def test_unavailable_is_frozen():
    u = Unavailable(UnavailableReason.AMBIGUOUS, "two columns parse to 2024")
    with pytest.raises(AttributeError):
        u.detail = "something else"


def test_unavailable_never_equals_a_number():
    u = Unavailable(UnavailableReason.DIVISION_BY_ZERO, "revenue is zero")
    assert u != 0
    assert u != Decimal(0)
    assert u is not None


def test_root_walks_the_cause_chain_to_the_original_failure():
    root = Unavailable(UnavailableReason.NOT_LOCATED, "balance sheet not found on any page")
    mid = Unavailable(UnavailableReason.MISSING_INPUT, "equity unmapped", cause=root)
    top = Unavailable(UnavailableReason.MISSING_INPUT, "ROE needs equity", cause=mid)

    assert top.root() is root
    assert root.root() is root


def test_is_unavailable_discriminates():
    assert is_unavailable(Unavailable(UnavailableReason.CONFLICT, "two rows claim revenue"))
    assert not is_unavailable(Decimal("12450.00"))
    assert not is_unavailable(0)

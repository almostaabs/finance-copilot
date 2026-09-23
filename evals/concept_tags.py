"""Which SEC XBRL tags are ground truth for each canonical concept.

Owns the concept -> us-gaap tag table used by the eval. Every tag set lists
names for the same line item only; it must never widen a concept to a
different line item to raise a score. A concept missing here is never scored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fincopilot.types import CanonicalConcept as C


@dataclass(frozen=True, slots=True)
class ConceptTruthSpec:
    tags: tuple[str, ...]  # all accepted; first is preferred
    kind: Literal["duration", "instant"]
    sign_agnostic: bool


def _d(*tags: str, sign_agnostic: bool = False) -> ConceptTruthSpec:
    return ConceptTruthSpec(tags, "duration", sign_agnostic)


def _i(*tags: str) -> ConceptTruthSpec:
    return ConceptTruthSpec(tags, "instant", False)


CONCEPT_TAGS: dict[C, ConceptTruthSpec] = {
    C.REVENUE: _d(
        "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"
    ),
    C.COGS: _d("CostOfRevenue", "CostOfGoodsAndServicesSold", sign_agnostic=True),
    C.GROSS_PROFIT: _d("GrossProfit"),
    C.OPERATING_INCOME: _d("OperatingIncomeLoss"),
    C.D_AND_A: _d(
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ),
    C.NET_INCOME: _d("NetIncomeLoss"),
    C.TOTAL_ASSETS: _i("Assets"),
    C.CURRENT_ASSETS: _i("AssetsCurrent"),
    C.CASH: _i("CashAndCashEquivalentsAtCarryingValue"),
    C.TOTAL_LIABILITIES: _i("Liabilities"),
    C.CURRENT_LIABILITIES: _i("LiabilitiesCurrent"),
    C.SHORT_TERM_BORROWINGS: _i("ShortTermBorrowings", "DebtCurrent"),
    C.LONG_TERM_BORROWINGS: _i("LongTermDebtNoncurrent"),
    C.EQUITY: _i(
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    C.OPERATING_CASH_FLOW: _d("NetCashProvidedByUsedInOperatingActivities"),
    C.CAPEX: _d("PaymentsToAcquirePropertyPlantAndEquipment", sign_agnostic=True),
}

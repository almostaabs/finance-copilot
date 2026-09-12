"""US-GAAP fixture: consolidated only, $ in millions.

Three periods on operations and cash flows, two on the balance sheet -- the
standard 10-K shape.

Intended page layout (page 1 is the cover):
  1       cover
  2-25    filler (24 pages)
  26      Consolidated Statements of Operations
  27      Consolidated Balance Sheets
  28      Consolidated Statements of Cash Flows
  29-34   filler (6 pages)
"""

from tests.fixtures.build_fixtures import ReportSpec, StatementBlock

_OPERATIONS = StatementBlock(
    heading="Consolidated Statements of Operations",
    caption="(In millions, except per share data)",
    header=("", "2024", "2023", "2022"),
    rows=(
        ("Net sales", "8,420.0", "7,650.0", "6,980.0"),
        ("Cost of sales", "5,180.0", "4,790.0", "4,420.0"),
        ("Gross profit", "3,240.0", "2,860.0", "2,560.0"),
        ("Research and development", "780.0", "690.0", "620.0"),
        ("Selling, general and administrative", "1,120.0", "1,040.0", "980.0"),
        ("Depreciation and amortization", "410.0", "380.0", "350.0"),
        ("Operating income", "930.0", "750.0", "610.0"),
        ("Interest expense", "95.0", "88.0", "82.0"),
        ("Income before income taxes", "835.0", "662.0", "528.0"),
        ("Provision for income taxes", "192.0", "152.0", "121.0"),
        ("Net income", "643.0", "510.0", "407.0"),
    ),
)

_BALANCE = StatementBlock(
    heading="Consolidated Balance Sheets",
    caption="(In millions)",
    header=("", "2024", "2023"),
    rows=(
        ("Cash and cash equivalents", "1,180.0", "960.0"),
        ("Accounts receivable, net", "1,340.0", "1,210.0"),
        ("Inventories", "890.0", "820.0"),
        ("Total current assets", "3,410.0", "2,990.0"),
        ("Property and equipment, net", "2,760.0", "2,540.0"),
        ("Goodwill", "1,420.0", "1,420.0"),
        ("Total assets", "7,590.0", "6,950.0"),
        ("Accounts payable", "980.0", "910.0"),
        ("Short-term debt", "320.0", "400.0"),
        ("Total current liabilities", "1,300.0", "1,310.0"),
        ("Long-term debt", "1,850.0", "1,980.0"),
        ("Total liabilities", "3,150.0", "3,290.0"),
        ("Total stockholders' equity", "4,440.0", "3,660.0"),
        ("Total liabilities and stockholders' equity", "7,590.0", "6,950.0"),
    ),
)

_CASH_FLOWS = StatementBlock(
    heading="Consolidated Statements of Cash Flows",
    caption="(In millions)",
    header=("", "2024", "2023", "2022"),
    rows=(
        ("Net cash provided by operating activities", "1,210.0", "1,020.0", "880.0"),
        ("Purchases of property and equipment", "(540.0)", "(480.0)", "(430.0)"),
        ("Net cash used in investing activities", "(610.0)", "(545.0)", "(470.0)"),
        ("Net cash used in financing activities", "(380.0)", "(330.0)", "(295.0)"),
        ("Net increase in cash and cash equivalents", "220.0", "145.0", "115.0"),
    ),
)

GOLDEN_US = ReportSpec(
    title="Meridian Systems, Inc.",
    subtitle="Annual Report on Form 10-K for the fiscal year ended December 31, 2024",
    metadata_title="Meridian Systems 10-K 2024",
    leading_filler_pages=24,
    between_filler_pages=0,
    trailing_filler_pages=6,
    blocks=(_OPERATIONS, _BALANCE, _CASH_FLOWS),
)

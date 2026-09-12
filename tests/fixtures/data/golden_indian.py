"""Ind-AS fixture: two periods, Rs. in crore, consolidated and standalone.

Intended page layout (page 1 is the cover):
  1       cover
  2-40    filler (39 pages)
  41      Consolidated Statement of Profit and Loss
  42      Consolidated Balance Sheet
  43      Consolidated Statement of Cash Flows
  44      Standalone Statement of Profit and Loss
  45      Standalone Balance Sheet
  46      Standalone Statement of Cash Flows
  47-60   filler (14 pages)

Standalone figures are deliberately DIFFERENT from consolidated, so a test
that silently picks the wrong scope fails on the numbers, not just a label.
"""

from tests.fixtures.build_fixtures import ReportSpec, StatementBlock

_CONSOLIDATED_PL = StatementBlock(
    heading="Consolidated Statement of Profit and Loss",
    caption="(Rs. in crore)",
    header=("Particulars", "FY 2023-24", "FY 2022-23"),
    rows=(
        ("Revenue from operations", "12,450.00", "10,980.00"),
        ("Other income", "320.50", "280.00"),
        ("Total income", "12,770.50", "11,260.00"),
        ("Cost of materials consumed", "7,180.00", "6,420.00"),
        ("Employee benefits expense", "1,890.00", "1,720.00"),
        ("Depreciation and amortisation expense", "640.00", "580.00"),
        ("Other expenses", "1,120.00", "1,010.00"),
        ("Profit from operations", "1,940.50", "1,530.00"),
        ("Finance costs", "280.00", "250.00"),
        ("Profit before tax", "1,660.50", "1,280.00"),
        ("Tax expense", "415.00", "330.00"),
        ("Profit for the year", "1,245.50", "950.00"),
    ),
)

_CONSOLIDATED_BS = StatementBlock(
    heading="Consolidated Balance Sheet",
    caption="(Rs. in crore)",
    header=("Particulars", "As at 31 March 2024", "As at 31 March 2023"),
    rows=(
        ("Property, plant and equipment", "6,820.00", "6,240.00"),
        ("Other non-current assets", "1,150.00", "980.00"),
        ("Total non-current assets", "7,970.00", "7,220.00"),
        ("Inventories", "1,640.00", "1,480.00"),
        ("Trade receivables", "2,210.00", "1,950.00"),
        ("Cash and cash equivalents", "1,380.00", "1,120.00"),
        ("Other current assets", "420.00", "390.00"),
        ("Total current assets", "5,650.00", "4,940.00"),
        ("Total assets", "13,620.00", "12,160.00"),
        ("Equity share capital", "500.00", "500.00"),
        ("Other equity", "6,430.00", "5,480.00"),
        ("Total equity", "6,930.00", "5,980.00"),
        ("Long-term borrowings", "2,850.00", "2,640.00"),
        ("Other non-current liabilities", "640.00", "580.00"),
        ("Total non-current liabilities", "3,490.00", "3,220.00"),
        ("Short-term borrowings", "900.00", "820.00"),
        ("Trade payables", "1,760.00", "1,610.00"),
        ("Other current liabilities", "540.00", "530.00"),
        ("Total current liabilities", "3,200.00", "2,960.00"),
        ("Total liabilities", "6,690.00", "6,180.00"),
        ("Total equity and liabilities", "13,620.00", "12,160.00"),
    ),
)

_CONSOLIDATED_CF = StatementBlock(
    heading="Consolidated Statement of Cash Flows",
    caption="(Rs. in crore)",
    header=("Particulars", "FY 2023-24", "FY 2022-23"),
    rows=(
        ("Net cash generated from operating activities", "2,180.00", "1,760.00"),
        ("Purchase of property, plant and equipment", "(1,240.00)", "(1,080.00)"),
        ("Net cash used in investing activities", "(1,310.00)", "(1,150.00)"),
        ("Net cash used in financing activities", "(610.00)", "(520.00)"),
        ("Net increase in cash and cash equivalents", "260.00", "90.00"),
        ("Cash and cash equivalents at the end of the year", "1,380.00", "1,120.00"),
    ),
)

_STANDALONE_PL = StatementBlock(
    heading="Standalone Statement of Profit and Loss",
    caption="(Rs. in crore)",
    header=("Particulars", "FY 2023-24", "FY 2022-23"),
    rows=(
        ("Revenue from operations", "9,310.00", "8,240.00"),
        ("Other income", "410.00", "360.00"),
        ("Total income", "9,720.00", "8,600.00"),
        ("Cost of materials consumed", "5,420.00", "4,880.00"),
        ("Employee benefits expense", "1,280.00", "1,160.00"),
        ("Depreciation and amortisation expense", "470.00", "430.00"),
        ("Other expenses", "820.00", "760.00"),
        ("Profit from operations", "1,730.00", "1,370.00"),
        ("Finance costs", "210.00", "190.00"),
        ("Profit before tax", "1,520.00", "1,180.00"),
        ("Tax expense", "380.00", "305.00"),
        ("Profit for the year", "1,140.00", "875.00"),
    ),
)

_STANDALONE_BS = StatementBlock(
    heading="Standalone Balance Sheet",
    caption="(Rs. in crore)",
    header=("Particulars", "As at 31 March 2024", "As at 31 March 2023"),
    rows=(
        ("Total non-current assets", "6,140.00", "5,610.00"),
        ("Total current assets", "4,180.00", "3,720.00"),
        ("Total assets", "10,320.00", "9,330.00"),
        ("Total equity", "5,410.00", "4,690.00"),
        ("Long-term borrowings", "2,190.00", "2,080.00"),
        ("Short-term borrowings", "700.00", "640.00"),
        ("Total current liabilities", "2,340.00", "2,180.00"),
        ("Total liabilities", "4,910.00", "4,640.00"),
        ("Total equity and liabilities", "10,320.00", "9,330.00"),
    ),
)

_STANDALONE_CF = StatementBlock(
    heading="Standalone Statement of Cash Flows",
    caption="(Rs. in crore)",
    header=("Particulars", "FY 2023-24", "FY 2022-23"),
    rows=(
        ("Net cash generated from operating activities", "1,640.00", "1,380.00"),
        ("Purchase of property, plant and equipment", "(890.00)", "(810.00)"),
        ("Net cash used in investing activities", "(940.00)", "(870.00)"),
        ("Net cash used in financing activities", "(520.00)", "(430.00)"),
        ("Net increase in cash and cash equivalents", "180.00", "80.00"),
    ),
)

GOLDEN_INDIAN = ReportSpec(
    title="Bharat Industries Limited",
    subtitle="Integrated Annual Report 2023-24",
    metadata_title="Bharat Industries Limited Annual Report 2023-24",
    leading_filler_pages=39,
    between_filler_pages=0,
    trailing_filler_pages=14,
    blocks=(
        _CONSOLIDATED_PL,
        _CONSOLIDATED_BS,
        _CONSOLIDATED_CF,
        _STANDALONE_PL,
        _STANDALONE_BS,
        _STANDALONE_CF,
    ),
)

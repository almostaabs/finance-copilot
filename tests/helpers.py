"""Small constructors so tests read as behaviour, not as dataclass plumbing."""

from fincopilot.types import SourceRef, make_ref_id


def make_source_ref(
    *,
    page: int = 1,
    table_idx: int = 0,
    row_idx: int = 0,
    col_idx: int | None = None,
    row_label: str = "Revenue from operations",
    raw_text: str = "12,450.00",
    document_id: str = "doc-test",
) -> SourceRef:
    return SourceRef(
        ref_id=make_ref_id(page, table_idx, row_idx),
        document_id=document_id,
        page=page,
        table_idx=table_idx,
        row_idx=row_idx,
        col_idx=col_idx,
        row_label=row_label,
        raw_text=raw_text,
    )

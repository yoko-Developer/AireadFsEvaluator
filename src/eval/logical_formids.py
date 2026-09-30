import re
from typing import List

# 1 physical page may contain multiple logical statements.
# This table is a validation fixture for PDF 208, based on the manually confirmed truth.
# It intentionally does NOT modify ground-truth CSV files.
_LOGICAL_GT_BY_PDF_PAGE = {
    "208": {
        1: ["01_010_02", "01_010_02"],
        2: ["01_020_02", "01_030_02"],
        3: ["01_050_02"],
    }
}


def extract_pdf_number(name: str) -> str | None:
    """Extract the company/PDF number from either decoded or #U encoded file names."""
    # Current source names contain the company number immediately before a space + underscore.
    m = re.search(r"(\d+)\s+_(?:#U|墨)", name)
    if m:
        return str(int(m.group(1)))
    # Fallback for decoded names such as 株式会社208.
    m = re.search(r"株式会社\s*(\d+)", name)
    if m:
        return str(int(m.group(1)))
    return None


def logical_gt_formids(pdf_name: str, page_no: int, observed: List[str]) -> List[str]:
    """Return logical GT statements for a physical page, preserving duplicates."""
    pdf_no = extract_pdf_number(pdf_name)
    override = _LOGICAL_GT_BY_PDF_PAGE.get(pdf_no, {}).get(page_no)
    return list(override) if override is not None else list(observed)

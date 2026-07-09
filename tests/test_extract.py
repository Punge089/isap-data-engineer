"""Step 3 extractor tests — smoke test against the real committed raw files.

No mocking: PROJECT_SPEC.md's testing strategy (§10) calls for a smoke E2E
against the real committed raw files, so this runs the actual extractor and
checks the resulting staging CSVs against the row counts/boundaries
verified in reports/eda_cgd.txt and reports/eda_ocsc.txt.
"""

import csv
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

import extract
from extract import run_cgd, run_ocsc
from validate_structure import StructureValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING_DIR = REPO_ROOT / "staging"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module", autouse=True)
def run_extraction():
    run_cgd()
    run_ocsc()


def test_cgd_disbursement_row_count():
    rows = read_csv(STAGING_DIR / "cgd_disbursement.csv")
    assert len(rows) == 24


def test_cgd_total_row_not_present():
    rows = read_csv(STAGING_DIR / "cgd_disbursement.csv")
    names = [r["ministry_name"] for r in rows]
    codes = [r["ministry_code"] for r in rows]
    assert "รวม" not in names
    assert " " not in codes  # the total row's stray-space code must not leak in


def test_ocsc_workforce_row_count():
    rows = read_csv(STAGING_DIR / "ocsc_workforce.csv")
    # 1 grand total + 2 subtotals + 22 leaf categories, per reports/eda_ocsc.txt
    assert len(rows) == 25


def test_ocsc_every_row_has_hierarchy_level():
    rows = read_csv(STAGING_DIR / "ocsc_workforce.csv")
    assert len(rows) > 0
    levels = {r["hierarchy_level"] for r in rows}
    assert levels == {"0", "1", "2"}
    assert all(r["hierarchy_level"] != "" for r in rows)


def test_ocsc_preserves_dirty_whitespace():
    """Guard against someone later adding .strip() to extract.py —
    that's Step 4's job, not extraction's."""
    df = pd.read_csv(STAGING_DIR / "ocsc_workforce.csv")
    dirty_name = df[df["category_name"].str.contains("องค์กรอิสระ", na=False)]["category_name"].iloc[0]
    assert dirty_name != dirty_name.strip()


def test_run_cgd_raises_via_real_entry_point_on_mangled_structure(tmp_path, monkeypatch):
    """Step 7 integration check: proves extract.py's REAL entry point
    (run_cgd()) actually calls validate_cgd_structure() and stops before
    writing anything, not just that the validation function raises
    correctly in isolation (tests/test_validate_structure.py already
    covers that in isolation). Points extract.RAW_DIR at a fake directory
    containing a deliberately wrong sheet, using the real config/cgd.yaml
    unchanged, and calls the real run_cgd()."""
    fake_cgd_dir = tmp_path / "cgd"
    fake_cgd_dir.mkdir()
    wb = Workbook()
    wb.active.title = "totally wrong sheet name"
    wb.save(fake_cgd_dir / "mangled.xlsx")

    monkeypatch.setattr(extract, "RAW_DIR", tmp_path)

    staging_path = STAGING_DIR / "cgd_disbursement.csv"
    before = staging_path.read_bytes()

    with pytest.raises(StructureValidationError, match="not found"):
        extract.run_cgd()

    after = staging_path.read_bytes()
    assert before == after  # validation failed before extract_cgd()/write_csv() ever ran

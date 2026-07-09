"""Step 4 cleaner tests.

Row-count/whitespace/is_leaf checks run against the real committed staging
CSVs (Step 3's output), matching the smoke-E2E convention used in
tests/test_extract.py. The zero-budget edge case does NOT exist in the real
CGD data (verified: no ministry has budget_after_transfer == 0 in
staging/cgd_disbursement.csv), so that test uses a small fake row instead —
per PROJECT_SPEC.md §10's guidance to unit-test clean.py's pure functions
with a small fake table rather than only against real data.
"""

import csv
from pathlib import Path

import pandas as pd
import pytest

from clean import clean_cgd, clean_ocsc

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING_DIR = REPO_ROOT / "staging"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def cgd_raw_rows():
    return read_csv(STAGING_DIR / "cgd_disbursement.csv")


@pytest.fixture(scope="module")
def ocsc_raw_rows():
    return read_csv(STAGING_DIR / "ocsc_workforce.csv")


def test_cgd_unpivot_row_count(cgd_raw_rows):
    assert len(cgd_raw_rows) == 24  # sanity: Step 3's output hasn't drifted
    cleaned = clean_cgd(cgd_raw_rows)
    assert len(cleaned) == 72  # 24 ministries x 3 expense types


def test_cgd_is_leaf_consistent_per_expense_type(cgd_raw_rows):
    """Every row sharing the same expense_type_name must have the same
    is_leaf value. Guards against is_leaf being hardcoded independently
    in clean.py and (later) in Step 5's dim_expense_type seeding, which
    could silently drift out of sync."""
    cleaned = clean_cgd(cgd_raw_rows)
    df = pd.DataFrame(cleaned)
    assert df.groupby("expense_type_name")["is_leaf"].nunique().eq(1).all()


def test_cgd_is_leaf_correct_both_expense_types(cgd_raw_rows):
    cleaned = clean_cgd(cgd_raw_rows)
    leaf_types = {r["expense_type_name"] for r in cleaned if r["is_leaf"]}
    rollup_types = {r["expense_type_name"] for r in cleaned if not r["is_leaf"]}
    assert leaf_types == {"รายจ่ายประจำ", "รายจ่ายลงทุน"}
    assert rollup_types == {"รวม"}


def test_cgd_zero_budget_gives_null_not_inf_or_crash():
    fake_row = {
        "seq_no": "1",
        "ministry_name": "กระทรวงทดสอบ",
        "ministry_code": "99",
        "recurring_budget_after_transfer": "0",
        "recurring_allocated": "0",
        "recurring_spending_plan": "0",
        "recurring_po_reserved": "0",
        "recurring_disbursed": "0",
        "capital_budget_after_transfer": "100",
        "capital_allocated": "100",
        "capital_spending_plan": "0",
        "capital_po_reserved": "0",
        "capital_disbursed": "50",
        "total_budget_after_transfer": "100",
        "total_allocated": "100",
        "total_spending_plan": "0",
        "total_po_reserved": "0",
        "total_disbursed": "50",
    }
    cleaned = clean_cgd([fake_row])

    recurring_row = next(r for r in cleaned if r["expense_type_name"] == "รายจ่ายประจำ")
    assert recurring_row["disbursed_pct"] is None  # zero budget -> NULL, not inf/crash

    capital_row = next(r for r in cleaned if r["expense_type_name"] == "รายจ่ายลงทุน")
    assert capital_row["disbursed_pct"] == 50.0  # sanity: normal division still works fine


def test_ocsc_category_name_has_no_whitespace(ocsc_raw_rows):
    cleaned = clean_ocsc(ocsc_raw_rows)
    assert len(cleaned) == 25
    for r in cleaned:
        assert r["category_name"] == r["category_name"].strip()
    # the specific row Step 1's EDA found dirty must actually have been dirty going in
    assert any("องค์กรอิสระ" in r["category_name"] for r in cleaned)


def test_ocsc_is_leaf_matches_hierarchy_level(ocsc_raw_rows):
    cleaned = clean_ocsc(ocsc_raw_rows)
    for r in cleaned:
        assert r["is_leaf"] == (r["hierarchy_level"] == 2)
    assert sum(1 for r in cleaned if r["is_leaf"]) == 22  # 22 leaf categories


def test_ocsc_parent_category_still_plain_text_not_resolved(ocsc_raw_rows):
    """Locks in the Step 4/5 boundary: parent_category is text here, not a
    parent_category_key, because dim_personnel_category isn't populated
    until Step 5's loader runs."""
    cleaned = clean_ocsc(ocsc_raw_rows)
    grand_total = next(r for r in cleaned if r["hierarchy_level"] == 0)
    assert grand_total["parent_category"] is None

    leaf = next(r for r in cleaned if r["hierarchy_level"] == 2)
    assert isinstance(leaf["parent_category"], str)

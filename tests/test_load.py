"""Step 5 loader tests.

Runs the real loader against a scratch DuckDB file (not
warehouse/warehouse.duckdb — tests must not depend on or clobber the
warehouse a developer is looking at) and against the real committed
staging/*_clean.csv + raw/manifest.json, matching this project's
established smoke-E2E convention (tests/test_extract.py,
tests/test_clean.py). No mocking of the database: idempotency is a
property of the actual SQL constraints firing, not of load.py's Python
logic, so the proof has to run against a real DuckDB connection.
"""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

import load as load_module
from init_db import ensure_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
TABLES = [
    "dim_date",
    "dim_ministry",
    "dim_expense_type",
    "dim_personnel_category",
    "dim_source",
    "fact_disbursement",
    "fact_workforce_summary",
]


def row_counts(con: duckdb.DuckDBPyConnection) -> dict:
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


@pytest.fixture
def con(tmp_path):
    """A scratch warehouse file, not the real warehouse/warehouse.duckdb."""
    db_path = tmp_path / "test_warehouse.duckdb"
    connection = duckdb.connect(str(db_path))
    ensure_schema(connection)
    yield connection
    connection.close()


def test_thai_fiscal_year_be_cutover_direction():
    """Locks in which direction the Oct 1 fiscal-year cutover goes. The only
    real data point available (report_date 2026-07-03 -> FY2569, verified
    against reports/eda_cgd.txt's title text) is deep in mid-year and proves
    nothing about which side of Oct 1 the rollover lands on — this test
    exists because that boundary has never been checked against anything
    real.

    Direction chosen: the Thai government fiscal year is named for the
    calendar year in which it ENDS (30 กันยายน), not the one it starts in —
    e.g. "ปีงบประมาณ 2568" runs 1 ต.ค. 2567 - 30 ก.ย. 2568. So:
      - 2025-09-30 is the last day of the fiscal year that started
        2024-10-01 and ends 2025-09-30 (CE 2025) -> fiscal_year_be 2568.
      - 2025-10-01 is the first day of the NEXT fiscal year, which will end
        2026-09-30 (CE 2026) -> fiscal_year_be 2569, one BE year higher.
    If this direction were backwards, every CGD report published Oct-Dec
    would get tagged with the fiscal year that just ended instead of the
    one that just started.
    """
    assert load_module.thai_fiscal_year_be(date(2025, 9, 30)) == 2568
    assert load_module.thai_fiscal_year_be(date(2025, 10, 1)) == 2569


def test_loading_twice_gives_identical_row_counts(con):
    load_module.load_cgd(con)
    load_module.load_ocsc(con)
    first_run_counts = row_counts(con)

    load_module.load_cgd(con)
    load_module.load_ocsc(con)
    second_run_counts = row_counts(con)

    assert first_run_counts == second_run_counts
    # sanity: this isn't trivially true because everything is 0
    assert first_run_counts["fact_disbursement"] == 72
    assert first_run_counts["fact_workforce_summary"] == 25


def test_dim_expense_type_is_leaf_matches_clean_csv_exactly(con):
    load_module.load_cgd(con)

    clean_rows = load_module.read_csv(load_module.STAGING_DIR / "cgd_disbursement_clean.csv")
    expected = {r["expense_type_name"]: load_module.parse_bool(r["is_leaf"]) for r in clean_rows}

    actual = dict(
        con.execute("SELECT expense_type_name, is_leaf FROM dim_expense_type").fetchall()
    )
    assert actual == expected


def test_workforce_parent_category_key_resolves_or_is_null_only_for_grand_total(con):
    load_module.load_ocsc(con)

    rows = con.execute(
        "SELECT hierarchy_level, parent_category_key, personnel_category_key FROM fact_workforce_summary"
    ).fetchall()
    assert len(rows) == 25

    valid_keys = {
        r[0]
        for r in con.execute(
            "SELECT personnel_category_key FROM dim_personnel_category"
        ).fetchall()
    }

    for hierarchy_level, parent_category_key, _ in rows:
        if hierarchy_level == 0:
            assert parent_category_key is None
        else:
            assert parent_category_key is not None
            assert parent_category_key in valid_keys


def test_dim_date_fiscal_year_ce_always_matches_be_minus_543(con):
    load_module.load_cgd(con)
    load_module.load_ocsc(con)

    rows = con.execute("SELECT fiscal_year_be, fiscal_year_ce FROM dim_date").fetchall()
    assert len(rows) == 2  # one CGD row (report_date-keyed), one OCSC row (fiscal-year-keyed)
    for fiscal_year_be, fiscal_year_ce in rows:
        assert fiscal_year_ce == fiscal_year_be - 543


def test_dim_date_check_constraint_actually_rejects_bad_be_ce_pair(con):
    """Proves the CHECK constraint isn't just decoration: load.py's own
    correct math passing (previous test) doesn't prove the constraint
    would catch a wrong one."""
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """
            INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
            VALUES ('bad-test-key', NULL, 2569, 1111)
            """
        )


def test_two_cgd_manifest_entries_across_two_runs_produce_two_dim_source_rows(con, tmp_path, monkeypatch):
    """Step 7's downloader can now genuinely append a second CGD manifest
    entry. This proves load_manifest()'s fix (max() by report_date, not
    "whichever the dict comprehension keeps") actually results in TWO
    accumulated dim_source rows across two separate pipeline runs, not one
    entry silently overwriting the other's slot -- the exact bug flagged
    in HANDOFF.md since Step 5.
    """
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(load_module, "MANIFEST_PATH", manifest_path)

    # "Run 1": manifest has a single CGD entry, as if this were the very
    # first download.
    manifest_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "source": "CGD",
                        "source_url": "https://www.cgd.go.th/x",
                        "local_path": "raw/cgd/2026_06_05.xlsx",
                        "report_date": "2026-06-05",
                        "sha256": "hash-run-1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    load_module.load_dim_source(con, "CGD")

    # "Run 2": download.py has since appended a second, newer CGD entry --
    # note it's appended (existing entry untouched), not replacing it.
    manifest_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "source": "CGD",
                        "source_url": "https://www.cgd.go.th/x",
                        "local_path": "raw/cgd/2026_06_05.xlsx",
                        "report_date": "2026-06-05",
                        "sha256": "hash-run-1",
                    },
                    {
                        "source": "CGD",
                        "source_url": "https://www.cgd.go.th/x",
                        "local_path": "raw/cgd/2026_07_03.xlsx",
                        "report_date": "2026-07-03",
                        "sha256": "hash-run-2",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    load_module.load_dim_source(con, "CGD")

    rows = con.execute(
        "SELECT file_hash FROM dim_source WHERE agency = 'CGD' ORDER BY file_hash"
    ).fetchall()
    assert [r[0] for r in rows] == ["hash-run-1", "hash-run-2"]

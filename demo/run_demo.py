"""Interview demo script — NOT part of the pipeline.

Connects to the real warehouse/warehouse.duckdb (read-only — this script
never writes to it) and prints a sequence of labeled query results meant
to be run live and narrated over. See demo/DEMO_SCRIPT.md for the
walkthrough/talking points that go with each query below.

Run: python demo/run_demo.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

# Thai text needs UTF-8 out; some terminals (this one included) default to
# something narrower and would crash on print() otherwise.
sys.stdout.reconfigure(encoding="utf-8")

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 160)
pd.set_option("display.max_colwidth", 40)

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "warehouse" / "warehouse.duckdb"


def header(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def show(df: pd.DataFrame) -> None:
    print(df.to_string(index=False))


def query_a_row_counts(con: duckdb.DuckDBPyConnection) -> None:
    header("Query 1: row counts in every table right now")
    tables = [
        "dim_date", "dim_ministry", "dim_expense_type",
        "dim_personnel_category", "dim_source",
        "fact_disbursement", "fact_workforce_summary",
    ]
    rows = [(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in tables]
    show(pd.DataFrame(rows, columns=["table", "row_count"]))


def query_b_cgd_double_count(con: duckdb.DuckDBPyConnection) -> None:
    header("Query 2a: CGD -- naive SUM(disbursed) by ministry (NO is_leaf filter)")
    naive = con.execute("""
        SELECT m.ministry_name_th, SUM(f.disbursed) AS naive_sum_disbursed
        FROM fact_disbursement f
        JOIN dim_ministry m ON m.ministry_key = f.ministry_key
        GROUP BY m.ministry_name_th
        ORDER BY naive_sum_disbursed DESC
    """).fetchdf()
    show(naive)

    header("Query 2b: CGD -- correct SUM(disbursed) by ministry (WHERE is_leaf = true)")
    correct = con.execute("""
        SELECT m.ministry_name_th, SUM(f.disbursed) AS correct_sum_disbursed
        FROM fact_disbursement f
        JOIN dim_ministry m ON m.ministry_key = f.ministry_key
        JOIN dim_expense_type e ON e.expense_type_key = f.expense_type_key
        WHERE e.is_leaf = true
        GROUP BY m.ministry_name_th
        ORDER BY correct_sum_disbursed DESC
    """).fetchdf()
    show(correct)

    header("Query 2c: side by side -- the double-count as a real number, per ministry")
    merged = naive.merge(correct, on="ministry_name_th")
    merged["difference"] = merged["naive_sum_disbursed"] - merged["correct_sum_disbursed"]
    merged = merged.sort_values("difference", ascending=False)
    show(merged)

    naive_total = naive["naive_sum_disbursed"].sum()
    correct_total = correct["correct_sum_disbursed"].sum()
    print()
    print(f"GRAND TOTAL -- naive (no filter):        {naive_total:,.2f} ล้านบาท")
    print(f"GRAND TOTAL -- correct (is_leaf = true):  {correct_total:,.2f} ล้านบาท")
    print(f"naive / correct ratio:                    {naive_total / correct_total:.4f}")
    print("=> naive double-counts every ministry, because 'รวม' (total) IS")
    print("   recurring + capital added again, not a 3rd independent number.")


def query_c_ocsc_double_count(con: duckdb.DuckDBPyConnection) -> None:
    header("Query 3: OCSC -- naive vs correct SUM(headcount), reconciled against the grand total")

    naive_sum = con.execute("SELECT SUM(headcount) FROM fact_workforce_summary").fetchone()[0]
    correct_sum = con.execute(
        "SELECT SUM(headcount) FROM fact_workforce_summary WHERE is_leaf"
    ).fetchone()[0]
    grand_total_row = con.execute(
        "SELECT headcount FROM fact_workforce_summary WHERE hierarchy_level = 0"
    ).fetchone()[0]

    df = pd.DataFrame([
        {"metric": "naive SUM(headcount), no filter (over-counts grand total + subtotals + leaves)", "value": naive_sum},
        {"metric": "correct SUM(headcount) WHERE is_leaf = true", "value": correct_sum},
        {"metric": "grand_total_headcount row (hierarchy_level = 0)", "value": grand_total_row},
    ])
    show(df)
    print()
    print(f"naive / correct ratio: {naive_sum / correct_sum:.4f}  (~3x: grand total + 2 subtotals + 22 leaves, all summed together)")
    print(f"correct sum == grand total row exactly: {correct_sum == grand_total_row}")


def query_d_lineage(con: duckdb.DuckDBPyConnection) -> None:
    header("Query 4: dim_source -- lineage, every row traceable to an exact file")
    df = con.execute("""
        SELECT agency, file_name, LEFT(file_hash, 12) AS sha256_prefix, ingested_at
        FROM dim_source
        ORDER BY agency
    """).fetchdf()
    show(df)


def query_e_check_constraint(db_path: Path) -> None:
    header("Query 5: CHECK constraint enforcement -- live, against a COPY, never the real file")

    with tempfile.TemporaryDirectory() as tmp_dir:
        copy_path = Path(tmp_dir) / "warehouse_copy_for_demo.duckdb"
        shutil.copy2(db_path, copy_path)
        print(f"Copied {db_path.name} -> {copy_path} (scratch copy, deleted after this query)")

        con = duckdb.connect(str(copy_path))
        try:
            print("Attempting: INSERT INTO dim_date with fiscal_year_be=2570, fiscal_year_ce=1999")
            print("(should be 2570 - 543 = 2027, not 1999 -- deliberately wrong)")
            con.execute("""
                INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
                VALUES ('demo-bad-date', NULL, 2570, 1999)
            """)
            print("!! NO EXCEPTION RAISED -- this would be a bug, the CHECK constraint failed to fire !!")
        except duckdb.ConstraintException as e:
            print()
            print("Caught duckdb.ConstraintException, exactly as expected:")
            print(f"  {e}")
        finally:
            con.close()


def main() -> None:
    if not DB_PATH.exists():
        print(f"No warehouse found at {DB_PATH}. Run `python src/load.py` first.")
        sys.exit(1)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        query_a_row_counts(con)
        query_b_cgd_double_count(con)
        query_c_ocsc_double_count(con)
        query_d_lineage(con)
    finally:
        con.close()

    # Separate connection, separate (copied) file -- never touches the real one.
    query_e_check_constraint(DB_PATH)

    print()
    print("=" * 70)
    print("Demo complete.")
    print("=" * 70)


if __name__ == "__main__":
    main()

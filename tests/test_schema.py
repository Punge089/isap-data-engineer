"""Step 2 schema tests.

Each test builds a fresh in-memory DuckDB database from sql/schema.sql,
seeds the minimum dimension rows needed, then checks one thing the DDL is
supposed to guarantee: a constraint rejects bad data, or an is_leaf filter
produces the correct total. No file on disk is touched.
"""

from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = (REPO_ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")


@pytest.fixture
def con():
    connection = duckdb.connect(":memory:")
    connection.execute(SCHEMA_SQL)
    yield connection
    connection.close()


def seed_cgd(con):
    """One dim_date/dim_ministry/dim_source row + all 3 expense types.

    Returns (date_key, ministry_key, source_id, {expense_type_name: key}).
    """
    con.execute(
        """
        INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
        VALUES ('2026-07-03', DATE '2026-07-03', 2569, 2026)
        """
    )
    con.execute(
        """
        INSERT INTO dim_ministry (ministry_code, ministry_name_th, source_name_raw)
        VALUES ('08', 'กระทรวงคมนาคม', 'กระทรวงคมนาคม')
        """
    )
    con.execute(
        """
        INSERT INTO dim_expense_type (expense_type_name, is_leaf) VALUES
        ('รายจ่ายประจำ', true),
        ('รายจ่ายลงทุน', true),
        ('รวม', false)
        """
    )
    con.execute(
        """
        INSERT INTO dim_source (agency, file_name, ingested_at)
        VALUES ('CGD', '2026_07_03.xlsx', now())
        """
    )
    date_key = con.execute("SELECT date_key FROM dim_date").fetchone()[0]
    ministry_key = con.execute("SELECT ministry_key FROM dim_ministry").fetchone()[0]
    source_id = con.execute("SELECT source_id FROM dim_source").fetchone()[0]
    expense_keys = dict(
        con.execute("SELECT expense_type_name, expense_type_key FROM dim_expense_type").fetchall()
    )
    return date_key, ministry_key, source_id, expense_keys


def seed_ocsc(con):
    """One dim_date/dim_source row + grand total/subtotal/2 leaf categories.

    Returns (date_key, source_id, {category_name: key}).
    """
    con.execute(
        """
        INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
        VALUES ('FY2567', NULL, 2567, 2024)
        """
    )
    con.execute(
        """
        INSERT INTO dim_source (agency, file_name, ingested_at)
        VALUES ('OCSC', 'thaigovmanpower2567_4.xlsx', now())
        """
    )
    con.execute(
        """
        INSERT INTO dim_personnel_category (category_name) VALUES
        ('รวมทั้งหมด'), ('ข้าราชการ'), ('ครูและบุคลากรทางการศึกษา'), ('พลเรือนสามัญ')
        """
    )
    date_key = con.execute("SELECT date_key FROM dim_date").fetchone()[0]
    source_id = con.execute("SELECT source_id FROM dim_source").fetchone()[0]
    category_keys = dict(
        con.execute(
            "SELECT category_name, personnel_category_key FROM dim_personnel_category"
        ).fetchall()
    )
    return date_key, source_id, category_keys


def test_fact_disbursement_duplicate_grain_rejected(con):
    date_key, ministry_key, source_id, expense = seed_cgd(con)
    row = (date_key, ministry_key, expense["รายจ่ายประจำ"], source_id, 100, 100, 0, 0, 60, 40, 60.0)
    con.execute("INSERT INTO fact_disbursement VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO fact_disbursement VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)


def test_fact_disbursement_bad_fk_rejected(con):
    date_key, ministry_key, source_id, expense = seed_cgd(con)
    bad_row = (99999, ministry_key, expense["รายจ่ายประจำ"], source_id, 100, 100, 0, 0, 60, 40, 60.0)
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO fact_disbursement VALUES (?,?,?,?,?,?,?,?,?,?,?)", bad_row)


def test_dim_date_natural_key_rejects_duplicate(con):
    con.execute(
        """
        INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
        VALUES ('2026-07-03', DATE '2026-07-03', 2569, 2026)
        """
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """
            INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
            VALUES ('2026-07-03', DATE '2026-07-03', 2569, 2026)
            """
        )


def test_dim_date_natural_key_allows_cgd_and_ocsc_side_by_side(con):
    con.execute(
        """
        INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
        VALUES ('2026-07-03', DATE '2026-07-03', 2569, 2026)
        """
    )
    con.execute(
        """
        INSERT INTO dim_date (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce)
        VALUES ('FY2567', NULL, 2567, 2024)
        """
    )
    assert con.execute("SELECT count(*) FROM dim_date").fetchone()[0] == 2


def test_fact_disbursement_is_leaf_avoids_overcount(con):
    date_key, ministry_key, source_id, expense = seed_cgd(con)
    # 'รวม' is the additive rollup of the other two, not a 3rd independent value.
    rows = [
        (date_key, ministry_key, expense["รายจ่ายประจำ"], source_id, 100, 100, 0, 0, 60, 40, 60.0),
        (date_key, ministry_key, expense["รายจ่ายลงทุน"], source_id, 100, 100, 0, 0, 40, 60, 40.0),
        (date_key, ministry_key, expense["รวม"], source_id, 200, 200, 0, 0, 100, 100, 50.0),
    ]
    for row in rows:
        con.execute("INSERT INTO fact_disbursement VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)

    naive_sum = con.execute("SELECT SUM(disbursed) FROM fact_disbursement").fetchone()[0]
    assert naive_sum == 200  # 60 + 40 + 100 -- 'รวม' double-counts the two leaves

    leaf_sum = con.execute(
        """
        SELECT SUM(f.disbursed)
        FROM fact_disbursement f
        JOIN dim_expense_type e ON e.expense_type_key = f.expense_type_key
        WHERE e.is_leaf
        """
    ).fetchone()[0]
    assert leaf_sum == 100  # 60 + 40, matches the 'รวม' row without double-counting it


def test_fact_workforce_summary_is_leaf_avoids_overcount(con):
    date_key, source_id, cat = seed_ocsc(con)
    grand, sub = cat["รวมทั้งหมด"], cat["ข้าราชการ"]
    leaf1, leaf2 = cat["ครูและบุคลากรทางการศึกษา"], cat["พลเรือนสามัญ"]

    con.execute(
        "INSERT INTO fact_workforce_summary VALUES (?,?,?,?,?,?,?,?)",
        (date_key, grand, source_id, 858256, 100.0, 0, None, False),
    )
    con.execute(
        "INSERT INTO fact_workforce_summary VALUES (?,?,?,?,?,?,?,?)",
        (date_key, sub, source_id, 858256, 100.0, 1, grand, False),
    )
    con.execute(
        "INSERT INTO fact_workforce_summary VALUES (?,?,?,?,?,?,?,?)",
        (date_key, leaf1, source_id, 444168, 51.75, 2, sub, True),
    )
    con.execute(
        "INSERT INTO fact_workforce_summary VALUES (?,?,?,?,?,?,?,?)",
        (date_key, leaf2, source_id, 414088, 48.25, 2, sub, True),
    )

    naive_sum = con.execute("SELECT SUM(headcount) FROM fact_workforce_summary").fetchone()[0]
    assert naive_sum == 858256 * 2 + 444168 + 414088  # grand + subtotal + leaves, all counted

    leaf_sum = con.execute(
        "SELECT SUM(headcount) FROM fact_workforce_summary WHERE is_leaf"
    ).fetchone()[0]
    assert leaf_sum == 858256  # 444168 + 414088, matches the grand total exactly


def test_fact_workforce_summary_bad_fk_rejected(con):
    date_key, source_id, cat = seed_ocsc(con)
    bad_row = (date_key, 99999, source_id, 100, 100.0, 2, None, True)
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO fact_workforce_summary VALUES (?,?,?,?,?,?,?,?)", bad_row)


def test_fact_workforce_summary_duplicate_grain_rejected(con):
    date_key, source_id, cat = seed_ocsc(con)
    row = (date_key, cat["ข้าราชการ"], source_id, 858256, 100.0, 1, cat["รวมทั้งหมด"], False)
    con.execute("INSERT INTO fact_workforce_summary VALUES (?,?,?,?,?,?,?,?)", row)
    with pytest.raises(duckdb.ConstraintException):
        con.execute("INSERT INTO fact_workforce_summary VALUES (?,?,?,?,?,?,?,?)", row)

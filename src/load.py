"""Step 5: loader.

Reads Step 4's cleaned staging CSVs (staging/cgd_disbursement_clean.csv,
staging/ocsc_workforce_clean.csv) and raw/manifest.json, and performs an
idempotent load into warehouse/warehouse.duckdb's dim_*/fact_* tables
(sql/schema.sql, Step 2).

"Idempotent" here means every INSERT is `ON CONFLICT (natural key) DO
NOTHING` — running this script twice against the same input must produce
identical row counts in every table. That relies on every table already
having a real UNIQUE/PRIMARY KEY constraint on its natural key; there is no
"check row count before inserting" logic anywhere in this file.

Paths are resolved relative to this file, same convention as every other
src/ script in this project.
"""

from __future__ import annotations

import csv
import json
from calendar import monthrange
from datetime import date, datetime
from pathlib import Path

import duckdb

from extract import STAGING_DIR
from init_db import DB_PATH, ensure_schema

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "raw" / "manifest.json"


# ---------------------------------------------------------------- helpers

def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def parse_float_or_none(value: str) -> float | None:
    value = value.strip()
    return float(value) if value else None


def load_manifest() -> dict:
    """{'CGD': latest CGD entry, 'OCSC': latest OCSC entry} -- the entry
    with the latest report_date/fiscal_year_be per source, not just
    "whichever happens to be last in the file". Manifest order is never
    trusted, same discipline as detect.py's latest_cgd_date_from_manifest:
    now that Step 7's downloader can genuinely append a second CGD entry,
    a naive {entry["source"]: entry for entry in ...} dict comprehension
    would silently keep whichever entry iterates last, not whichever is
    actually newest.
    """
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cgd_entries = [e for e in manifest["files"] if e["source"] == "CGD"]
    ocsc_entries = [e for e in manifest["files"] if e["source"] == "OCSC"]

    result = {}
    if cgd_entries:
        result["CGD"] = max(cgd_entries, key=lambda e: e["report_date"])
    if ocsc_entries:
        result["OCSC"] = max(ocsc_entries, key=lambda e: e["fiscal_year_be"])
    return result


def thai_fiscal_year_be(report_date: date) -> int:
    """Thai government fiscal year runs Oct 1 - Sep 30; Oct/Nov/Dec belong
    to the *next* calendar year's fiscal year. Not stored anywhere
    machine-readable for CGD (only the free-text report title has it, and
    nothing in this pipeline parses that title) so it's derived here from
    report_date instead of guessed. Verified against the one data point we
    have: report_date 2026-07-03 -> FY2569, matching reports/eda_cgd.txt's
    row 0 title text ('...ปีงบประมาณ พ.ศ. 2569')."""
    fiscal_year_ce = report_date.year + 1 if report_date.month >= 10 else report_date.year
    return fiscal_year_ce + 543


def thai_fiscal_quarter(month: int) -> int:
    """Q1 = Oct-Dec, Q2 = Jan-Mar, Q3 = Apr-Jun, Q4 = Jul-Sep."""
    return ((month - 10) % 12) // 3 + 1


def is_last_day_of_month(d: date) -> bool:
    return d.day == monthrange(d.year, d.month)[1]


# ---------------------------------------------------------------- dim_source

def load_dim_source(con: duckdb.DuckDBPyConnection, agency: str) -> int:
    entry = load_manifest()[agency]
    file_name = Path(entry["local_path"]).name
    con.execute(
        """
        INSERT INTO dim_source (agency, source_url, file_name, file_hash, ingested_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (file_hash) DO NOTHING
        """,
        [agency, entry["source_url"], file_name, entry["sha256"], datetime.now()],
    )
    return con.execute(
        "SELECT source_id FROM dim_source WHERE file_hash = ?", [entry["sha256"]]
    ).fetchone()[0]


# ---------------------------------------------------------------- dim_date

def load_dim_date_cgd(con: duckdb.DuckDBPyConnection, report_date_str: str) -> int:
    report_date = date.fromisoformat(report_date_str)
    fiscal_year_be = thai_fiscal_year_be(report_date)
    fiscal_year_ce = fiscal_year_be - 543
    natural_key = report_date.isoformat()

    con.execute(
        """
        INSERT INTO dim_date
            (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce, month, quarter, is_month_end)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (date_natural_key) DO NOTHING
        """,
        [
            natural_key,
            report_date,
            fiscal_year_be,
            fiscal_year_ce,
            report_date.month,
            thai_fiscal_quarter(report_date.month),
            is_last_day_of_month(report_date),
        ],
    )
    return con.execute(
        "SELECT date_key FROM dim_date WHERE date_natural_key = ?", [natural_key]
    ).fetchone()[0]


def load_dim_date_ocsc(con: duckdb.DuckDBPyConnection, fiscal_year_be: int) -> int:
    fiscal_year_ce = fiscal_year_be - 543
    natural_key = f"FY{fiscal_year_be}"

    con.execute(
        """
        INSERT INTO dim_date
            (date_natural_key, report_date, fiscal_year_be, fiscal_year_ce, month, quarter, is_month_end)
        VALUES (?, NULL, ?, ?, NULL, NULL, NULL)
        ON CONFLICT (date_natural_key) DO NOTHING
        """,
        [natural_key, fiscal_year_be, fiscal_year_ce],
    )
    return con.execute(
        "SELECT date_key FROM dim_date WHERE date_natural_key = ?", [natural_key]
    ).fetchone()[0]


# ---------------------------------------------------------------- CGD load

def load_cgd(con: duckdb.DuckDBPyConnection) -> None:
    manifest_entry = load_manifest()["CGD"]
    source_id = load_dim_source(con, "CGD")
    date_key = load_dim_date_cgd(con, manifest_entry["report_date"])

    rows = read_csv(STAGING_DIR / "cgd_disbursement_clean.csv")

    # dim_expense_type.is_leaf comes straight from clean.py's own column —
    # never re-derived independently here, so there is exactly one source
    # of truth (Step 4's test_cgd_is_leaf_consistent_per_expense_type
    # already guarantees every row for a given expense_type_name agrees).
    expense_types = {r["expense_type_name"]: parse_bool(r["is_leaf"]) for r in rows}
    for name, is_leaf in expense_types.items():
        con.execute(
            """
            INSERT INTO dim_expense_type (expense_type_name, is_leaf)
            VALUES (?, ?)
            ON CONFLICT (expense_type_name) DO NOTHING
            """,
            [name, is_leaf],
        )
    expense_type_keys = dict(
        con.execute("SELECT expense_type_name, expense_type_key FROM dim_expense_type").fetchall()
    )

    ministries = {r["ministry_code"]: r["ministry_name"] for r in rows}
    for code, name in ministries.items():
        con.execute(
            """
            INSERT INTO dim_ministry (ministry_code, ministry_name_th, source_name_raw)
            VALUES (?, ?, ?)
            ON CONFLICT (ministry_code) DO NOTHING
            """,
            [code, name, name],
        )
    ministry_keys = dict(
        con.execute("SELECT ministry_code, ministry_key FROM dim_ministry").fetchall()
    )

    for r in rows:
        con.execute(
            """
            INSERT INTO fact_disbursement
                (date_key, ministry_key, expense_type_key, source_id,
                 budget_after_transfer, allocated, spending_plan, po_reserved,
                 disbursed, remaining, disbursed_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date_key, ministry_key, expense_type_key) DO NOTHING
            """,
            [
                date_key,
                ministry_keys[r["ministry_code"]],
                expense_type_keys[r["expense_type_name"]],
                source_id,
                float(r["budget_after_transfer"]),
                float(r["allocated"]),
                float(r["spending_plan"]),
                float(r["po_reserved"]),
                float(r["disbursed"]),
                float(r["remaining"]),
                parse_float_or_none(r["disbursed_pct"]),
            ],
        )


# ---------------------------------------------------------------- OCSC load

def load_ocsc(con: duckdb.DuckDBPyConnection) -> None:
    manifest_entry = load_manifest()["OCSC"]
    source_id = load_dim_source(con, "OCSC")
    date_key = load_dim_date_ocsc(con, manifest_entry["fiscal_year_be"])

    rows = read_csv(STAGING_DIR / "ocsc_workforce_clean.csv")

    # dim_personnel_category: insert every distinct (already-stripped by
    # clean.py) category_name FIRST, THEN build the name -> key lookup,
    # THEN resolve parent_category text -> parent_category_key using that
    # lookup. Never resolve a key before the row that owns it exists.
    for r in rows:
        con.execute(
            """
            INSERT INTO dim_personnel_category (category_name)
            VALUES (?)
            ON CONFLICT (category_name) DO NOTHING
            """,
            [r["category_name"]],
        )
    category_keys = dict(
        con.execute(
            "SELECT category_name, personnel_category_key FROM dim_personnel_category"
        ).fetchall()
    )

    for r in rows:
        parent_text = r["parent_category"]
        # Grand total's parent_category came out of clean.py as None, which
        # write_csv/csv.DictWriter serialized as ''. Empty string here means
        # "no parent" -> parent_category_key stays NULL, not resolved to
        # some default.
        parent_key = category_keys[parent_text] if parent_text else None

        con.execute(
            """
            INSERT INTO fact_workforce_summary
                (date_key, personnel_category_key, source_id, headcount,
                 share_pct, hierarchy_level, parent_category_key, is_leaf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date_key, personnel_category_key) DO NOTHING
            """,
            [
                date_key,
                category_keys[r["category_name"]],
                source_id,
                int(r["headcount"]),
                parse_float_or_none(r["share_pct"]),
                int(r["hierarchy_level"]),
                parent_key,
                parse_bool(r["is_leaf"]),
            ],
        )


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    try:
        ensure_schema(con)
        load_cgd(con)
        load_ocsc(con)

        tables = [
            "dim_date", "dim_ministry", "dim_expense_type",
            "dim_personnel_category", "dim_source",
            "fact_disbursement", "fact_workforce_summary",
        ]
        for t in tables:
            count = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            print(f"{t}: {count} rows")
    finally:
        con.close()


if __name__ == "__main__":
    main()

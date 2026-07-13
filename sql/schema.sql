-- ============================================================
-- ISAP Data Engineer project — warehouse schema (Step 2)
-- Engine: DuckDB. Star schema: 2 fact tables + conformed dims.
-- This file defines the `warehouse/` layer only (see PROJECT_SPEC.md §4).
-- Safe to re-run: every statement is IF NOT EXISTS.
-- ============================================================

-- ---- surrogate key sequences (one per dimension) ----
CREATE SEQUENCE IF NOT EXISTS seq_dim_date              START 1;
CREATE SEQUENCE IF NOT EXISTS seq_dim_ministry           START 1;
CREATE SEQUENCE IF NOT EXISTS seq_dim_expense_type       START 1;
CREATE SEQUENCE IF NOT EXISTS seq_dim_personnel_category START 1;
CREATE SEQUENCE IF NOT EXISTS seq_dim_source             START 1;

-- ============================================================
-- DIMENSIONS
-- ============================================================

CREATE TABLE IF NOT EXISTS dim_date (
    date_key         INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_date'),
    date_natural_key VARCHAR NOT NULL UNIQUE,  -- CGD: '2026-07-03'. OCSC: 'FY2567'.
    report_date      DATE,              -- CGD: report-as-of date. NULL for OCSC.
    fiscal_year_be   INTEGER NOT NULL,  -- Buddhist-era fiscal year, e.g. 2569
    fiscal_year_ce   INTEGER NOT NULL,  -- = fiscal_year_be - 543, e.g. 2026
    month            INTEGER,           -- CGD only, 1-12. NULL for OCSC.
    quarter          INTEGER,           -- CGD only, 1-4. NULL for OCSC.
    is_month_end     BOOLEAN,           -- CGD only. NULL for OCSC.
    CHECK (fiscal_year_ce = fiscal_year_be - 543)  -- catches a loader bug that inserts BE/CE out of sync
);

CREATE TABLE IF NOT EXISTS dim_ministry (
    ministry_key     INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_ministry'),
    ministry_code    VARCHAR NOT NULL UNIQUE,  -- e.g. '08', from CGD column 'รหัสกระทรวง'
    ministry_name_th VARCHAR NOT NULL,
    source_name_raw  VARCHAR                   -- first-seen raw name string, kept for debugging
);

CREATE TABLE IF NOT EXISTS dim_expense_type (
    expense_type_key  INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_expense_type'),
    expense_type_name VARCHAR NOT NULL UNIQUE,  -- 'รายจ่ายประจำ' / 'รายจ่ายลงทุน' / 'รวม'
    is_leaf           BOOLEAN NOT NULL          -- true for the two components, false for 'รวม'
);

CREATE TABLE IF NOT EXISTS dim_personnel_category (
    personnel_category_key INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_personnel_category'),
    category_name           VARCHAR NOT NULL UNIQUE  -- stripped of whitespace, e.g. 'ข้าราชการ'
);

CREATE TABLE IF NOT EXISTS dim_source (
    source_id   INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_source'),
    agency      VARCHAR NOT NULL,   -- 'CGD' or 'OCSC'
    source_url  VARCHAR,
    file_name   VARCHAR NOT NULL,   -- e.g. '2026_07_03.xlsx'
    file_hash   VARCHAR NOT NULL UNIQUE,  -- sha256 of the raw file, ties to raw/manifest.json
    ingested_at TIMESTAMP NOT NULL
);

-- ============================================================
-- FACTS
-- ============================================================
CREATE TABLE IF NOT EXISTS fact_disbursement (
    date_key              INTEGER NOT NULL REFERENCES dim_date(date_key),
    ministry_key          INTEGER NOT NULL REFERENCES dim_ministry(ministry_key),
    expense_type_key      INTEGER NOT NULL REFERENCES dim_expense_type(expense_type_key),
    source_id             INTEGER NOT NULL REFERENCES dim_source(source_id),
    budget_after_transfer DOUBLE NOT NULL,  -- วงเงินงบประมาณหลังโอนเปลี่ยนแปลง
    allocated             DOUBLE NOT NULL,  -- จัดสรร
    spending_plan         DOUBLE NOT NULL,  -- แผนการใช้จ่าย (0 for all ministries today — kept, see reports/eda_cgd.txt)
    po_reserved           DOUBLE NOT NULL,  -- PO+สำรองเงินมีหนี้
    disbursed             DOUBLE NOT NULL,  -- เบิกจ่าย
    remaining             DOUBLE NOT NULL,  -- derived: budget_after_transfer - disbursed
    disbursed_pct         DOUBLE,           -- derived: disbursed / budget_after_transfer * 100 (recomputed, NOT the
                                             -- Excel formula). Nullable: Step 4's clean.py stores NULL, not inf/crash,
                                             -- when budget_after_transfer = 0 (not reachable in today's data, but the
                                             -- column must allow it or the loader would fail when it happens).
    PRIMARY KEY (date_key, ministry_key, expense_type_key)
);

CREATE TABLE IF NOT EXISTS fact_workforce_summary (
    date_key               INTEGER NOT NULL REFERENCES dim_date(date_key),
    personnel_category_key INTEGER NOT NULL REFERENCES dim_personnel_category(personnel_category_key),
    source_id              INTEGER NOT NULL REFERENCES dim_source(source_id),
    headcount              BIGINT NOT NULL,   -- คน
    share_pct              DOUBLE,            -- derived: headcount / grand_total_headcount * 100. Nullable for the
                                                -- same reason as fact_disbursement.disbursed_pct: NULL when the
                                                -- grand-total denominator is 0, not inf/crash.
    hierarchy_level        TINYINT NOT NULL,  -- 0 = grand total, 1 = subtotal, 2 = leaf category
    parent_category_key    INTEGER REFERENCES dim_personnel_category(personnel_category_key),  -- NULL for grand total
    is_leaf                BOOLEAN NOT NULL,  -- WHERE is_leaf = true => SUM(headcount) is correct, no double count
    PRIMARY KEY (date_key, personnel_category_key)
);

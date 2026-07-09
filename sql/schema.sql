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

-- One row per distinct date grain. CGD rows carry an exact report_date;
-- OCSC rows carry only fiscal_year_be and leave report_date NULL, because
-- the OCSC yearbook has no daily grain (PROJECT_SPEC.md §4.1).
--
-- report_date is nullable, so a plain UNIQUE on it would not stop two OCSC
-- rows for the same fiscal year from both being inserted (SQL treats every
-- NULL as distinct). date_natural_key exists purely to close that gap: the
-- loader must set it to the ISO report_date string for CGD (e.g.
-- '2026-07-03') or 'FY' + fiscal_year_be for OCSC (e.g. 'FY2567'), and the
-- UNIQUE constraint then guarantees no duplicate date row can ever be
-- inserted, independent of whatever the loader's own idempotency logic does.
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

-- 'รวม' (total) is an additive rollup of 'รายจ่ายประจำ' + 'รายจ่ายลงทุน' for
-- the same ministry+period — the exact same overcount risk found in OCSC
-- sheet '12' (reports/eda_ocsc.txt): a naive SUM(disbursed) across all three
-- expense types double-counts every ministry. is_leaf is the same fix.
-- Unlike fact_workforce_summary's hierarchy columns, this one lives on the
-- dimension, not the fact: CGD's three-way split is a fixed, unchanging
-- enumeration (not something that could be restructured per load the way a
-- personnel category could), so there is no per-load reason to duplicate it.
CREATE TABLE IF NOT EXISTS dim_expense_type (
    expense_type_key  INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_expense_type'),
    expense_type_name VARCHAR NOT NULL UNIQUE,  -- 'รายจ่ายประจำ' / 'รายจ่ายลงทุน' / 'รวม'
    is_leaf           BOOLEAN NOT NULL          -- true for the two components, false for 'รวม'
);

-- One row per personnel category from OCSC sheet '12'. Hierarchy info
-- (level / parent / is_leaf) lives on fact_workforce_summary, not here —
-- see the comment above that table for why.
CREATE TABLE IF NOT EXISTS dim_personnel_category (
    personnel_category_key INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_personnel_category'),
    category_name           VARCHAR NOT NULL UNIQUE  -- stripped of whitespace, e.g. 'ข้าราชการ'
);

CREATE TABLE IF NOT EXISTS dim_source (
    source_id   INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_source'),
    agency      VARCHAR NOT NULL,   -- 'CGD' or 'OCSC'
    source_url  VARCHAR,
    file_name   VARCHAR NOT NULL,   -- e.g. '2026_07_03.xlsx'
    file_hash   VARCHAR,            -- sha256 of the raw file, ties to raw/manifest.json
    ingested_at TIMESTAMP NOT NULL
);

-- ============================================================
-- FACTS
-- ============================================================

-- Grain: one row per (report_date x ministry x expense_type).
-- Source: CGD sheet '2.กระทรวง'. Unit: million THB (ล้านบาท).
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
    disbursed_pct         DOUBLE NOT NULL,  -- derived: disbursed / budget_after_transfer * 100 (recomputed, NOT the Excel formula)
    PRIMARY KEY (date_key, ministry_key, expense_type_key)
);

-- Grain: one row per (fiscal_year x personnel_category).
-- Source: OCSC sheet '12'.
-- hierarchy_level / parent_category_key / is_leaf live on the fact (not the
-- dimension) because a category's place in the hierarchy is a fact of a
-- given year's report, not a permanent trait of the category itself — next
-- year's yearbook could in principle restructure it. See PROJECT_SPEC.md §4.2
-- and reports/eda_ocsc.txt for the hierarchy finding this is built on.
CREATE TABLE IF NOT EXISTS fact_workforce_summary (
    date_key               INTEGER NOT NULL REFERENCES dim_date(date_key),
    personnel_category_key INTEGER NOT NULL REFERENCES dim_personnel_category(personnel_category_key),
    source_id              INTEGER NOT NULL REFERENCES dim_source(source_id),
    headcount              BIGINT NOT NULL,   -- คน
    share_pct              DOUBLE NOT NULL,   -- derived: headcount / grand_total_headcount * 100
    hierarchy_level        TINYINT NOT NULL,  -- 0 = grand total, 1 = subtotal, 2 = leaf category
    parent_category_key    INTEGER REFERENCES dim_personnel_category(personnel_category_key),  -- NULL for grand total
    is_leaf                BOOLEAN NOT NULL,  -- WHERE is_leaf = true => SUM(headcount) is correct, no double count
    PRIMARY KEY (date_key, personnel_category_key)
);

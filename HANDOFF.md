# HANDOFF.md — Read this first

> If you are Claude Code (or any AI assistant) picking up this project: read this
> file, then `PROJECT_SPEC.md` in full. That's the whole context you need —
> don't re-derive the plan from scratch, and don't re-open the source Excel
> files to "explore" before checking whether Step 1 already answered your
> question (it probably did — see `reports/`).

## Who's doing this

Student project for ISAP (Innosoft Student Associate Program) selection,
Data Engineer track. Author is a beginner/intermediate CompEng student —
**keep code simple enough to explain line-by-line in an interview.** No
Airflow, no Spark, no framework the author can't defend under questioning.
If you're about to reach for something "impressive," don't — check
`PROJECT_SPEC.md` §11 (High-Risk Parts) and §3 (explicit out-of-scope list)
first.

## Working style the author wants

- **Step by step, not all at once.** Finish one step, confirm it runs, then
  move to the next. Don't jump ahead and generate the whole pipeline.
- **Every code step needs:** files created/edited, exact code, commands to
  run, expected output, how to test, and a plain-language explanation of
  what the code does (author needs to explain it in an interview).
- **Be strict.** If something is risky, untested, fake, or over-engineered,
  say so explicitly rather than smoothing it over.
- Mixed Thai-English explanations are welcome and preferred for concepts.

## Status as of this handoff

| Step | Status | Notes |
|---|---|---|
| 0 — Repo skeleton & env | ✅ Done | See commit `Step 0: repo skeleton...` |
| 1 — EDA & profiling | ✅ Done | See commit `Step 1: EDA & data profiling...`. Real findings in `reports/eda_cgd.txt` and `reports/eda_ocsc.txt` — **read these before re-profiling anything.** |
| 2 — Warehouse DDL | ✅ Done | `sql/schema.sql` (DDL) + `src/init_db.py` (runner) + `tests/test_schema.py` (8 pytest cases, all green under duckdb 1.5.4 / pytest 8.4.2, run via `.venv`). `dim_date.date_natural_key` (UNIQUE) enforces one row per report_date/fiscal_year. `dim_date` also has a `CHECK (fiscal_year_ce = fiscal_year_be - 543)` guarding the BE/CE conversion. `dim_expense_type.is_leaf` guards against 'รวม' double-counting the other two expense types — same overcount pattern as the OCSC hierarchy, fixed the same way but on the dimension since CGD's 3-way split is static. **Amended in Step 4:** `disbursed_pct`/`share_pct` were originally `NOT NULL`; loosened to nullable once Step 4 decided zero-denominator cases store NULL — see "Edge case history" below. |
| 3 — Extractor | ✅ Done | `config/cgd.yaml` + `config/ocsc.yaml` (row/column boundaries) + `src/extract.py` + `tests/test_extract.py` (5 pytest cases, all green). Writes `staging/cgd_disbursement.csv` (24 rows) and `staging/ocsc_workforce.csv` (25 rows, hierarchy_level + parent_category tagged at extraction time). **Correction from the original Step 3 brief:** OCSC row count is 25, not 29 — verified directly against the raw file (1 grand total + 2 subtotals + 22 leaf = 25); the config's row *ranges* were already correct, only the total count claim was off. Added `PyYAML>=6.0,<7.0` to `requirements.txt` (was missing). No cleaning logic in this step — total row and footnote row are structurally excluded by range, not filtered by content; ministry names/category names are NOT `.strip()`-ed here (still dirty, e.g. `'องค์กรอิสระตามรัฐธรรมนูญ '`) — that was Step 4's job. |
| 4 — Cleaner/transformer | ✅ Done | `src/clean.py` + `tests/test_clean.py` (6 pytest cases, all green). Reads Step 3's staging CSVs, writes `staging/cgd_disbursement_clean.csv` (72 rows — 24 ministries × 3 expense types, unpivoted) and `staging/ocsc_workforce_clean.csv` (25 rows). Recomputes `disbursed_pct`/`share_pct` from raw numbers (never trusts the Excel-reported percent — matches within float precision, verified). **Divide-by-zero decision (closes the Step 2 edge-case note): both return `None`/NULL when the denominator is 0**, not `inf` or a crash — not reachable in today's data (checked: no ministry has `budget_after_transfer == 0`; OCSC grand total is 3,004,485), covered by a synthetic-row unit test since real data can't exercise it. `is_leaf` computed both places: CGD from a fixed expense-type set (`รวม` = rollup = not leaf), OCSC from `hierarchy_level == 2`. `parent_category` is deliberately left as **plain stripped text, not a resolved key** — `dim_personnel_category` isn't populated until Step 5's loader runs, so resolving it here would mean guessing; this is a documented Step 5 dependency, not an oversight. |
| 5 — Loader | ⬜ Not started | This is the next step. Must: insert `dim_expense_type` (3 rows, with `is_leaf`) and `dim_personnel_category` rows first, then resolve `staging/ocsc_workforce_clean.csv`'s text `parent_category` into `parent_category_key` via a lookup against the just-inserted dimension, then load both fact tables. Also must decide how CSV's empty-string representation of `disbursed_pct`/`share_pct` NULLs gets turned into a real SQL NULL on insert — csv module writes `None` as `''`, not the literal word NULL. |
| 6 — Latest-file detector (web scraping) | ⬜ Not started | Untested — no internet access existed in the sandbox that built Steps 0-1. Test this early on the author's real machine. |
| 7 — Scheduler + schema validation | ⬜ Not started | |
| 8 — Tests | ⬜ Not started | |
| 9 — Suggestions to Senior + docs + interview prep | ⬜ Not started | |

## Locked decisions — do not re-litigate these

- **Warehouse engine:** DuckDB (single file `warehouse.duckdb`)
- **Scheduler:** GitHub Actions, monthly cron
- **Scope:** core only — `fact_disbursement` (CGD sheet `2.กระทรวง`) +
  `fact_workforce_summary` (OCSC sheet `12`). Stretch sheets (`17-29`,
  `3.หน่วยงาน`) are explicitly deferred, not forgotten.

## Important findings from Step 1 that affect design (already reflected in PROJECT_SPEC.md)

1. **CGD `2.กระทรวง`:** total row (`รวม`) does NOT follow the data rows' column
   layout — label shifts from column 1 to column 0, and the ministry_code
   cell is a stray space `' '`, not `None`. Any cleaner must detect this row
   by pattern, not by null-checking.
2. **CGD `2.กระทรวง`:** `แผนการใช้จ่าย` (spending plan) columns are 0 for
   100% of ministries — carry through as-is, don't silently drop the column.
3. **CGD `2.กระทรวง`:** this specific sheet has zero live formulas (values
   are pre-baked), unlike sheet `1.สรุปภาพรวม` in the same workbook which
   does use formulas. Don't assume one sheet's formula status for the whole
   workbook.
4. **OCSC sheet `12`:** NOT a flat list — it's a verified 2-level hierarchy
   (1 grand total + 2 subtotals + 22 leaf categories). `PROJECT_SPEC.md`
   §4.2 already has the fix (`hierarchy_level`, `parent_category_key`,
   `is_leaf` columns on `fact_workforce_summary`). Don't reintroduce a flat
   design.
5. **OCSC sheet `12`:** one category name has trailing whitespace
   (`'องค์กรอิสระตามรัฐธรรมนูญ '`) — must `.strip()` all text fields.

## Edge case history: divide-by-zero in the derived `_pct` columns — CLOSED in Step 4

`fact_disbursement.disbursed_pct` and `fact_workforce_summary.share_pct` both
divide by a value that's *usually* non-zero (verified: not reachable in
today's data), but Step 2's DDL originally declared both `NOT NULL`, which
would have crashed the loader the day it happened. Step 4's `clean.py`
decided: store `NULL` when the denominator is 0, not `inf`/`NaN`/a crash.
That decision required going back and loosening `sql/schema.sql` — both
columns are now nullable (`DOUBLE`, not `DOUBLE NOT NULL`) — re-verified
`tests/test_schema.py` still passes and manually confirmed a NULL insert is
now accepted. If you're touching `sql/schema.sql` again, don't reintroduce
`NOT NULL` on these two columns without also changing `clean.py`'s behavior.

## Environment notes

- Repo layout, `.gitignore` policy (raw/ tracked, staging/ and warehouse/*.duckdb
  not), and the reasoning for both are explained in `README.md` and inline
  comments — read those instead of asking the author to re-explain.
- `requirements.txt` is version-range-pinned (not exact), verified against
  what's actually importable. `duckdb` and `pytest` were NOT verified in the
  environment that built Steps 0-1 (no internet there) — if either fails to
  install, that's new information, debug it for real rather than assuming
  the pin is wrong.
- Scripts assume they're run from the repo root (relative paths like
  `raw/cgd/...`). This bit the author once already during Step 1 — don't
  repeat that mistake in new scripts without at least flagging it.

## Next action

Start Step 5: the loader. Reads `staging/cgd_disbursement_clean.csv` and
`staging/ocsc_workforce_clean.csv` (from Step 4) and performs an idempotent
upsert into `warehouse/warehouse.duckdb`'s dim/fact tables (`sql/schema.sql`,
Step 2). Order matters: dims before facts, and `dim_expense_type` /
`dim_personnel_category` before resolving CGD/OCSC's text fields into
surrogate keys — neither dimension is seeded by the DDL itself. Specifically
needs to: (1) insert `dim_expense_type`'s 3 rows with `is_leaf`; (2) insert
`dim_personnel_category` rows and then resolve `ocsc_workforce_clean.csv`'s
plain-text `parent_category` into `parent_category_key` via lookup; (3)
insert/reuse `dim_ministry`, `dim_date` (remember `date_natural_key`); (4)
convert the clean CSVs' empty-string NULLs (`disbursed_pct`/`share_pct`)
into real SQL NULLs on insert — csv.DictWriter wrote `None` as `''`, not the
literal word NULL, so a naive `float('')` will crash; (5) make re-running
the loader on the same input not create duplicate rows (the fact tables'
composite PRIMARY KEYs will reject exact duplicates, but decide what
"re-run with updated numbers for the same grain" should do — update or
reject). Follow the same per-step format (files / code / commands /
expected output / test / explain) as Steps 0-4.

Note: `raw/manifest.json` (hash/url/timestamp tracking for idempotent
re-downloads) is not built yet — that belongs to Step 6's detector, not
Step 3's extractor.

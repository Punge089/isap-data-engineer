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
| 2 — Warehouse DDL | ✅ Done | `sql/schema.sql` (DDL) + `src/init_db.py` (runner) + `tests/test_schema.py` (8 pytest cases, all green under duckdb 1.5.4 / pytest 8.4.2, run via `.venv`). `dim_date.date_natural_key` (UNIQUE) enforces one row per report_date/fiscal_year. `dim_date` also has a `CHECK (fiscal_year_ce = fiscal_year_be - 543)` guarding the BE/CE conversion. `dim_expense_type.is_leaf` guards against 'รวม' double-counting the other two expense types — same overcount pattern as the OCSC hierarchy, fixed the same way but on the dimension since CGD's 3-way split is static. Known gap carried forward: divide-by-zero in the `_pct` columns is **not yet handled** — see "Known edge cases for Step 4" below. |
| 3 — Extractor | ✅ Done | `config/cgd.yaml` + `config/ocsc.yaml` (row/column boundaries) + `src/extract.py` + `tests/test_extract.py` (4 pytest cases, all green). Writes `staging/cgd_disbursement.csv` (24 rows) and `staging/ocsc_workforce.csv` (25 rows, hierarchy_level + parent_category tagged at extraction time). **Correction from the original Step 3 brief:** OCSC row count is 25, not 29 — verified directly against the raw file (1 grand total + 2 subtotals + 22 leaf = 25); the config's row *ranges* were already correct, only the total count claim was off. Added `PyYAML>=6.0,<7.0` to `requirements.txt` (was missing). No cleaning logic in this step — total row and footnote row are structurally excluded by range, not filtered by content; ministry names/category names are NOT `.strip()`-ed here (still dirty, e.g. `'องค์กรอิสระตามรัฐธรรมนูญ '`) — that's Step 4. |
| 4 — Cleaner/transformer | ⬜ Not started | This is the next step. Must: `.strip()` text fields, recompute `disbursed_pct`/`share_pct` (deciding the divide-by-zero behavior — see edge case note below), compute `is_leaf`/`remaining`, and turn each CGD ministry row into 3 long-format rows (one per expense type) using `staging/cgd_disbursement.csv`'s `recurring_*`/`capital_*`/`total_*` columns. |
| 5 — Loader | ⬜ Not started | |
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

## Known edge cases for Step 4 (cleaner/transformer) — not yet handled anywhere

- **Divide-by-zero in the derived `_pct` columns.** `fact_disbursement.disbursed_pct`
  (`disbursed / budget_after_transfer * 100`) and `fact_workforce_summary.share_pct`
  (`headcount / grand_total_headcount * 100`) both divide by a value that is
  *usually* non-zero in the data seen so far, but nothing in `sql/schema.sql`
  guarantees it (both `_pct` columns are `NOT NULL`, not "not zero"). Neither
  Step 1's EDA nor Step 2's DDL enforces or even checks this — it is the
  cleaner's job in Step 4 to decide what happens when the denominator is 0
  (e.g. a ministry with `budget_after_transfer = 0`): store `NULL`, store `0`,
  or raise loud. Whatever is chosen, write a test for it — don't let it surface
  first as a silent `inf`/`NaN` in the warehouse.

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

Start Step 4: the cleaner/transformer. Reads `staging/cgd_disbursement.csv`
and `staging/ocsc_workforce.csv` (from Step 3) and produces the
warehouse-ready rows: `.strip()` text fields, decide + implement the
divide-by-zero behavior for `disbursed_pct`/`share_pct` (see "Known edge
cases for Step 4" above), compute `remaining` and `is_leaf`, and unpivot
each CGD ministry row into 3 long-format rows (one per expense type:
`รายจ่ายประจำ`/`รายจ่ายลงทุน`/`รวม`). Follow the same per-step format
(files / code / commands / expected output / test / explain) as Steps 0-3.
Note: `raw/manifest.json` (hash/url/timestamp tracking for idempotent
re-downloads) is not built yet — that belongs to Step 6's detector, not
Step 3's extractor, since Step 3 only reads files already sitting in
`raw/`, it doesn't fetch or hash them.

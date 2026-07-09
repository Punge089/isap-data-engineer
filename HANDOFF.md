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
| 4 — Cleaner/transformer | ✅ Done | `src/clean.py` + `tests/test_clean.py` (7 pytest cases, all green). Reads Step 3's staging CSVs, writes `staging/cgd_disbursement_clean.csv` (72 rows — 24 ministries × 3 expense types, unpivoted) and `staging/ocsc_workforce_clean.csv` (25 rows). Recomputes `disbursed_pct`/`share_pct` from raw numbers (never trusts the Excel-reported percent — matches within float precision, verified). **Divide-by-zero decision (closes the Step 2 edge-case note): both return `None`/NULL when the denominator is 0**, not `inf` or a crash — not reachable in today's data (checked: no ministry has `budget_after_transfer == 0`; OCSC grand total is 3,004,485), covered by a synthetic-row unit test since real data can't exercise it. `is_leaf` computed both places: CGD from a fixed expense-type set (`รวม` = rollup = not leaf), OCSC from `hierarchy_level == 2`. `parent_category` is deliberately left as **plain stripped text, not a resolved key** — `dim_personnel_category` isn't populated until Step 5's loader runs, so resolving it here would mean guessing; this is a documented Step 5 dependency, not an oversight. |
| 5 — Loader | ✅ Done | `src/load.py` + `tests/test_load.py` (6 pytest cases, all green). Reads Step 4's clean CSVs + `raw/manifest.json`, idempotent-loads both facts via `ON CONFLICT (natural key) DO NOTHING` — **proven by running the real loader twice and diffing actual row counts, not by inspecting the code**: `dim_date` 2, `dim_ministry` 24, `dim_expense_type` 3, `dim_personnel_category` 25, `dim_source` 2, `fact_disbursement` 72, `fact_workforce_summary` 25, identical both runs. **Schema fix required first:** `dim_source` had no natural-key UNIQUE constraint (only a surrogate PK), so `ON CONFLICT (file_hash)` had nothing to target and would have silently duplicated a row every run — added `file_hash VARCHAR NOT NULL UNIQUE` to `sql/schema.sql`, updated `tests/test_schema.py`'s seed helpers to supply it, re-ran full suite to confirm no regressions. `init_db.py` refactored to expose `ensure_schema(con)` so `load.py` can guarantee tables exist without requiring `init_db.py` to have run first. **New assumption, not in any config/manifest:** CGD's `fiscal_year_be` is derived from `report_date` using the standard Thai Oct–Sep fiscal year rule (`thai_fiscal_year_be()` in `load.py`), direction locked in by `test_thai_fiscal_year_be_cutover_direction` (2025-09-30 → 2568, 2025-10-01 → 2569). **This rule has only ever been checked against one real report, dated 2026-07-03 (deep mid-year) — it has never been cross-checked against an actual report published Oct-Dec, re-verify the moment Step 6 pulls one.** |
| 6 — Latest-file detector (web scraping) | ✅ Done (CGD fully automated, OCSC manual-fallback) | `src/detect.py` + `tests/test_detect.py` (13 pytest cases, all green) + `tests/fixtures/*.html` (real saved pages, 3 of them). **Environment issue found and actually fixed, not worked around:** this machine's antivirus (Norton) does local HTTPS-scanning by re-signing every TLS connection with its own generated root cert ("Norton Web/Mail Shield Root") — confirmed by reading the actual certificate bytes. Windows trusts that root; Python's bundled `certifi` list doesn't, so every `requests` call failed `SSLError`, even to `google.com`. Fixed for real by adding `pip-system-certs` to `requirements.txt`, which makes Python trust the Windows cert store — confirmed working: `requests.get('https://www.google.com')` now succeeds with zero special flags, and **the actual shipped, unmodified `python src/detect.py` was then run live against both real sites, no `verify=False`, no bypass.** **CGD: fully works, live-verified.** Real 200, real HTML, parser (`parse_thai_be_date` against the table's dedicated `DD/MM/YYYY`-BE column) correctly reports "nothing new" against the live site (matches `raw/manifest.json`'s 2026-07-03 exactly). **OCSC: two DIFFERENT real responses observed on two separate live attempts against the same URL — both stand, neither supersedes the other, see "Open risk" note below.** `detect.py`'s `check_ocsc()` handles both: (1) a genuine Cloudflare managed JS challenge (HTTP 403, "Just a moment...", saved as `tests/fixtures/ocsc_cloudflare_challenge.html`), and (2) a clean, non-challenged 200 with real WordPress/Elementor HTML (saved as `tests/fixtures/ocsc_real_page_no_file_links.html`) that STILL has zero `.xlsx`/`.pdf`/`.zip` links anywhere in 369KB of page — the report list is rendered by a JS-driven filter widget (`form.custom-field-filter-form` → `wp-admin/admin-ajax.php`), not present in static HTML. Both are real, both are handled (`html_has_file_links()` checks directly rather than assuming), and manual-check fallback is the right call either way (OCSC publishes yearly, low impact). **Bug found and fixed on the CGD side too:** `load_known_cgd_date()` originally returned the *first* manifest entry matching `source=='CGD'`, not the latest — same class of ordering bug already flagged for `load.py`. Fixed to take `max()` across all matching entries (split into a pure `latest_cgd_date_from_manifest(manifest: dict)` for testability), proven order-independent with two fixture tests (ascending and descending manifest order, same answer both ways) — mirrors the exact discipline `find_latest_cgd_report` already applies to page rows. **New info for Step 7:** CGD's report links are NOT plain `<a href>` — they're `javascript:openDownload('NewsStat_C', id, '/cs/Satellite?...')` calls; the real download URL is the 3rd argument string, extractable without running JS. |
| 7 — Downloader + schema validation (local logic; GitHub Actions cron itself still pending) | ✅ Done | `src/download.py` + `src/validate_structure.py` + `tests/test_download.py` (9 cases) + `tests/test_validate_structure.py` (6 cases), all green. **`download_cgd()`**: extracts the real download URL from CGD's `javascript:openDownload('NewsStat_C', id, '/cs/Satellite?...')` href (regex on the 3rd argument + `urljoin`, confirmed against the real Step 6 fixture), downloads the bytes, hashes them, and appends (never overwrites) a new `raw/manifest.json` entry — only if the hash isn't already in the manifest (duplicate-content dedup, tested). Ran for real against the live CGD site: `CGD: nothing new to download (latest on site is 2026-07-03, already have it)` — correctly stopped before ever attempting a file download, and confirmed `raw/manifest.json`/`raw/cgd/` were untouched afterward. Since there was nothing new to actually download today, the "new file found → download → append" path is proven with a fixture (`tests/fixtures/fake_new_cgd_report.xlsx`, explicitly a placeholder, not a real xlsx — download.py never parses file contents, only hashes/saves bytes) standing in for the real bytes, with the listing page and the HTTP GET both faked via `monkeypatch` — stated explicitly, not hidden. **`download_ocsc()`** refuses immediately with a manual-check message and is tested to make zero network calls (asserts if `requests.get`/`detect.fetch_html` are even invoked). **`validate_structure.py`**: `validate_cgd_structure()` checks 8 header anchor cells + the total-row label against `config/cgd.yaml`'s new `validation:` section (exact real text, including embedded `\n`, re-verified against the live raw file) before `extract.py` parses anything — wired into `extract.py`'s `run_cgd()`. Tested against 5 deliberately mangled fake sheets (wrong sheet name, mangled header cell, truncated header, moved/wrong total-row label, sheet too short to reach the total row) — all raise `StructureValidationError`, plus the real committed file still passes; also proven through `extract.py`'s real `run_cgd()` entry point (not just calling `validate_cgd_structure()` directly), confirming the wiring itself stops extraction and never touches `staging/cgd_disbursement.csv`. **OCSC has no structure validation** — this is deliberate, not an oversight: there is no automated OCSC download path (Step 6) for validation to protect, so there is nothing for `validate_structure.py` to run before yet. **Two ordering bugs fixed as part of this step:** (1) `detect.py`'s `CgdReport` was refactored from a plain tuple to a `NamedTuple` (adds `download_href`) so `download.py` can get the real link without re-scraping — required updating `format_cgd_result` and all of `test_detect.py`, re-verified 13/13 still pass; (2) `load.py`'s `load_manifest()` — previously a `{source: entry}` dict comprehension that silently kept whichever entry iterated last, not deliberately "latest" — fixed to explicit `max()` by `report_date`/`fiscal_year_be`, same discipline as `detect.py`. New test `test_two_cgd_manifest_entries_across_two_runs_produce_two_dim_source_rows` proves two CGD manifest entries (simulated across two runs) produce two `dim_source` rows, not one overwriting the other. **GitHub Actions YAML wrapper is explicitly NOT built yet** — this step was scoped to local, fully-testable logic only; the cron wrapper is a thin follow-up once this is confirmed solid. **Known, accepted non-atomicity:** `download_cgd()`'s file-write and manifest-append aren't atomic together — an interrupted run (crash/kill between the two) just causes a redundant re-download on the next attempt, safe because dedup is by content hash, not a corruption risk; not a gap, not fixing it. |
| 8 — Tests | ⬜ Not started | Much of this already exists (55 tests across 7 files as of Step 7) — this step is about filling gaps (e.g. an actual end-to-end smoke test running extract→clean→load→detect→download in sequence against a temp warehouse) and organizing/documenting the suite, not starting from zero. |
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

## Open risk: OCSC detection may be non-deterministic — NOT closed, Step 7 must handle both outcomes

Two separate live requests to OCSC's listing page, made while building Step 6,
got two DIFFERENT real responses from the same URL:

1. **Blocked**: Cloudflare managed JS challenge, HTTP 403, "Just a moment...".
   Real, saved as `tests/fixtures/ocsc_cloudflare_challenge.html`. This
   happened first, before this machine's TLS issue (see Step 6's row above)
   was fixed.
2. **Not blocked**: clean HTTP 200, genuine WordPress/Elementor HTML, no
   Cloudflare challenge at all. Real, saved as
   `tests/fixtures/ocsc_real_page_no_file_links.html`. This happened after
   the TLS fix, on a separate live request.

**Neither observation is being treated as a mistake or as superseded by the
other.** Both are real responses this project has actually seen from the
live site. The honest conclusion is that `check_ocsc()`'s behavior against
the live URL may be non-deterministic — Cloudflare's challenge appears to
trigger sometimes and not other times against the same page, for reasons
this project has not investigated (rate-limiting, risk scoring, session
state, or something else entirely).

**Why this doesn't change the current fallback decision:** even in the
"not blocked" case, the real page still has zero scrapable file links (see
Step 6's row above) — so automated detection isn't possible either way,
just for two different reasons depending on which response you get.

**What Step 7 must NOT do:** assume the Cloudflare block is gone just
because one later request got through, and assume it isn't reachable just
because one earlier request got blocked. Step 7's monthly automation must
handle BOTH outcomes gracefully (log clearly which one occurred; don't
crash on either; don't silently treat a challenge as "nothing new") rather
than picking one as "the real behavior" and writing code that only expects
that one.

## Decision: the monthly CI workflow does NOT commit warehouse.duckdb — CLOSED, open since Step 0/6

`.github/workflows/monthly_check.yml` only commits `raw/manifest.json` and
any new `raw/cgd/*.xlsx` back to the repo. It does **not** rebuild or commit
`warehouse.duckdb`, even though the runner already has everything needed to
do so (it runs `extract.py`→`clean.py`→`load.py` in the same job).

**Why (option (a), not (b)):** `warehouse.duckdb` is a build artifact —
`README.md` and `.gitignore` already say so for local runs, and this
workflow doesn't special-case that. Committing a rebuilt binary DuckDB file
every month would (1) contradict the existing "generated, not committed"
rule for everyone else who runs the pipeline locally — a second, CI-only
exception to the same rule is confusing, not simplifying; (2) bloat repo
history with a full binary diff every month, since DuckDB files don't diff
usefully in git; (3) create a false impression that the committed
`warehouse.duckdb` is always current, when anyone with local uncommitted
data changes would immediately diverge from it anyway. The tradeoff:
after a CI run updates `raw/`, the warehouse isn't automatically
queryable until someone runs `python src/load.py` — a few seconds, and
the same step a local contributor already runs after `git pull`.

## Open risk: CGD returned HTTP 403 from the GitHub Actions runner IP — NOT closed, needs monitoring

The workflow was actually triggered live (`workflow_dispatch`, run
[29034793774](https://github.com/Punge089/isap-data-engineer/actions/runs/29034793774),
2026-07-09). Both `detect.py` and `download.py` got
`HTTPError: 403 Client Error: Forbidden` fetching CGD's listing page —
**from GitHub's hosted-runner IP (Azure eastus)**. The same URL returns a
normal 200 with real content from the local dev machine every time it's
been tried. This is a different failure mode than anything seen locally,
and matches the kind of IP-range blocking government sites sometimes apply
to cloud/datacenter traffic — exactly the risk `PROJECT_SPEC.md §11`
already named ("โดนบล็อค IP"), now concretely observed for the first time.

**First problem this exposed, since fixed:** that first run finished green
(22s, no action taken — correct, since nothing should happen on a failed
check), but a real "nothing new" month would have looked *exactly* the
same in the Actions list — both leave the two conditional steps skipped,
both show a plain green checkmark. A persistent IP block would have been
invisible, blending into normal no-op months indefinitely. Fixed by adding
a "Flag CGD check failures distinctly from 'nothing new' months" step:
fails the job (`exit 1` + an `::error::` annotation) whenever
`download.py`'s CGD line indicates the check itself didn't complete
(`could not fetch` / `no report rows found`), leaving `nothing new to
download` / `downloaded new file` (and the rarer duplicate-hash-skip
message) to pass through as the legitimate non-failures they are.
**Re-triggered live to prove it** (run
[29035432857](https://github.com/Punge089/isap-data-engineer/actions/runs/29035432857)):
against the same real 403, the run now shows red ✗ with the annotation
`CGD check did NOT complete this run (this is a FAILED check, not a
normal 'nothing new' month): CGD: could not fetch listing page
(HTTPError: 403 ...)` — confirmed via the GitHub API that this still
correctly took no action (no pipeline run, no commit).

**What's genuinely still unverified:** this is two data points from two
runs made minutes apart, not proof of a pattern. It is not yet known
whether CGD blocks GitHub Actions' IP ranges consistently (which would
mean this workflow's CGD half never succeeds automatically, only ever
detecting new files from a local machine or a self-hosted runner) or
whether this was a one-off/transient response. Don't assume either
conclusion — watch the first several real scheduled runs (now that a
persistent block would actually show up as a red ✗ in the Actions tab,
instead of silently) before deciding this needs a workaround (e.g. a
self-hosted runner, or a proxy — both add real complexity, not to be
reached for until the block is confirmed consistent).

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

Step 7's LOCAL logic (download + validation) is done — see the table row
above. What's still open:

1. **GitHub Actions monthly cron wrapper** (`PROJECT_SPEC.md §9`) — a thin
   YAML file that runs, in order: `extract.py` → `clean.py` → `load.py` (if
   there's new data) and separately `detect.py`/`download.py` on a schedule.
   Nothing about this needs new Python logic; it's wiring existing,
   already-tested scripts into a workflow file.
2. Once the cron exists, the full loop (detect → download → validate →
   extract → clean → load) should be run for real against a genuinely new
   CGD file the next time one is published (currently: nothing new as of
   this writing) — everything up to that point has only been proven via
   fixtures/mocks for the "new file" path, and live for the "nothing new"
   path.
3. Then Step 8 (tests — much of the suite already exists, see the table
   row above) and Step 9 (senior suggestions + docs + interview prep).

Follow the same per-step format (files / code / commands / expected
output / test / explain) as Steps 0-7.

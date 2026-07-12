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
| 1 — EDA & profiling | ✅ Done | See commit `Step 1: EDA & data profiling...`. Findings in `reports/eda_cgd.txt` / `reports/eda_ocsc.txt` — read before re-profiling anything. |
| 2 — Warehouse DDL | ✅ Done | `sql/schema.sql` + `src/init_db.py` + `tests/test_schema.py` (8 cases, green on duckdb 1.5.4/pytest 8.4.2). `dim_date.date_natural_key` (UNIQUE) enforces one row per report_date/fiscal_year, plus a CHECK guarding the BE/CE conversion. `dim_expense_type.is_leaf` guards 'รวม' from double-counting. **Amended in Step 4:** `disbursed_pct`/`share_pct` loosened from `NOT NULL` to nullable — see "Edge case history" below. |
| 3 — Extractor | ✅ Done | `config/{cgd,ocsc}.yaml` + `src/extract.py` + `tests/test_extract.py` (5 cases). Writes `staging/cgd_disbursement.csv` (24 rows) and `staging/ocsc_workforce.csv` (25 rows, hierarchy tagged at extraction). **Correction:** OCSC is 25 rows not 29 (1 total + 2 subtotal + 22 leaf) — config ranges were already right, only the count claim was off. Added missing `PyYAML` pin. No cleaning here — total/footnote rows excluded by range, text not yet `.strip()`-ed (Step 4's job). |
| 4 — Cleaner/transformer | ✅ Done | `src/clean.py` + `tests/test_clean.py` (7 cases). Writes `staging/cgd_disbursement_clean.csv` (72 rows, unpivoted) and `staging/ocsc_workforce_clean.csv` (25 rows). Recomputes `disbursed_pct`/`share_pct` from raw numbers, never trusts Excel's percent (verified matching). **Divide-by-zero: returns NULL, not `inf`/crash** — not reachable in today's data, covered by a synthetic-row test. `is_leaf`: CGD from a fixed expense-type set, OCSC from `hierarchy_level == 2`. `parent_category` left as plain stripped text — resolving to a key is Step 5's job once `dim_personnel_category` exists. |
| 5 — Loader | ✅ Done | `src/load.py` + `tests/test_load.py` (6 cases). Idempotent load via `ON CONFLICT DO NOTHING` — **proven by running the real loader twice and diffing row counts**: `dim_date` 2, `dim_ministry` 24, `dim_expense_type` 3, `dim_personnel_category` 25, `dim_source` 2, `fact_disbursement` 72, `fact_workforce_summary` 25, identical both runs. **Schema fix required:** `dim_source` had no natural-key UNIQUE constraint — added `file_hash UNIQUE`. **New rule, not in any config:** `fiscal_year_be` derived from `report_date` via standard Thai Oct–Sep FY cutover (`thai_fiscal_year_be()`), tested both directions — **only checked against one real report (mid-year), re-verify once an Oct–Dec report appears.** |
| 6 — Latest-file detector | ✅ Done | `src/detect.py` + `tests/test_detect.py` (13 cases) + 3 real saved HTML fixtures. **Fixed the machine's actual TLS bug** (Norton re-signs HTTPS locally; added `pip-system-certs`) rather than working around it — confirmed by running unmodified `detect.py` live. **CGD: fully works, live-verified** — real 200, correct "nothing new" matching the manifest. **OCSC: two different real responses seen live, both real, neither supersedes the other** — see "Open risk" below; either way, manual fallback is correct (yearly cadence, low impact). **Bug fixed:** `load_known_cgd_date()` was taking the *first* matching manifest entry, not the latest — fixed to `max()`, proven order-independent. **New info for Step 7:** CGD links are `javascript:openDownload(...)`, not plain hrefs — the real URL is the 3rd argument. |
| 7 — Downloader + validation (local logic; GH Actions cron itself pending) | ✅ Done | `src/download.py` + `src/validate_structure.py` + 19 tests, all green. `download_cgd()` extracts the real URL from the JS href, unwraps a ZIP-wrapped response if present (see "Bug found and fixed" below), hashes bytes, appends (never overwrites) a manifest entry only if the hash is new. **Live-verified twice now** (see that section) — both the "nothing new" path and, since the ZIP-unwrap fix, the real download path against a genuinely fresh live response. `download_ocsc()` refuses immediately, tested to make zero network calls. `validate_structure.py` checks 8 header anchors + total-row label before `extract.py` parses anything — tested against 5 mangled fixtures (all raise) plus the real file (passes). OCSC has no structure validation — deliberate, since there's no automated OCSC download path yet. **Two ordering bugs fixed:** `CgdReport` refactored to a `NamedTuple` to carry `download_href`; `load_manifest()`'s dict comprehension silently kept whichever entry iterated last — fixed to explicit `max()`. **GitHub Actions YAML is a separate, not-yet-built follow-up.** **Known, accepted:** file-write + manifest-append aren't atomic — an interrupted run just redownloads next time (dedup is by hash, not a corruption risk). |
| 8 — Tests | ⬜ Not started | Much already exists (66 tests across the files above) — this step fills gaps (e.g. one true end-to-end smoke test) and organizes/documents the suite. |
| 9 — Suggestions to Senior + docs + interview prep | ⬜ Not started | |

## Locked decisions — do not re-litigate these

- **Warehouse engine:** DuckDB (single file `warehouse.duckdb`)
- **Scheduler:** GitHub Actions, monthly cron
- **Scope:** core only — `fact_disbursement` (CGD sheet `2.กระทรวง`) +
  `fact_workforce_summary` (OCSC sheet `12`). Stretch sheets (`17-29`,
  `3.หน่วยงาน`) are explicitly deferred, not forgotten.

## Important findings from Step 1 that affect design (already reflected in PROJECT_SPEC.md)

1. **CGD `2.กระทรวง`:** the total row (`รวม`) shifts its label from column 1
   to column 0, and its ministry_code cell is a stray space, not `None`.
   Detect this row by pattern, not by null-checking.
2. **CGD `2.กระทรวง`:** `แผนการใช้จ่าย` (spending plan) is 0 for 100% of
   ministries — carry through as-is, don't drop the column.
3. **CGD `2.กระทรวง`:** zero live formulas, unlike sheet `1.สรุปภาพรวม` in the
   same workbook — don't assume one sheet's formula status for the whole file.
4. **OCSC sheet `12`:** a verified 2-level hierarchy (1 grand total + 2
   subtotals + 22 leaf), not a flat list. `PROJECT_SPEC.md` §4.2 already
   has the fix (`hierarchy_level`, `parent_category_key`, `is_leaf`).
5. **OCSC sheet `12`:** one category name has trailing whitespace
   (`'องค์กรอิสระตามรัฐธรรมนูญ '`) — must `.strip()` all text fields.

## Edge case history: divide-by-zero in the derived `_pct` columns — CLOSED in Step 4

`disbursed_pct`/`share_pct` divide by a value that's *usually* non-zero
(verified: not reachable in today's data), but Step 2's DDL originally
declared both `NOT NULL`, which would crash the loader the day it
happened. Step 4 decided: store `NULL` on a zero denominator, not
`inf`/`NaN`/a crash — required loosening both columns to nullable in
`sql/schema.sql`. If you touch that DDL again, don't reintroduce
`NOT NULL` without also changing `clean.py`.

## Bug found and fixed: CGD's download link sometimes serves a ZIP, not a bare .xlsx — CLOSED 2026-07-12

Found by deliberately testing the real, live `detect.py` → `download.py`
path end-to-end (throwaway sibling copy of the repo, manifest date spoofed
old to force a "new file" branch — never touched the real repo). CGD's
actual download URL returned a **ZIP archive containing a dated
subfolder** (`2026.07.03/2026.07.03.xlsx`), not the bare `.xlsx`
`download_cgd()` assumed. It saved those raw response bytes straight to
`raw/cgd/2026_07_03.xlsx` — a zip-of-an-xlsx, not a valid workbook —
so `extract.py`'s `load_workbook()` failed immediately
(`KeyError: '[Content_Types].xml'`).

**Why every previous test missed this:** `fake_new_cgd_report.xlsx` (the
existing "new file" fixture) is plain placeholder bytes, never
zip-wrapped, so it could never have exercised this path. And the one
prior live `download_cgd()` run (Step 7, 2026-07-09) hit the "nothing
new" branch and never actually wrote a file — so the real file-write path
had genuinely never run against a real network response until this test.

**Fix:** new `unwrap_response_bytes()` in `download.py` — checks the
response bytes with `zipfile.is_zipfile()`; if it's a ZIP, finds the
`.xlsx` entry inside and returns its bytes (raises loudly if a ZIP has no
`.xlsx` entry); a plain `.xlsx` response passes through unchanged. Called
once, right after the HTTP response, before hashing/saving/appending —
so every downstream step (sha256, `raw/cgd/*.xlsx`, the manifest entry)
uses the real unwrapped bytes.

**Verified two ways, not just one:**
1. **New fixture** — `tests/fixtures/fake_new_cgd_report_zip_wrapped.xlsx`,
   a real ZIP mirroring the exact structure found live (dated subfolder +
   a genuinely valid, openable inner workbook, unlike the old placeholder
   fixture). New tests assert the unwrap logic extracts the right bytes,
   passes plain `.xlsx` through unchanged, raises on a ZIP with no
   `.xlsx` inside, and that a full `download_cgd()` run against this
   fixture saves a valid, `load_workbook()`-openable file. Old
   fixture/tests kept as-is, not deleted.
2. **Re-run against the real live site** (same throwaway-copy method,
   after the fix): `detect.py` again correctly reported "new file found —
   2026-07-03" against the spoofed-old manifest date. `download.py`
   fetched the real live response, unwrapped it, and computed
   sha256 `309ad096e8e1...` — an **exact byte-for-byte match** to the hash
   already recorded as correct in the real repo's manifest (verified
   independently in the prior investigation by manually unzipping and
   hashing). Before the fix this hash would have been computed on the
   raw zip container and would never have matched. It correctly hit the
   "duplicate content, already have it" path instead of writing a second
   copy — proof the fix reconstructs the identical real file from the
   real live response, using the exact same `file_bytes` value that the
   "new file" branch would have written to disk. `extract.py → clean.py →
   load.py` re-run against the scratch copy afterward, same real row
   counts as documented elsewhere in this file (`dim_ministry` 24,
   `fact_disbursement` 72, etc.) — the pipeline was never actually broken,
   only the raw download step.

Test count: 57 → 61 (3 new `unwrap_response_bytes()` unit tests + 1 new
full-flow test using the zip-wrapped fixture).

## Open risk: OCSC detection may be non-deterministic — NOT closed

Two live requests to OCSC's listing page, made while building Step 6, got
two different real responses from the same URL:

1. **Blocked** — Cloudflare managed JS challenge, HTTP 403, "Just a
   moment...". Saved: `tests/fixtures/ocsc_cloudflare_challenge.html`.
2. **Not blocked** — clean HTTP 200, genuine WordPress/Elementor HTML, no
   challenge. Saved: `tests/fixtures/ocsc_real_page_no_file_links.html`.

Neither is treated as superseding the other — both are real. The honest
read is that Cloudflare's challenge triggers sometimes and not other
times against the same page, for reasons not investigated here (rate
limiting, risk scoring, session state, or something else).

**Why this doesn't change the fallback:** even in the "not blocked" case,
the page still has zero scrapable file links (JS-rendered widget) — so
automated detection fails either way, just for different reasons.

**What not to do:** don't assume the block is gone because one later
request got through, and don't assume it's permanent because one earlier
request got blocked. `check_ocsc()` must handle both outcomes without
crashing on either.

## Investigated: alternate OCSC endpoints (permalink, REST API) — CLOSED, still not automatable

Checked whether OCSC could be automated via the direct post permalink or
the WordPress REST API instead of the JS-rendered listing page. Result:
Cloudflare blocks at the edge/WAF level — identical 403 challenge across
the listing page, the permalink, and the REST API, meaning the block is
keyed to request characteristics (not JS-executing, likely IP/rate/
fingerprint-based), not to which URL path is requested. Rules out "try a
different endpoint" as a fix — even a hypothetically-static endpoint
would still be blocked. Manual check remains the only viable approach for
OCSC, now confirmed across 3 independent endpoint types.

## Decision: the monthly CI workflow does NOT commit warehouse.duckdb — CLOSED

`.github/workflows/monthly_check.yml` only commits `raw/manifest.json` and
any new `raw/cgd/*.xlsx`. It does not rebuild or commit
`warehouse.duckdb`, even though the runner could.

**Why:** `warehouse.duckdb` is a build artifact per `README.md`/
`.gitignore` — committing a rebuilt binary every month would (1)
contradict that rule for everyone else, (2) bloat repo history with
undiffable binary changes, (3) falsely imply the committed file is always
current. Tradeoff: after CI updates `raw/`, someone still needs to run
`python src/load.py` to refresh the warehouse — the same step a local
contributor already runs after `git pull`.

## Open risk: CGD returned HTTP 403 from the GitHub Actions runner IP — NOT closed

Triggered live (`workflow_dispatch`, run
[29034793774](https://github.com/Punge089/isap-data-engineer/actions/runs/29034793774),
2026-07-09). Both `detect.py` and `download.py` got `403 Forbidden`
fetching CGD's listing page **from GitHub's hosted-runner IP** — the same
URL returns 200 from the local dev machine every time. Matches the
IP-range blocking risk `PROJECT_SPEC.md §11` already named.

**Problem this exposed, since fixed:** a failed fetch and a genuine
"nothing new" month looked identical (green checkmark) in the Actions
list — a persistent block would have been invisible. Fixed by adding a
step that fails the job loudly (`exit 1` + `::error::`) whenever the CGD
check itself didn't complete, leaving real non-failures (nothing new /
downloaded / duplicate-hash-skip) to pass through. **Re-triggered live to
confirm** (run
[29035432857](https://github.com/Punge089/isap-data-engineer/actions/runs/29035432857)):
now shows red ✗ with a clear annotation, and still took no action.

**Still unverified:** whether CGD blocks GitHub Actions' IPs consistently
or this was a one-off. Watch the first several real scheduled runs before
reaching for a workaround (self-hosted runner, proxy — both add real
complexity, not worth it until the block is confirmed consistent).

## Second automation path: Windows Task Scheduler — CLOSED, confirmed working 2026-07-11

GitHub Actions' CGD half is still blocked by IP filtering (above, still
open) — this adds a **second, independent trigger** for the same
`python src/detect.py` check, running from this local machine.

**What was built:** a scheduled task `ISAP Monthly CGD Check` (monthly,
day 1, 08:00) running `scripts\run_monthly_cgd_check.bat`, which runs
`.venv\Scripts\python.exe src\detect.py >> logs\detect_log.txt 2>&1`
(batch wrapper needed because Task Scheduler actions don't support `>>`
directly).

**Gotcha hit and fixed:** `schtasks /create /tr "<quoted path>"` silently
truncates the action at the first space in a path — and this repo's path
always has one (`...\ISAP Project\...`). It doesn't error at creation
time, only at run time (`FILE_NOT_FOUND`). Confirmed via the task's real
CIM object, not just schtasks' own (misleading) text output. Fixed by
registering the task against the batch file's 8.3 short path instead of
fighting the quoting. **Known limitation:** that short path is specific
to this machine/folder — moving the repo means re-registering the task.

**Live-verified:** triggered via `schtasks /run`, polled `Last Result`
until `0`. `logs/detect_log.txt` gained the expected two new lines
(verified by line count). An earlier attempt (before the short-path fix)
genuinely failed with `STATUS_CONTROL_C_EXIT` — recorded here rather than
hidden.

**Proves:** a second, real, working trigger path independent of GitHub's
runner IPs. **Does not:** fix the GitHub Actions 403, or make OCSC
automatable — it's a mitigation, not a replacement for resolving either.

## Task Scheduler now runs the full chained pipeline, not just detect.py — CLOSED 2026-07-12

Previously Task Scheduler only ran `detect.py` (informational check only,
never downloaded/loaded anything) — a real gap vs. GitHub Actions' YAML,
which chains detect → download → extract → clean → load. Closed by adding
`src/run_monthly_pipeline.py`, a `main()` mirroring the YAML's logic:
print both `detect.check_cgd()`/`check_ocsc()` results (OCSC informational
only, never gates); exit 1 loudly if the CGD check itself failed
(`could not fetch` / `no report rows found`) rather than looking like a
normal no-op month — same principle as the YAML's "Flag CGD check
failures" step, applied locally; if `detect.check_cgd()` says nothing
new, stop (exit 0); if it says a new file exists, call
`download.download_cgd()`, and only run `extract.run_cgd()` →
`clean.run_cgd()` → load (`load.ensure_schema` + `load.load_cgd` against
a fresh connection) if that download actually saved a new file (not a
dedup-skip). `scripts\run_monthly_cgd_check.bat` updated to call this
script instead of `detect.py` directly, same log redirection.

**One deliberate difference from the YAML, worth knowing about:** the
YAML always runs `download.py` unconditionally and lets it do its own
independent freshness check (that's *why* `download_cgd()` re-fetches the
listing page itself rather than trusting an earlier step). This script
instead gates the download call on `detect.check_cgd()`'s result, to
avoid a second redundant live fetch when detect already knows there's
nothing to do. Functionally equivalent in every case observed so far, but
if `detect.check_cgd()` and `download.download_cgd()` ever disagreed
(e.g. a report appears between the two calls), this script would miss it
until the next run, where the YAML's design would not. Not fixed here
since it wasn't asked for — flagging so it isn't mistaken for an
oversight.

**Tested two ways:**
1. **Mocks first** — `tests/test_run_monthly_pipeline.py`, 5 cases (4
   branches, one parametrized): nothing-new (only detect called, exits
   0); new file + successful download (extract→clean→load run in that
   exact order); new file + dedup-skip (pipeline does NOT run); fetch
   failure, both message shapes (exits 1, nothing downstream touched).
   `detect`, `download`, `extract`, `clean` are monkeypatched at the
   module level; the load step is isolated behind a small
   `run_load_cgd()` helper so tests don't need a real duckdb connection.
2. **One real live trigger** — `schtasks /run /tn "ISAP Monthly CGD
   Check"`, polled until done.

**Bug found during that live trigger, unrelated to the new script itself,
and fixed:** the task's registered action still pointed to
`C:\Users\MSII\Desktop\...` (the short path from the original Step 7
Task Scheduler setup) — dead, because OneDrive's Known Folder Move has
since relocated Desktop to `C:\Users\MSII\OneDrive\Desktop\...`. First
live trigger after the script swap failed with `LastTaskResult=1` and
`logs/detect_log.txt`'s mtime hadn't moved at all — the task never even
launched the batch file. This is exactly the "known limitation" already
flagged in the original Task Scheduler entry above (short path is
tied to one machine/folder; moving the repo needs re-registration) — it
had just never actually triggered until now. Fixed by generating a fresh
8.3 short path for the current real location and applying it via
`Set-ScheduledTask -Action (New-ScheduledTaskAction ...)` (PowerShell's
`ScheduledTasks` module) rather than `schtasks /change /tr`, which
prompted for an interactive password re-entry and had to be aborted.
Re-triggered after the fix: `LastTaskResult=0`, `logs/detect_log.txt`
grew from 4 to 7 lines with the expected content (CGD "nothing new",
OCSC's informational 403, and the pipeline's own "nothing new this month
-- pipeline not run" line) — confirmed by real line count and mtime, not
assumed.

**What this proves / doesn't:** proves Task Scheduler now runs the same
full chain as GitHub Actions when triggered, and that the trigger
mechanism itself works again after the stale-path fix. Does not exercise
the download→extract→clean→load branch live, since there was genuinely
nothing new to download at trigger time (same real site state documented
elsewhere in this file) — that branch is covered by mocks only until a
real new CGD file appears (see "Open item" below).

## Open item: extract→clean→load against a genuinely new CGD file is still fixture-tested only

Checked for a real new CGD file twice, a week apart (**2026-07-09**,
**2026-07-10**) using both `detect.py` and `download.py` locally. Both
times the latest report on the live site was still **2026-07-03**,
already in the manifest — nothing forced or faked.

**This is a timing limitation, not a code gap.** The "new file found"
path has real fixture-based test coverage but has never run end-to-end
against actual new data. **The moment a real new file appears, note the
date here and run the full chain for real** — worth calling out
explicitly in the interview as the one piece validated as soon as real
data allowed it.

## Environment notes

- Repo layout, `.gitignore` policy, and reasoning are in `README.md` —
  read those instead of asking the author to re-explain.
- `requirements.txt` is version-range-pinned, verified against what's
  actually importable. `duckdb`/`pytest` were not verified in the
  environment that built Steps 0-1 — if either fails to install, debug it
  for real rather than assuming the pin is wrong.
- Scripts assume they're run from the repo root. This bit the author once
  already during Step 1 — flag it in new scripts.

## Next action

Step 7's local logic (download + validation) is done. Still open:

1. **GitHub Actions monthly cron wrapper** (`PROJECT_SPEC.md §9`) — a thin
   YAML wiring `extract.py`→`clean.py`→`load.py` plus `detect.py`/
   `download.py` on a schedule. No new Python logic needed.
2. Once the cron exists, run the full loop (detect → download → validate
   → extract → clean → load) for real against a genuinely new CGD file
   the next time one is published.
3. Then Step 8 (tests) and Step 9 (senior suggestions + docs + interview prep).

Follow the same per-step format (files / code / commands / expected
output / test / explain) as Steps 0-7.

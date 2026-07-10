# Interview Demo Script

Everything below runs against real, already-built artifacts — nothing is
staged or faked for the demo. `demo/run_demo.py` connects read-only to the
real `warehouse/warehouse.duckdb`. If asked "is this real data," the
answer is yes, and the CHECK-constraint step (Step 3e) proves the schema's
own rules by triggering a real failure live, not by assertion.

Before the interview: run `python src/load.py` once so the warehouse
reflects the latest data, and confirm `warehouse/warehouse.duckdb` exists.

---

## Step 1 — `git log --oneline`

**Run:**
```
git log --oneline
```

**Say:** "Built step by step over 10 commits — repo skeleton, EDA, schema,
extractor, cleaner, loader, detector, downloader, CI wrapper — each one
runnable and tested before the next started. Not one dump at the end."

**Proves:** ข้อ 5 (GitHub repo — real incremental work, verifiable history).

---

## Step 2 — `python -m pytest -v`, let it finish green

**Run:**
```
python -m pytest -v
```

**Say:** "57 tests. Each one exists because of a real problem this project
actually hit — double-counting, a missing UNIQUE constraint, a Cloudflare
block, an IP-range block on GitHub's runners — not boilerplate coverage
padding. If you pick any test name, I can tell you the bug it's guarding
against."

**Proves:** ข้อ 3a (code quality) — and sets up credibility for everything
that follows.

---

## Step 3 — `python demo/run_demo.py`

Run it, then narrate each section as it prints. Query numbers below match
the script's own `print()` headers.

- **Query 1 (row counts):** "Here's what's actually in the warehouse right
  now — not a mockup." Quick, don't linger.

- **Query 2a/2b/2c (CGD double-count):** "Two ways to sum the same
  column. Naive: no filter, sums recurring + capital + total together.
  Correct: filtered to `is_leaf = true`. The naive number is exactly 2x
  the correct one — because `รวม` (total) in the source data literally
  *is* recurring+capital added a second time, not a third independent
  figure. `is_leaf` is a single boolean column that prevents any analyst
  from silently double-counting the entire national budget."

- **Query 3 (OCSC double-count):** "Same class of bug, found first —
  this is the one that shaped the schema. Naive sum is ~3x the real
  figure, because the sheet has 1 grand total + 2 subtotals + 22 leaf
  categories all mixed into one flat-looking table. Filtered to
  `is_leaf`, the sum matches the grand-total row *exactly* — 3,004,485,
  not approximately. That exact match is the proof, not a coincidence."

- **Query 4 (dim_source lineage):** "Every fact row traces back to an
  exact file and an exact sha256 — not 'a file from around July,' the
  literal bytes. If a number's ever questioned, this is how you'd audit
  it."

- **Query 5 (CHECK constraint, live):** "This copies the warehouse file
  first — never touches the real one — then tries to insert a
  deliberately wrong fiscal-year pair. Watch it actually throw." Let the
  exception print. "The schema enforces its own rules; that's not
  something I'm claiming, it just happened on screen."

**Proves:** ข้อ 1 (warehouse design, live not claimed) + ข้อ 2 (EDA
findings — the hierarchy and double-counting risks were *found*, not
assumed, and the schema is the direct fix).

---

## Step 4 — GitHub Actions tab (open in browser)

Navigate to the repo's Actions tab. Show the run history — **including
the red failed run**, not just green ones.

**Say:** "This failed run is the system working correctly, not a bug I'm
apologizing for. CGD's server blocks requests from GitHub's shared runner
IP ranges — confirmed 3 times now, always the same 403. Early on, that
failure looked *identical* to a normal 'nothing new this month' — both
just skip the rest of the pipeline. I added a step that tells them apart:
if the check itself couldn't complete, the job now fails loudly with a
clear annotation, instead of quietly looking like eleven other normal
no-op months. You're looking at proof that distinction works, not a
description of it."

**Proves:** ข้อ 3b (monthly check exists and runs) + real infrastructure
judgment for ข้อ 4 (suggestions to senior — this *is* the kind of
observability call a senior DE would want to see made, unprompted).

---

## Step 5 — only if time permits

Open `src/validate_structure.py` and `src/detect.py` briefly. Offer:
"Happy to walk through any file in here line by line if useful."

---

## Cheat sheet: hardest anticipated questions

**"Why can't OCSC be automated too?"**
Two independent real blockers, not one: it's sometimes behind a
Cloudflare JS challenge, and *even when that's not triggered*, the report
list is rendered by a JavaScript widget that's simply not in the page's
HTML — confirmed by fetching the real page and finding zero file links in
it. Full record in `HANDOFF.md`'s OCSC sections.

**"Why only 2 sheets out of ~80 combined?"**
Scoped deliberately, not from running out of time — `PROJECT_SPEC.md §3`
names the other sheets explicitly as out-of-scope with reasons (chart-only
pages, no shared join key between sources, one sheet with a 4-level
header that's a known trap). Junior-DE judgment is knowing what *not* to
build, not building everything.

**"What's this failed GitHub Actions run about?"**
CGD's server 403s requests from GitHub's hosted-runner IPs specifically —
works every time from a local machine, fails every time (3/3 so far) from
GitHub Actions. Open, monitored risk, documented in `HANDOFF.md`, with a
step added specifically so it can't hide as a silent no-op.

**"What happens right at the fiscal-year boundary (Sept 30 / Oct 1)?"**
The BE/CE conversion direction is locked in by a dedicated test
(`test_thai_fiscal_year_be_cutover_direction`), but every real report seen
so far has been deep mid-year — the rule has never been checked against
an actual report published Oct-Dec. Flagged explicitly in `HANDOFF.md` as
unverified, not swept under the rug.

*(For the full version of any of these, `HANDOFF.md` has the complete
record — findings, fixes, and what's still open.)*

---

## Optional visual demo (if time and setup allow)

This is **DuckDB's own official UI extension** (ships from DuckDB Labs
as part of the DuckDB CLI, not a custom tool built for this project). It
opens a browser-based catalog browser and SQL notebook against the real
warehouse file. Use it **after** Steps 1-5 above, as a visual bonus —
the terminal demo is the primary, already-fully-tested proof and stands
on its own without this.

**Prerequisites (one-time, already done on this machine):**
- DuckDB CLI installed via `winget install --id DuckDB.cli --source winget`
  (separate binary from the `duckdb` Python package in `requirements.txt`).
- Confirm nothing else has `warehouse/warehouse.duckdb` open — DuckDB is
  single-writer, so a second connection (VS Code extension, a running
  `python demo/run_demo.py`, another `duckdb` CLI instance) will make the
  UI fail to start with an "already open" IO error.

**Run:**
```
duckdb warehouse/warehouse.duckdb -ui
```

**What this proved, live, on this machine (2026-07-11):**
- Opens `http://localhost:4213/` automatically in the default browser
  (Brave, in this test) and the server answers `HTTP 200`.
- Before launch, `SHOW TABLES;` against the same file confirmed all 7
  real tables: `dim_date`, `dim_expense_type`, `dim_ministry`,
  `dim_personnel_category`, `dim_source`, `fact_disbursement`,
  `fact_workforce_summary` — the same catalog the UI's left-hand
  browser reads from, since it's the identical file.
- Once the UI is running, the file is held open single-writer by that
  process (verified: a second CLI connection to the same path fails
  with "file is already open in ... duckdb.exe (PID ...)"). That lock
  is itself proof the UI is bound to the real warehouse file, not an
  empty or mock one.

**In the notebook cell, try the CGD `is_leaf` double-count query:**
```sql
SELECT SUM(disbursed) AS naive_sum FROM fact_disbursement;

SELECT SUM(disbursed) AS correct_sum
FROM fact_disbursement f
JOIN dim_expense_type e ON e.expense_type_key = f.expense_type_key
WHERE e.is_leaf = true;
```

**Expected numbers (captured from `python demo/run_demo.py` on
2026-07-11, terminal-verified, use these to confirm the UI matches):**
```
GRAND TOTAL -- naive (no filter):        3,497,480.03 ล้านบาท
GRAND TOTAL -- correct (is_leaf = true):  1,748,740.01 ล้านบาท
naive / correct ratio:                    2.0000
```
If the UI's notebook returns these same two numbers, that's the visual
confirmation this bonus step is for.

**Honest caveat:** the install, launch, port binding, HTTP response, and
file-lock proof above were verified directly on this machine. Actually
clicking through the catalog browser and typing the query into the
notebook cell requires a human at the keyboard (or a browser-automation
tool this assistant didn't have available) — do that part live, and
don't present it as pre-verified beyond what's listed above.

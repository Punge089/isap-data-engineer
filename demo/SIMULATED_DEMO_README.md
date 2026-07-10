# Simulated "new file" demo (ข้อ 3c) — read this before presenting it

**This is a controlled simulation, not a live web download.** As of this
writing (2026-07-11), CGD has not published a report newer than
2026-07-03 — checked repeatedly, see `HANDOFF.md`'s "Open item:
extract→clean→load against a genuinely new CGD file is still fixture-tested
only". This demo exists to prove the ingestion path end-to-end *before* a
real new file happens to show up, using a manually fabricated stand-in.

## What was actually done

Everything below ran in a **throwaway copy of the whole repo**, at a
sibling folder (`isap-data-engineer-demo/`), created outside git (no
`.git`, no `.venv` copied in) and never committed. The real repo's
`raw/cgd/` (still just `2026_07_03.xlsx`) and `raw/manifest.json` (still 2
entries) were never touched — confirmed with `git status` after the fact.

1. Loaded the real `raw/cgd/2026_07_03.xlsx` with `openpyxl`, in the copy
   only, and:
   - Changed the report's date cell (`2.กระทรวง`, row 2 / index 1) from
     *"ตั้งแต่ต้นปีงบประมาณ จนถึงวันที่ 3 กรกฎาคม 2569"* to
     *"...จนถึงวันที่ 10 กรกฎาคม 2569"* — a later, plausible date, title
     row left untouched.
   - Nudged `recurring_disbursed` / `capital_disbursed` (and recomputed
     `total_disbursed = recurring + capital`, matching the real invariant)
     for 3 ministries: กระทรวงคมนาคม (+50 / +20), กระทรวงพลังงาน
     (+100 / +0), กระทรวงทรัพยากรธรรมชาติ และสิ่งแวดล้อม (+0 / +75).
   - Saved as `raw/cgd/2026_07_10_SIMULATED.xlsx`.
2. Appended one entry to the copy's `raw/manifest.json`: same
   `source`/`source_name_th`/`source_url` as the real CGD entry,
   `report_date: "2026-07-10"`, the new file's real sha256, and
   `"downloaded_by": "manual-demo-simulated"` so it's unmistakably not a
   real download.
3. Ran the **real, unmodified** `src/extract.py` → `src/clean.py` →
   `src/load.py` (the copy's own files, byte-identical to the real repo's
   at copy time) against this. Real terminal output:

   ```
   === extract.py ===
   cgd_disbursement.csv: 24 rows
   ocsc_workforce.csv: 25 rows
   === clean.py ===
   cgd_disbursement_clean.csv: 72 rows (from 24 raw rows)
   ocsc_workforce_clean.csv: 25 rows
   === load.py ===
   dim_date: 3 rows
   dim_ministry: 24 rows
   dim_expense_type: 3 rows
   dim_personnel_category: 25 rows
   dim_source: 3 rows
   fact_disbursement: 144 rows
   fact_workforce_summary: 25 rows
   ```

   Before this run, the copy's warehouse (a copy of the real, already-built
   one) had `dim_date: 2`, `dim_source: 2`, `fact_disbursement: 72` — the
   same numbers documented in `HANDOFF.md`'s Step 5 row. After: `dim_date`
   and `dim_source` each gained exactly one row (the new report date, the
   new file's lineage row), `fact_disbursement` gained exactly 72 new rows
   (24 ministries × 3 expense types, for the new date), and
   `dim_ministry`/`dim_expense_type`/`fact_workforce_summary` were
   unchanged — `ON CONFLICT ... DO NOTHING` correctly reused the existing
   ministry/expense-type dimension rows instead of duplicating them. Direct
   query confirmed the new `fact_disbursement` rows carry exactly the
   tweaked numbers (e.g. กระทรวงพลังงาน `รายจ่ายประจำ` disbursed:
   1367.75 on 2026-07-03 vs 1467.75 on the simulated 2026-07-10 row).
4. **Bonus — broken-file validation, live:** built a second fake file (a
   copy of the real one with the `กระทรวง` header cell mangled to
   `'MANGLED_HEADER_TEXT'`), saved *outside* `raw/cgd/` so it could never
   be picked up by `extract.py`'s own file-selection glob, and called the
   real `validate_cgd_structure()` directly against it. Real, live
   exception (not a pytest assertion):

   ```
   Caught StructureValidationError, live, exactly as expected:
     2026_99_99_BROKEN.xlsx: header mismatch at row 3, col 1 — expected
     'กระทรวง', found 'MANGLED_HEADER_TEXT'. The sheet's structure may
     have changed; refusing to parse until config/cgd.yaml is reviewed
     and updated to match.
   ```

## What this proves

- The full `extract.py → clean.py → load.py` chain genuinely handles a
  second CGD report appearing: new `dim_date`/`dim_source` rows, 72 new
  `fact_disbursement` rows, existing dimensions correctly reused via the
  idempotent `ON CONFLICT` loader logic — not asserted, actually run and
  observed.
- `validate_structure.py`'s structure guard actually fires against a real
  mangled file, live, with the real error message a maintainer would see —
  not just covered by `tests/test_validate_structure.py`'s mocked cases.

## What this does NOT prove

- Does **not** fix GitHub Actions' CGD 403 (CGD blocking the hosted-runner
  IP range) — that's still open, see `HANDOFF.md`'s "Open risk: CGD
  returned HTTP 403 from the GitHub Actions runner IP".
- Does **not** make OCSC automatable — OCSC's Cloudflare/JS-widget wall is
  unrelated to this and untouched by this demo.
- Is **not** evidence that CGD's real site has published anything new —
  the file is a manual fabrication, clearly marked as such in its own
  manifest entry (`downloaded_by: manual-demo-simulated`) and filename
  (`_SIMULATED`), and lives only in a throwaway, uncommitted copy of the
  repo. The day a real new CGD report appears, re-run the real pipeline
  against it and update `HANDOFF.md`'s open item — this demo is a stand-in
  for that day, not a replacement for it.

## Reproducing this

The throwaway copy this was run against is not committed and may not
exist anymore by the time you read this. To rebuild it: copy the repo
(excluding `.git`, `.venv`) to a sibling folder, then repeat steps 1-4
above against the copy — never against the real `raw/`.

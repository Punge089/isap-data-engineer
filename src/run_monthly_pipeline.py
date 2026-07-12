"""Step 7: Task Scheduler's full pipeline entry point. Mirrors
.github/workflows/monthly_check.yml's detect -> download -> extract ->
clean -> load chain, run locally instead of via GitHub Actions -- see
HANDOFF.md's Task Scheduler entry.

Gating is on detect.check_cgd()'s result, not download.download_cgd()'s
own independent check (unlike the YAML, which always runs download.py and
gates on its output) -- a deliberate simplification for the local path, to
avoid an extra live request when detect already knows there's nothing to
do. See HANDOFF.md for the tradeoff this implies.
"""

from __future__ import annotations

import sys

import duckdb

import clean
import detect
import download
import extract
import load


def run_load_cgd() -> None:
    con = duckdb.connect(str(load.DB_PATH))
    try:
        load.ensure_schema(con)
        load.load_cgd(con)
    finally:
        con.close()


def main() -> int:
    cgd_result = detect.check_cgd()
    print(cgd_result)
    print(detect.check_ocsc())  # informational only, never gates anything

    if "could not fetch" in cgd_result or "no report rows found" in cgd_result:
        print(
            "ERROR: CGD check did NOT complete this run (this is a FAILED "
            f"check, not a normal 'nothing new' month): {cgd_result}"
        )
        return 1

    if "new file found" not in cgd_result:
        print("CGD: nothing new this month -- pipeline not run.")
        return 0

    download_result = download.download_cgd()
    print(download_result)

    if "downloaded new file" not in download_result:
        print("No new file actually saved (see message above) -- pipeline not run.")
        return 0

    extract.run_cgd()
    clean.run_cgd()
    run_load_cgd()

    print("Pipeline complete: new CGD report extracted, cleaned, and loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

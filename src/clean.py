"""Step 4: cleaner/transformer.

Reads staging/cgd_disbursement.csv and staging/ocsc_workforce.csv — the
untouched output of Step 3's extract.py — and produces cleaned,
warehouse-shaped versions. This is where values finally get fixed: strip
whitespace, recompute percentages ourselves, unpivot CGD into long format,
compute is_leaf. Step 3 deliberately did none of this (see extract.py's
docstring); this file is where that boundary ends.

Paths are resolved relative to this file, not the working directory (same
convention as init_db.py / extract.py).
"""

from pathlib import Path
import csv

from extract import STAGING_DIR, write_csv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Maps the wide staging column prefix -> the expense_type_name that will
# become a dim_expense_type row. 'รวม' is the additive rollup of the other
# two (budget_after_transfer_total = recurring + capital), not a 3rd
# independent value — same overcount shape as the OCSC hierarchy, which is
# why it's flagged is_leaf=False here exactly like a non-leaf category.
EXPENSE_TYPE_GROUPS = {
    "recurring": "รายจ่ายประจำ",
    "capital": "รายจ่ายลงทุน",
    "total": "รวม",
}
LEAF_EXPENSE_TYPES = {"รายจ่ายประจำ", "รายจ่ายลงทุน"}

MEASURES = ["budget_after_transfer", "allocated", "spending_plan", "po_reserved", "disbursed"]


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clean_cgd(raw_rows: list[dict]) -> list[dict]:
    """Unpivot each wide ministry row (Step 3's output) into 3 long rows,
    one per expense type, and recompute disbursed_pct from raw numbers.
    """
    cleaned = []
    for row in raw_rows:
        for prefix, expense_type_name in EXPENSE_TYPE_GROUPS.items():
            values = {m: float(row[f"{prefix}_{m}"]) for m in MEASURES}
            budget_after_transfer = values["budget_after_transfer"]
            disbursed = values["disbursed"]

            if budget_after_transfer == 0:
                # Not present in today's data (checked: no ministry has
                # budget_after_transfer == 0 in staging/cgd_disbursement.csv),
                # but nothing upstream guarantees that stays true. Store NULL
                # rather than raising ZeroDivisionError or writing inf/NaN —
                # an analyst sees a missing percentage, not a nonsensical one.
                disbursed_pct = None
            else:
                disbursed_pct = disbursed / budget_after_transfer * 100

            cleaned.append(
                {
                    "ministry_code": row["ministry_code"],
                    "ministry_name": row["ministry_name"],
                    "expense_type_name": expense_type_name,
                    "is_leaf": expense_type_name in LEAF_EXPENSE_TYPES,
                    "budget_after_transfer": budget_after_transfer,
                    "allocated": values["allocated"],
                    "spending_plan": values["spending_plan"],
                    "po_reserved": values["po_reserved"],
                    "disbursed": disbursed,
                    "remaining": budget_after_transfer - disbursed,
                    "disbursed_pct": disbursed_pct,
                }
            )
    return cleaned


def clean_ocsc(raw_rows: list[dict]) -> list[dict]:
    """Strip text fields, compute is_leaf from hierarchy_level, and
    recompute share_pct from raw headcounts instead of trusting the
    Excel-reported percent column.

    parent_category is kept as plain (stripped) text, NOT resolved to a
    parent_category_key here: that requires dim_personnel_category rows to
    already exist, and this script never touches the warehouse — it only
    reads/writes CSVs. Resolving text -> key is Step 5's job, once the
    loader has inserted dim_personnel_category and can look keys up.
    """
    cleaned = []
    for row in raw_rows:
        hierarchy_level = int(row["hierarchy_level"])
        parent_category_raw = row["parent_category"]
        cleaned.append(
            {
                "category_name": row["category_name"].strip(),
                "headcount": int(row["headcount"]),
                "hierarchy_level": hierarchy_level,
                "parent_category": parent_category_raw.strip() if parent_category_raw else None,
                "is_leaf": hierarchy_level == 2,
            }
        )

    grand_total_headcount = next(r["headcount"] for r in cleaned if r["hierarchy_level"] == 0)
    for r in cleaned:
        if grand_total_headcount == 0:
            # Same reasoning as disbursed_pct above: NULL, not a crash. Not
            # reachable in today's data (grand total = 3,004,485) but the
            # code shouldn't assume that stays true.
            r["share_pct"] = None
        else:
            r["share_pct"] = r["headcount"] / grand_total_headcount * 100

    return cleaned


def run_cgd() -> Path:
    raw_rows = read_csv(STAGING_DIR / "cgd_disbursement.csv")
    cleaned = clean_cgd(raw_rows)
    out_path = STAGING_DIR / "cgd_disbursement_clean.csv"
    write_csv(cleaned, out_path)
    print(f"{out_path.name}: {len(cleaned)} rows (from {len(raw_rows)} raw rows)")
    return out_path


def run_ocsc() -> Path:
    raw_rows = read_csv(STAGING_DIR / "ocsc_workforce.csv")
    cleaned = clean_ocsc(raw_rows)
    out_path = STAGING_DIR / "ocsc_workforce_clean.csv"
    write_csv(cleaned, out_path)
    print(f"{out_path.name}: {len(cleaned)} rows")
    return out_path


def main() -> None:
    run_cgd()
    run_ocsc()


if __name__ == "__main__":
    main()

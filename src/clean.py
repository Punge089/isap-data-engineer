"""Step 4: cleaner/transformer. Strips/recomputes/unpivots Step 3's raw
staging CSVs into warehouse-shaped rows."""

from pathlib import Path
import csv

from extract import STAGING_DIR, write_csv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Wide staging column prefix -> expense_type_name. 'รวม' is the rollup of
# the other two, not a 3rd independent value -- flagged is_leaf=False.
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
    """Strip text, compute is_leaf, recompute share_pct from raw headcounts.
    parent_category stays plain text -- Step 5's loader resolves the key."""
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
            # Same as disbursed_pct: NULL, not a crash (not reachable today).
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

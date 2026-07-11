"""Step 2: create warehouse/warehouse.duckdb from sql/schema.sql."""

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"
DB_PATH = REPO_ROOT / "warehouse" / "warehouse.duckdb"


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply sql/schema.sql (all IF NOT EXISTS) -- safe on every run."""
    con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    try:
        ensure_schema(con)
        tables = con.execute("SHOW TABLES").fetchall()
    finally:
        con.close()

    print(f"Warehouse ready at {DB_PATH}")
    print("Tables:", [t[0] for t in tables])


if __name__ == "__main__":
    main()

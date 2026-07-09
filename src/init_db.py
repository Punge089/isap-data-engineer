"""Step 2: create warehouse/warehouse.duckdb from sql/schema.sql.

Paths are resolved relative to this file, not the current working
directory, so it works whether you run it from the repo root or not.
"""

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"
DB_PATH = REPO_ROOT / "warehouse" / "warehouse.duckdb"


def main() -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    try:
        con.execute(schema_sql)
        tables = con.execute("SHOW TABLES").fetchall()
    finally:
        con.close()

    print(f"Warehouse ready at {DB_PATH}")
    print("Tables:", [t[0] for t in tables])


if __name__ == "__main__":
    main()

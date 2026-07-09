"""Step 2: create warehouse/warehouse.duckdb from sql/schema.sql.

Paths are resolved relative to this file, not the current working
directory, so it works whether you run it from the repo root or not.
"""

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"
DB_PATH = REPO_ROOT / "warehouse" / "warehouse.duckdb"


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply sql/schema.sql against an already-open connection. Every
    statement in that file is IF NOT EXISTS, so this is safe to call on
    every run — load.py relies on this to guarantee the tables exist
    without requiring init_db.py to have been run first."""
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

#!/usr/bin/env python3
"""Load a fresh TPC-H SF1 database using this project's SQLite CLI.

DBGEN's original .tbl files remain unchanged. Remove the trailing delimiter
into temporary files and import in ASCII mode, preserving literal quotes.
Validate the data before renaming the provisional database to its final name.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "region": (3, 5),
    "nation": (4, 25),
    "part": (9, 200_000),
    "supplier": (7, 10_000),
    "partsupp": (5, 800_000),
    "customer": (8, 150_000),
    "orders": (9, 1_500_000),
    "lineitem": (16, 6_001_215),
}


def dot_quote(path):
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'


def run_sql(sqlite, database, sql):
    result = subprocess.run(
        [str(sqlite), "-batch", "-bail", str(database)],
        input=sql,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="", flush=True)
    # .import can report errors without making the shell exit nonzero.
    if result.returncode or result.stderr.strip():
        raise RuntimeError(result.stderr or f"SQLite exited {result.returncode}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/tpch-sf1/raw")
    parser.add_argument("--db", type=Path, default=ROOT / "data/tpch-sf1/tpch.db")
    parser.add_argument("--sqlite", type=Path, default=ROOT / "build/sqlite-debug/sqlite3d")
    args = parser.parse_args()
    raw, database, sqlite = args.raw.resolve(), args.db.resolve(), args.sqlite.resolve()
    if not sqlite.is_file():
        raise SystemExit(f"SQLite CLI not found: {sqlite}")
    if database.exists():
        raise SystemExit(f"Refusing to overwrite existing database: {database}")
    for table in TABLES:
        if not (raw / f"{table}.tbl").is_file():
            raise SystemExit(f"Missing input: {raw / (table + '.tbl')}")
    database.parent.mkdir(parents=True, exist_ok=True)
    pending = database.with_name(database.name + ".loading")
    # Exclusive creation also protects unfinished imports from another run.
    fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    started = time.monotonic()
    print(f"SQLite: {subprocess.check_output([str(sqlite), '--version'], text=True).strip()}", flush=True)
    print(f"Provisional database: {pending}", flush=True)
    counts = {}
    try:
        with tempfile.TemporaryDirectory(prefix="tpch-import-", dir=database.parent) as temporary:
            commands = [
                ".bail on",
                "PRAGMA journal_mode=DELETE;",
                "PRAGMA synchronous=NORMAL;",
                "PRAGMA cache_size=-65536;",
                "PRAGMA temp_store=FILE;",
                # Verify all foreign keys after the bulk import.
                "PRAGMA foreign_keys=OFF;",
                "BEGIN;",
                (ROOT / "sql/tpch/schema.sql").read_text(),
            ]
            for table, (columns, expected) in TABLES.items():
                normalized = Path(temporary) / f"{table}.tbl"
                count = 0
                with (raw / f"{table}.tbl").open("rb") as source, normalized.open("wb") as target:
                    for count, line in enumerate(source, 1):
                        row = line.removesuffix(b"\n").removesuffix(b"\r")
                        if not row.endswith(b"|") or row.count(b"|") != columns:
                            raise ValueError(f"{table}, row {count}: unexpected delimiters")
                        target.write(row[:-1] + b"\n")
                if count != expected:
                    raise ValueError(f"{table}: expected {expected} SF1 rows, found {count}")
                counts[table] = count
                print(f"Prepared {table}: {count:,} rows", flush=True)
                commands.extend([
                    f".print Importing {table}",
                    f'.import --ascii --colsep "|" --rowsep "\\n" {dot_quote(normalized)} {table}',
                ])
            commands.extend([
                ".print Creating project indexes",
                (ROOT / "sql/tpch/indexes.sql").read_text(),
                "ANALYZE;",
                "COMMIT;",
            ])
            print("Importing all tables, creating indexes, and collecting statistics...", flush=True)
            run_sql(sqlite, pending, "\n".join(commands) + "\n")
        print("Validating loaded row counts...", flush=True)
        for table, (_, expected) in TABLES.items():
            actual = int(run_sql(sqlite, pending, f"SELECT count(*) FROM {table};\n").strip())
            if actual != expected:
                raise ValueError(f"{table}: loaded {actual}, expected {expected}")
        print("Checking database structure...", flush=True)
        if run_sql(sqlite, pending, "PRAGMA quick_check;\n").strip() != "ok":
            raise ValueError("SQLite quick_check failed")
        print("Checking all foreign-key relationships...", flush=True)
        if run_sql(sqlite, pending, "PRAGMA foreign_key_check;\n").strip():
            raise ValueError("Foreign-key violations found")
        q8 = (ROOT / "sql/tpch/q8.sql").read_text()
        print("Running Q8 with official validation parameters...", flush=True)
        result = run_sql(sqlite, pending, q8)
        rows = [line.split("|") for line in result.strip().splitlines()]
        expected_q8 = {1995: 0.03, 1996: 0.04}
        if len(rows) != 2 or {int(y): round(float(v), 2) for y, v in rows} != expected_q8:
            raise ValueError("Q8 differs from the bundled q8.out at its displayed precision")
        print("Q8 agrees with bundled answers/q8.out at its two-decimal precision.", flush=True)
        # Do not replace a database which appeared while this import was running.
        os.link(pending, database)
        pending.unlink()
        elapsed = round(time.monotonic() - started, 2)
        summary = {
            "scale_factor": 1,
            "tables": counts,
            "database_bytes": database.stat().st_size,
            "sqlite_version": subprocess.check_output([str(sqlite), "--version"], text=True).strip(),
            "load_and_validation_seconds": elapsed,
            "quick_check": "ok",
            "foreign_key_violations": 0,
            "q8": result.strip().splitlines(),
            "q8_validation": "matches bundled q8.out to two decimal places only",
            "index_definitions": "sql/tpch/indexes.sql",
            "statistics": "ANALYZE after loading; no artificial statistics",
        }
        summary_path = database.with_suffix(".summary.json")
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Ready: {database} ({database.stat().st_size:,} bytes), {elapsed}s", flush=True)
        print(f"Summary: {summary_path}", flush=True)
    except BaseException:
        print(f"Import did not finish. Inspect the provisional file: {pending}", flush=True)
        raise


if __name__ == "__main__":
    main()

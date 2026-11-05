#!/usr/bin/env bash
# Run from any directory. Reuses existing generated data; never overwrites a DB.
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
mkdir -p logs tools data/tpch-sf1/raw

tool_dir="$project_root/tools/TPC-H V3.0.1/dbgen"
if [[ ! -f "$tool_dir/makefile.suite" ]]; then
    shopt -s nullglob
    archives=("$project_root"/downloads/*TPC-H-Tool.zip)
    if [[ ${#archives[@]} -ne 1 ]]; then
        printf '%s\n' 'Expected one downloaded *TPC-H-Tool.zip in downloads/.' >&2
        exit 1
    fi
    unzip -q "${archives[0]}" -d tools
fi

# The supplied C code predates the modern GCC default language dialect.
# ORACLE chooses an existing QGEN dialect; DBGEN still produces flat files.
make -C "$tool_dir" -f makefile.suite \
    CC='gcc -std=gnu89' DATABASE=ORACLE MACHINE=LINUX WORKLOAD=TPCH \
    2>&1 | tee -a logs/tpch-build.log

shopt -s nullglob
raw_files=(data/tpch-sf1/raw/*.tbl)
if [[ ${#raw_files[@]} -eq 0 ]]; then
    env DSS_PATH="$project_root/data/tpch-sf1/raw" DSS_CONFIG="$tool_dir" \
        "$tool_dir/dbgen" -s 1 > logs/tpch-generate-sf1.log 2>&1
else
    printf '%s\n' 'Reusing existing .tbl files.'
fi

# Preserve the official QGEN output separately from its SQLite adaptation.
env DSS_CONFIG="$tool_dir" DSS_QUERY="$tool_dir/queries" \
    "$tool_dir/qgen" -d 8 > logs/tpch-q8-official.sql

if [[ -f data/tpch-sf1/tpch.db ]]; then
    printf '%s\n' 'Database already exists: data/tpch-sf1/tpch.db'
else
    python3 -u scripts/load_tpch.py 2>&1 | tee logs/tpch-load-sf1.log
fi

printf '%s\n' 'Run Q8 from the project root:'
printf '%s\n' '  ./build/sqlite-debug/sqlite3d -header -column data/tpch-sf1/tpch.db ".read sql/tpch/q8.sql"'

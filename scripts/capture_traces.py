#!/usr/bin/env python3
"""Capture reproducible, read-only planner evidence and build the offline viewer."""

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from planner_trace import SQLITE_VERSION, TRACE_MASK, TraceError, parse_trace, path_labels

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(2 ** 20), b""):
            h.update(chunk)
    return h.hexdigest()


def query_definitions():
    nodes = [{"id": "r", "table": "region", "filter": "r_name = AMERICA"},
             {"id": "n", "table": "nation"}, {"id": "c", "table": "customer"},
             {"id": "o", "table": "orders"}]
    edges = [{"from": "r", "to": "n", "predicate": "r_regionkey = n_regionkey"},
             {"from": "n", "to": "c", "predicate": "n_nationkey = c_nationkey"},
             {"from": "c", "to": "o", "predicate": "c_custkey = o_custkey"}]
    definitions = []
    for k, filename in [(2, "02_region_nation.sql"), (3, "03_region_nation_customer.sql"),
                        (4, "04_region_nation_customer_orders.sql")]:
        definitions.append({"id": f"join{k}", "title": f"{k} tables · region chain",
                            "sql_file": f"sql/learning/{filename}", "setting": "default",
                            "graph": {"nodes": nodes[:k], "edges": edges[:k-1]}})
    q8_nodes = [{"id": alias, "table": table, "filter": filter_text}
                for alias, table, filter_text in [
                    ("part", "part", "p_type = ECONOMY ANODIZED STEEL"),
                    ("lineitem", "lineitem", ""), ("orders", "orders", "1995–1996"),
                    ("customer", "customer", ""), ("n1", "nation", ""),
                    ("region", "region", "r_name = AMERICA"),
                    ("supplier", "supplier", ""), ("n2", "nation", "")]]
    for node in q8_nodes:
        if node["id"] in ("n1", "n2"):
            node["role"] = "customer nation" if node["id"] == "n1" else "supplier nation"
    q8_edges = [{"from": a, "to": b, "predicate": pred} for a, b, pred in [
        ("part", "lineitem", "p_partkey = l_partkey"),
        ("lineitem", "supplier", "l_suppkey = s_suppkey"),
        ("lineitem", "orders", "l_orderkey = o_orderkey"),
        ("orders", "customer", "o_custkey = c_custkey"),
        ("customer", "n1", "c_nationkey = n_nationkey"),
        ("n1", "region", "n_regionkey = r_regionkey"),
        ("supplier", "n2", "s_nationkey = n_nationkey")]]
    for setting in ("default", "starquery_disabled"):
        definitions.append({"id": f"q8_{setting}",
                            "title": "TPC-H Q8 · " + ("default" if setting == "default" else "star heuristic off"),
                            "sql_file": "sql/tpch/q8.sql", "setting": setting,
                            "graph": {"nodes": q8_nodes, "edges": q8_edges}})
    return definitions


def capture(cli, db, definition, timeout):
    sql = (ROOT / definition["sql_file"]).read_text()
    # Initialize schema/statistics before enabling tracing to exclude internal SQL.
    setting = ".testctrl opt -starquery\n" if definition["setting"] == "starquery_disabled" else ""
    commands = (".bail on\nSELECT 1 FROM sqlite_stat1 LIMIT 1;\n" + setting +
                f".wheretrace {TRACE_MASK}\n.print ===PROJECT_TRACE_BEGIN===\n" +
                "EXPLAIN QUERY PLAN\n" + sql + "\n.wheretrace 0\n")
    proc = subprocess.run([str(cli), "-readonly", str(db)], input=commands,
                          text=True, capture_output=True, timeout=timeout, cwd=ROOT)
    if proc.returncode or proc.stderr.strip():
        raise TraceError(f"SQLite capture failed for {definition['id']}: {proc.stderr.strip()}")
    marker = "===PROJECT_TRACE_BEGIN===\n"
    if marker not in proc.stdout:
        raise TraceError("Missing trace marker")
    raw = proc.stdout.split(marker, 1)[1]
    trace = parse_trace(raw)
    if len(trace["blocks"]) != 1:
        raise TraceError("Expected one warmed user-query optimizer invocation")
    if {x["alias"] for x in trace["blocks"][0]["loops"].values()} != {
            n["id"] for n in definition["graph"]["nodes"]}:
        raise TraceError("Trace table references disagree with declared join graph")
    return {**definition, "sql": sql, "trace": trace}, raw, commands


def build_viewer(bundle, output):
    template = (ROOT / "viewer/template.html").read_text()
    expansion_script = (ROOT / "viewer/expansion.js").read_text()
    # Keep arbitrary SQL/raw text from terminating the inert JSON script element.
    embedded = json.dumps(bundle, ensure_ascii=True).replace("<", "\\u003c").replace("&", "\\u0026")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("/*__EXPANSION_SCRIPT__*/", expansion_script)
                      .replace("__PROJECT_DATA__", embedded))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=ROOT / "build/sqlite-debug/sqlite3d")
    parser.add_argument("--database", type=Path, default=ROOT / "data/tpch-sf1/tpch.db")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence")
    parser.add_argument("--viewer", type=Path, default=ROOT / "viewer/index.html")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    cli, db, output = args.sqlite.resolve(), args.database.resolve(), args.output.resolve()
    if not cli.is_file() or not db.is_file():
        parser.error("Build SQLite and load TPC-H first; see README.md")
    before = {"bytes": db.stat().st_size, "sha256": digest(db)}
    meta_query = "SELECT sqlite_version(),sqlite_source_id(); PRAGMA compile_options;"
    meta = subprocess.check_output([str(cli), "-readonly", str(db), meta_query], text=True).splitlines()
    version, source_id = meta[0].split("|", 1)
    if version != SQLITE_VERSION:
        parser.error(f"Unsupported SQLite {version}; expected {SQLITE_VERSION}")
    source_dir = ROOT / "src/sqlite-src-3540100"
    metadata = {"captured_utc": datetime.now(timezone.utc).isoformat(), "sqlite_version": version,
                "sqlite_source_id": source_id, "sqlite_binary_sha256": digest(cli),
                "planner_source_sha256": digest(source_dir / "src/where.c"),
                "compile_options": meta[1:], "platform": platform.platform(),
                "database": before, "trace_mask": TRACE_MASK,
                "capture_mode": "read-only EXPLAIN QUERY PLAN; no query execution timings",
                "cost_encoding": "SQLite LogEst, approximately 10 * log2(value); not milliseconds",
                "path_limit_basis": "Pinned SQLite 3.54.1 source; independently inspect mxChoice in GDB",
                "dataset_summary": json.loads((ROOT / "data/tpch-sf1/tpch.summary.json").read_text()),
                "provenance": json.loads((ROOT / "logs/tpch-provenance.json").read_text()),
                "index_sql": (ROOT / "sql/tpch/indexes.sql").read_text()}
    bundle = {"schema_version": 1, "metadata": metadata, "runs": []}
    output.mkdir(parents=True, exist_ok=True)
    for definition in query_definitions():
        run, raw, commands = capture(cli, db, definition, args.timeout)
        bundle["runs"].append(run)
        (output / f"{run['id']}.trace.txt").write_text(raw)
        (output / f"{run['id']}.commands.txt").write_text(commands)
        (output / f"{run['id']}.json").write_text(json.dumps(run, indent=2) + "\n")
        block = run["trace"]["blocks"][0]
        print(run["id"], "limit", block["path_limit"], "events", block["event_counts"],
              "order", " -> ".join(path_labels(block, block["solution"]["path"])))
    after = {"bytes": db.stat().st_size, "sha256": digest(db)}
    if before != after:
        raise TraceError("Baseline database changed during capture")
    metadata["database_unchanged"] = True
    (output / "project.json").write_text(json.dumps(bundle, indent=2) + "\n")
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    build_viewer(bundle, args.viewer)
    print("Validated database hash unchanged; wrote", args.viewer)


if __name__ == "__main__":
    try:
        main()
    except (TraceError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Capture error: {exc}") from exc

#!/usr/bin/env python3
"""Capture real GDB evidence without changing SQLite or the database.

Requires local ptrace permission. The generated command files can also be
opened interactively with GDB from the repository root.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

from capture_traces import ROOT


def source_line(fragment):
    lines = (ROOT / "src/sqlite-src-3540100/src/where.c").read_text().splitlines()
    return next(i for i, line in enumerate(lines, 1) if fragment in line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/debugger")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle = json.loads((ROOT / "evidence/project.json").read_text())
    allocation = source_line("nSpace = (sizeof(WherePath)")
    accept = source_line("/* pWLoop is a winner.  Add it to the set of best so far */") + 1
    observations = []
    for run in bundle["runs"]:
        if run["id"] not in ("join3", "q8_default", "q8_starquery_disabled"):
            continue
        command_file = output / f"{run['id']}.gdb"
        # Break after mxChoice is initialized; function entry locals are uninitialized.
        script = f"""set pagination off
set confirm off
set debuginfod enabled off
set startup-with-shell off
break where.c:{allocation} if pWInfo->nLevel > 1
commands
silent
printf "PROJECT_SOLVER nLoop=%d mxChoice=%d nRowEst=%d nOrderBy=%d star=%d\\n", nLoop, mxChoice, nRowEst, nOrderBy, pWInfo->bStarUsed
bt 5
print pWInfo->pLoops->maskSelf
print pWInfo->pLoops->prereq
print pWInfo->pLoops->rSetup
print pWInfo->pLoops->rRun
print pWInfo->pLoops->nOut
continue
end
"""
        if run["id"] == "join3":
            script += f"""break where.c:{accept} if pWInfo->nLevel == 3 && iLoop == 1 && pWLoop->cId == '4'
commands
silent
printf "PROJECT_REPLACEMENT depth=%d candidate=%c%c old=%c%c newCost=%d oldCost=%d\\n", iLoop+1, pFrom->aLoop[0]->cId, pWLoop->cId, pTo->aLoop[0]->cId, pTo->aLoop[1]->cId, rCost, pTo->rCost
print pFrom->maskLoop
print pWLoop->prereq
print pWLoop->rRun
print pFrom->nRow
continue
end
"""
        script += "run\n"
        command_file.write_text(script)
        setting = ["-cmd", ".testctrl opt -starquery"] if run["setting"] == "starquery_disabled" else []
        cmd = ["gdb", "-nx", "--batch", "--return-child-result", "-x", str(command_file),
               "--args", str(ROOT / "build/sqlite-debug/sqlite3d"), "-readonly",
               str(ROOT / "data/tpch-sf1/tpch.db"),
               "-cmd", "SELECT 1 FROM sqlite_stat1 LIMIT 1;",
               *setting, "-cmd", ".wheretrace 0x100000",
               "EXPLAIN QUERY PLAN\n" + run["sql"]]
        proc = subprocess.run(cmd, text=True, capture_output=True, cwd=ROOT, timeout=45)
        log = proc.stdout + ("\nSTDERR\n" + proc.stderr if proc.stderr else "")
        (output / f"{run['id']}.txt").write_text(log)
        records = [dict(zip(("nLoop", "mxChoice", "nRowEst", "nOrderBy", "star"), map(int, match)))
                   for match in re.findall(r"PROJECT_SOLVER nLoop=(\d+) mxChoice=(\d+) nRowEst=(-?\d+) nOrderBy=(\d+) star=(\d+)", log)]
        if proc.returncode or not records:
            raise SystemExit(f"GDB capture failed for {run['id']}. Inspect {output / (run['id'] + '.txt')}; local ptrace permission may be required.")
        expected = run["trace"]["blocks"][0]["path_limit"]
        if any(r["mxChoice"] != expected for r in records):
            raise SystemExit("GDB mxChoice disagrees with source-derived trace metadata")
        observations.append({"run": run["id"], "solver_stops": records,
                             "replacement": re.findall(r"PROJECT_REPLACEMENT .*", log),
                             "log_file": f"evidence/debugger/{run['id']}.txt"})
        print(run["id"], records)
    (output / "observations.json").write_text(json.dumps(observations, indent=2) + "\n")


if __name__ == "__main__":
    main()

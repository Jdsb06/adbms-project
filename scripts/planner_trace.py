#!/usr/bin/env python3
"""Strict reader for this project's SQLite 3.54.1 WHERETRACE dialect.

The trace is a diagnostic interface, not a stable SQLite API. Round snapshots
are authoritative. New/Update/Skip records describe consideration events;
they do not provide a complete eviction history or every rejected extension.
"""

import copy
import re
from collections import Counter


FORMAT_VERSION = 1
SQLITE_VERSION = "3.54.1"
TRACE_MASK = "0x001c008e"


class TraceError(ValueError):
    """The input cannot be represented faithfully by this parser."""


LOOP = re.compile(
    r"^(?P<id>[0-9a-zA-Z])\s+(?P<table_position>\d+)\."
    r"(?P<self_mask>[0-9a-f]+)\.(?P<prerequisite_mask>[0-9a-f]+)\s+"
    r"(?P<access>\S+)(?:\s+(?P<equalities>\d+))?\s+"
    r"f (?P<flags>[0-9a-f]+) N (?P<terms>\d+) cost\s+"
    r"(?P<setup>-?\d+),\s*(?P<run>-?\d+),\s*(?P<rows>-?\d+)"
    r"(?: delta=(?P<star_delta>-?\d+))?$"
)
EVENT = re.compile(
    r"^(New|Update|Skip)\s+([0-9a-zA-Z]+) cost=\s*(-?\d+)\s*,"
    r"\s*(-?\d+)\s*,\s*(-?\d+)\s+order=(\S+)"
    r"(?:\s+(vs|was) ([0-9a-zA-Z]+) cost=\s*(-?\d+)\s*,"
    r"\s*(-?\d+)\s*,\s*(-?\d+)\s+order=(\S+))?$"
)
SNAPSHOT = re.compile(
    r"^ ([0-9a-zA-Z]+) cost=\s*(-?\d+)\s+nrow=\s*(-?\d+)"
    r"\s+order=(\S+?)(?: rev=0x([0-9a-f]+))?$"
)
SOLVER = re.compile(r"^---- begin solver\.  \(nRowEst=(-?\d+), nQueryLoop=(-?\d+)\)$")
ROUND = re.compile(r"^---- after round (\d+) ----$")
SOLUTION = re.compile(r"^---- Solution cost=(-?\d+), nRow=(-?\d+)(?: ORDERBY=.*)?$")


def parse_loop(match, line_number):
    fields = match.groupdict()
    result = {k: int(fields[k]) for k in
              ("table_position", "terms", "setup", "run", "rows")}
    result.update({k: int(fields[k], 16) for k in
                   ("self_mask", "prerequisite_mask", "flags")})
    result.update(id=fields["id"], access=fields["access"],
                  alias=fields["access"].split(".", 1)[0],
                  equalities=int(fields["equalities"]) if fields["equalities"] else None,
                  star_delta=int(fields["star_delta"]) if fields["star_delta"] else 0,
                  disabled_by_interstage=False,
                  source_line=line_number)
    return result


def parse_trace(raw, sqlite_version=SQLITE_VERSION):
    """Parse all optimizer blocks; loop labels are scoped to their own block."""
    if sqlite_version != SQLITE_VERSION:
        raise TraceError(f"Unsupported SQLite version {sqlite_version}; expected {SQLITE_VERSION}")
    blocks = []
    block = solver = current_round = None
    pending_events = []
    snapshots_open = False
    loop_context = "catalog"
    eqp = []
    in_eqp = False

    for line_number, line in enumerate(raw.splitlines(), 1):
        if line.startswith("*** Optimizer Start ***"):
            if block is not None:
                raise TraceError(f"Nested optimizer invocation at line {line_number} is unsupported")
            block = {"id": len(blocks), "start_line": line_number, "loops": {},
                     "passes": [], "access_events": [], "annotations": [],
                     "star_applied": False, "solution": None, "solution_loops": []}
            blocks.append(block)
            solver = current_round = None
            pending_events = []
            snapshots_open = False
            loop_context = "catalog"
            in_eqp = False
            continue
        if line.startswith("*** Optimizer Finished ***"):
            if block is None:
                raise TraceError(f"Unmatched optimizer end at line {line_number}")
            block["end_line"] = line_number
            if pending_events:
                raise TraceError("Events without a closing round snapshot")
            block = solver = current_round = None
            continue
        if line == "QUERY PLAN":
            in_eqp = True
            continue
        if in_eqp:
            if line.strip():
                eqp.append(line)
            continue
        if block is None:
            if line.startswith(("New ", "Skip ", "Update ", "---- begin solver")):
                raise TraceError(f"Planner record outside optimizer block at line {line_number}")
            continue

        match = SOLVER.fullmatch(line)
        if match:
            if pending_events:
                raise TraceError("Solver pass ended with unassigned events")
            solver = {"id": len(block["passes"]), "source_line": line_number,
                      "row_estimate": int(match[1]), "query_loop": int(match[2]),
                      "loops": copy.deepcopy(block["loops"]), "rounds": []}
            block["passes"].append(solver)
            loop_context = "catalog"
            current_round = None
            snapshots_open = False
            continue

        match = ROUND.fullmatch(line)
        if match:
            if solver is None:
                raise TraceError("Round without solver pass")
            depth = int(match[1]) + 1
            if depth != len(solver["rounds"]) + 1:
                raise TraceError(f"Missing or repeated round at line {line_number}")
            current_round = {"depth": depth, "source_line": line_number,
                             "events": pending_events, "retained": []}
            solver["rounds"].append(current_round)
            pending_events = []
            snapshots_open = True
            continue

        match = EVENT.fullmatch(line)
        if match:
            if solver is None:
                raise TraceError("Path event without solver pass")
            snapshots_open = False
            event = {"kind": match[1], "path": match[2], "cost": int(match[3]),
                     "rows": int(match[4]), "unsorted_cost": int(match[5]),
                     "order": match[6], "source_line": line_number}
            if match[7]:
                event["comparison"] = {"relation": match[7], "path": match[8],
                                       "cost": int(match[9]), "rows": int(match[10]),
                                       "unsorted_cost": int(match[11]), "order": match[12]}
                event["reason"] = "competing path for same subset and compatible ordering"
            elif match[1] == "Skip":
                event["reason"] = "not competitive with full retained-path buffer"
            elif match[1] == "New":
                event["reason"] = "entered buffer; may displace an unnamed worst path"
            else:
                raise TraceError("Update without an identified previous path")
            pending_events.append(event)
            continue

        match = SNAPSHOT.fullmatch(line)
        if match:
            if current_round is None or not snapshots_open:
                raise TraceError(f"Unexpected snapshot at line {line_number}")
            current_round["retained"].append(
                {"path": match[1], "cost": int(match[2]), "rows": int(match[3]),
                 "order": match[4], "source_line": line_number})
            continue

        match = SOLUTION.fullmatch(line)
        if match:
            if solver is None or not solver["rounds"]:
                raise TraceError("Solution without completed search")
            block["solution"] = {"cost": int(match[1]), "rows": int(match[2]),
                                 "source_line": line_number,
                                 "path": solver["rounds"][-1]["retained"][0]["path"]}
            snapshots_open = False
            continue

        match = LOOP.fullmatch(line)
        if match:
            loop = parse_loop(match, line_number)
            # whereInterstageHeuristic prints a loop BEFORE setting its
            # prereq to ALLBITS. Preserve the printed mask and record the
            # effective disabling explicitly from this named message group.
            if loop_context == "interstage":
                loop["disabled_by_interstage"] = True
            block["loops"][loop["id"]] = loop
            if solver is not None and not solver["rounds"]:
                solver["loops"][loop["id"]] = copy.deepcopy(loop)
            if block["solution"] is not None:
                block["solution_loops"].append(loop)
            continue

        if re.match(r"^\s*(?:add:|replace:|with:|skip:|delete:)", line):
            block["access_events"].append({"source_line": line_number, "raw": line})
        elif line.strip():
            block["annotations"].append({"source_line": line_number, "raw": line})
            if "WhereLoops changed by star-query heuristic" in line:
                block["star_applied"] = True
            if line == "Loops disabled by interstage heuristic:":
                loop_context = "interstage"
        # Fail loudly for dialect changes in structural records.
        if line.startswith(("New ", "Update ", "Skip ", "---- after round", "---- begin solver", "---- Solution")):
            raise TraceError(f"Unsupported trace record at line {line_number}: {line}")

    if block is not None:
        raise TraceError("Truncated optimizer block")
    if not blocks or not eqp:
        raise TraceError("Expected optimizer trace and EXPLAIN QUERY PLAN output")
    for b in blocks:
        if not b["passes"] or b["solution"] is None:
            raise TraceError(f"Optimizer block {b['id']} lacks complete search evidence")
        table_count = len({x["table_position"] for x in b["loops"].values()})
        b["table_count"] = table_count
        b["path_limit"] = 1 if table_count == 1 else 5 if table_count == 2 else 18 if b["star_applied"] else 12
        b["path_limit_basis"] = "Pinned wherePathSolver/computeMxChoice source and observed heuristic flag"
        for p in b["passes"]:
            # Star costs may be printed immediately after begin solver.
            p["path_limit"] = b["path_limit"]
        b["event_counts"] = dict(Counter(e["kind"] for p in b["passes"]
                                         for r in p["rounds"] for e in r["events"]))
    result = {"schema_version": FORMAT_VERSION, "blocks": blocks, "eqp": eqp,
              "raw_lines": raw.splitlines()}
    validate_trace(result)
    return result


def validate_trace(trace):
    """Check graph legality, provenance and authoritative round continuity."""
    raw = trace["raw_lines"]
    for block in trace["blocks"]:
        for solver in block["passes"]:
            loops = solver["loops"]
            previous = {""}
            for round_data in solver["rounds"]:
                depth = round_data["depth"]
                retained = round_data["retained"]
                if not retained or len(retained) > solver["path_limit"]:
                    raise TraceError("Empty or over-capacity round snapshot")
                emitted = {e["path"] for e in round_data["events"] if e["kind"] != "Skip"}
                if not {x["path"] for x in retained} <= emitted:
                    raise TraceError("Snapshot contains path with no acceptance event")
                for item in [*retained, *round_data["events"],
                             *(e["comparison"] for e in round_data["events"] if "comparison" in e)]:
                    path = item["path"]
                    if len(path) != depth or path[:-1] not in previous:
                        raise TraceError(f"Path {path} has invalid depth or unretained parent")
                    visited = 0
                    for loop_id in path:
                        if loop_id not in loops:
                            raise TraceError(f"Unknown access-method ID {loop_id}")
                        loop = loops[loop_id]
                        if loop.get("disabled_by_interstage"):
                            raise TraceError(f"Interstage-disabled access method in path {path}")
                        if visited & loop["self_mask"]:
                            raise TraceError(f"Repeated table reference in path {path}")
                        if loop["prerequisite_mask"] & ~visited:
                            raise TraceError(f"Unmet dependency in path {path}")
                        visited |= loop["self_mask"]
                for item in [*retained, *round_data["events"]]:
                    if item["path"] not in raw[item["source_line"] - 1]:
                        raise TraceError("Invalid raw line provenance")
                previous = {x["path"] for x in retained}
            if len(solver["rounds"]) != block["table_count"]:
                raise TraceError("Search does not cover every table reference")
        final = block["passes"][-1]["rounds"][-1]["retained"]
        if len(final) != 1 or final[0]["path"] != block["solution"]["path"]:
            raise TraceError("Final plan disagrees with final retained snapshot")
        aliases = [block["loops"][x]["alias"] for x in block["solution"]["path"]]
        eqp_aliases = [m[1] for line in trace["eqp"]
                       if (m := re.search(r"(?:SCAN|SEARCH) (\S+)", line))]
        if len(trace["blocks"]) == 1 and aliases != eqp_aliases:
            raise TraceError(f"Final path {aliases} disagrees with EQP {eqp_aliases}")


def path_labels(block, path):
    return [block["loops"][loop_id]["alias"] for loop_id in path]

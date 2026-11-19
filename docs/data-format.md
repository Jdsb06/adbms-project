# Evidence format version 1

`evidence/project.json` is the complete bundle embedded into `viewer/index.html`.
The browser can also import it through **Open evidence JSON**. It is a project
interface, not a SQLite API. Capture requires the trace dialect in SQLite 3.54.1.

## Bundle

`schema_version` is 1. `metadata` records the SQLite source ID, binary/source
hashes, compilation options, timestamp, database SHA-256 and size, trace mask,
existing data validation summary and index definitions. `database_unchanged`
is true only after a matching before/after hash. Each item in `runs` has a
stable ID, SQL, connection setting, SQL filename, declared join graph, and
`trace`. The declared graph is curated for these five inputs; no arbitrary-SQL
parser is claimed.

## Trace and loop scope

`trace.blocks` contains optimizer invocations. Labels such as `0`, `4`, `b`,
and `o` identify access methods only within one invocation. The capture script
requires one warmed user-query block per run, while the parser can preserve
multiple sequential invocations. Nested optimizer invocations are rejected.

Each block has `loops`, `passes`, `access_events`, `annotations`, `solution`,
`table_count`, `star_applied`, `path_limit`, `path_limit_basis`, and event totals.
A loop records alias, access name, table position, self/dependency masks,
flags, equality/term counts, setup/run/output estimates and raw source line.
The displayed alias is not a unique access-method identifier.

## Solver state and provenance

Each solver pass freezes its own loop dictionary, preserving star cost changes
and interstage disabling between passes. A loop printed under the explicit
interstage-disabling header receives `disabled_by_interstage: true`: the
source prints that loop immediately before changing its prerequisite mask
to ALLBITS. The original printed mask is retained, and validation rejects
use of a disabled loop in the later pass. A pass has a row-estimate argument,
query-loop estimate and ordered `rounds`. A round has depth, decision events,
and authoritative `retained` snapshots. An event contains kind, path, estimated
cost, output estimate, unsorted cost, order marker, optional competitor, and
one-based raw source line. Snapshots contain the values actually printed by
SQLite. `raw_lines` preserves the complete capture and `eqp` the final plan.

The path limit is derived from the pinned source's table-count and observed
star flag. Independent GDB confirmations live in
`evidence/debugger/observations.json`; deriving N from the largest observed
snapshot would be wrong when the buffer never fills.

## Meaning and limits

- `New` accepts a candidate, possibly evicting an unnamed worst path.
- `Update … was …` replaces the named subset/ordering competitor.
- `Skip … vs …` loses against that competitor; a `Skip` without `vs` loses
  against the full best-path buffer.
- Lowercase access-generation `add/replace/skip` messages are separate records.
- `order` is preserved as the trace's marker. The viewer does not reinterpret
  every ordering state or expose a general ordering-analysis API.
- A solution's access order is checked against SCAN/SEARCH entries only.
  Bloom filters and temporary sorting B-trees remain EQP annotations.
- All cost and row integers remain LogEst. Approximate row conversion is
  rounded display information; estimates below one are valid.

The parser rejects unsupported versions, malformed recognized records,
incomplete blocks/rounds, unknown IDs, illegal dependencies, repeated table
references, unretained parents, and final-order disagreement. It does not
recompute SQLite's entire cost model or reconstruct unlogged paths. The
browser validates this project's small (at most eight-reference) bundles;
its JavaScript mask checks are not a general 64-table SQLite bitmask engine.

## Round expansion

The viewer derives a branch from each prior round's retained path and each
access method in the selected pass. Depth 1 starts with the solver's empty
path. A table order groups access variants that add the same reference to the
same start. The round summary counts unique alias sequences even when more
than one access path has the same sequence.

New, Update and Skip come from the raw events. The retained snapshot
determines survival. Replaced paths name their successor only when an Update
identifies it. Where an extension has no event, the viewer checks the pinned
source's early screens for disabled loops, missing prerequisites, repeated
references and automatic-index setup. It labels matches **Ineligible · inferred**
and shows the input trace records. An unexplained absence stays **Unlogged**.
The inference uses the existing evidence schema and works with saved captures.

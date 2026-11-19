# SQLite join optimization investigation

Jashandeep Singh Bedi · Advanced Database Management Systems · November 2026

This project follows SQLite 3.54.1's N3 join-order search from C structures and
GDB stops to captured decisions and an offline visualization. It reuses TPC-H
SF1 and never changes the baseline database during evidence capture.

## Start here

1. Open **[viewer/index.html](viewer/index.html)** directly in a browser. No
   server, installation, network, or database connection is needed for replay.
2. Open **3 tables · region chain** at **2 / 3 tables** in **Expand this round**.
   Follow each surviving starting path to its two next-table orders. Select
   `02`, `04` and `03` under `r → n` to compare a replacement, a retained
   index search and a lookup that needs customer first. Read the **Access code legend**
   for the meaning of each digit.
   **Start walkthrough** guides you across the three rounds. **Replay decisions**
   plays or steps through the logged candidates for the selected starting paths
   in trace order.
3. Follow **[docs/study_guide.md](docs/study_guide.md)**, then run the debugger
   walkthrough yourself. Saved machine captures establish facts; they do not
   establish your personal understanding.
4. Read the editable report and PDF under **[output/report](output/report)**.
   The content source is [docs/report.md](docs/report.md).

## What was observed

The three-table query chooses `r → n → c`. The update from `02` to `04`
changes the nation access method, while preserving the same table order.
The trace estimates change from cost 67 to 56 and output 49 to 26, all in
SQLite's LogEst representation.

| Q8 setting | GDB mxChoice | New | Update | Skip |
| --- | ---: | ---: | ---: | ---: |
| Default | 18 | 199 | 154 | 470 |
| Star heuristic disabled | 12 | 161 | 96 | 333 |

Both choose `part → lineitem → orders → customer → n1 → region → supplier → n2`.
Counts cover logged path decisions across both user-query solver passes.
They are not every possible plan, timings, or unique-plan counts. The switch
changes both costs and search breadth, so it does not isolate the effect of N.

## Reproduce the evidence

Run commands from this directory. Python 3.10 or later is sufficient for the
capture and parser; they use only the standard library.

```bash
python3 scripts/capture_traces.py
python3 -m unittest discover -s tests -v
python3 scripts/capture_debugger.py
```

The first command captures five independent read-only runs, checks the
database's SHA-256 before and after, validates paths and EQP order, and rebuilds
`viewer/index.html`. It prepares schema/statistics before enabling tracing,
avoiding initialization-query noise. The second command includes fresh
captures and rejection tests for corrupt evidence. GDB needs local permission
to trace a child process; a restricted agent sandbox may block `ptrace`.
Do not change system-wide ptrace settings for this project.

Inputs are the existing `build/sqlite-debug/sqlite3d`,
`data/tpch-sf1/tpch.db`, dataset summary, and TPC-H provenance log.
The default trace dialect is explicitly pinned to **SQLite 3.54.1**.

To inspect an existing capture without opening the viewer:

```bash
python3 -m json.tool evidence/debugger/observations.json
./build/sqlite-debug/sqlite3d -readonly data/tpch-sf1/tpch.db \
  '.read evidence/join3.commands.txt'
```

`--output /tmp/sqlite-evidence --viewer /tmp/sqlite-viewer.html` can be passed
to the capture script to regenerate a separate evidence copy. `--sqlite`,
`--database`, and `--timeout` are also available. The declared schemas and graph
are specific to this project's TPC-H inputs, rather than arbitrary SQL.

## Build and data setup

The original SQLite source, compiled debug build and downloads are already in
this repository. For a new debug build, from a fresh build directory:

```bash
../../src/sqlite-src-3540100/configure --debug --disable-amalgamation 'CFLAGS=-O0 -g3'
make sqlite3d
```

Run `./sqlite3d --version` and check the build enables `SQLITE_DEBUG`,
`SQLITE_ENABLE_WHERETRACE`, and `SQLITE_ENABLE_SELECTTRACE`.
The existing `scripts/prepare_tpch.sh` is for initial TPC-H preparation and
loading, not routine tracing. Keep the current database for the demo.
See `evidence/manifest.json` for exact binary/source hashes, version, index
definitions, compilation options, data provenance, and the existing validation
qualification. No TPC-H performance/compliance claim is made.

## Report and browser verification

Core capture and replay need no third-party Python or JavaScript packages.
Report generation additionally uses `python-docx` and Pillow:

```bash
python3 scripts/build_report.py
```

This writes the populated Markdown and editable Word report. PDF production
and page images were produced with the Codex Documents skill's bundled
`render_docx.py --emit_pdf`, using its bundled LibreOffice and Poppler.
Outside Codex, export the DOCX to PDF from Word or LibreOffice and review it.
To regenerate the figure taken from the UI, use the optional Playwright test
first; its `playwright` package and local Chrome are development tools only.

```bash
node tests/viewer_smoke.cjs
```

Set `CHROME_PATH` when Chrome is elsewhere, and make Playwright available to
Node through your development environment. The browser check exercises all
runs, solver passes and rounds, evidence selection, import errors, a mobile
viewport, and zero HTTP requests. It saves report figures under `output/figures`.

## Deliverables and evidence

- `viewer/`: HTML template, round expansion code, and generated offline viewer.
- `evidence/`: raw logs, replayable shell commands, parsed JSON, provenance,
  and actual GDB captures. Include this directory in version control; the
  older `logs/` is ignored.
- `docs/`: report source, learning exercises, data contract, and demo script.
- `sql/learning/`: two-, three-, and four-table examples.
- `output/report/`: Word/PDF report and populated Markdown.
- `tests/`: parser, fresh-capture, and optional browser checks.

SQLite source and public APIs are unchanged. The original source tree's
`AGENTS.md` applies if future work modifies that tree. Existing tracked build
artifacts and downloads have not been removed as part of this investigation.

## Research references

- [SQLite NGQP](https://sqlite.org/queryplanner-ng.html)
- [SQLite EXPLAIN QUERY PLAN](https://sqlite.org/eqp.html)
- [SQLite optimizer overview](https://sqlite.org/optoverview.html)
- Selinger et al., [Access Path Selection in a Relational Database Management System](https://web.eecs.umich.edu/~michjc/eecs584/Papers/selinger_1979.pdf), 1979.
- Graefe, [The Cascades Framework for Query Optimization](https://15799.courses.cs.cmu.edu/spring2025/papers/05-cascades/graefe-ieee1995.pdf), 1995.

The original assignment and supplied progress notes informed scope. The
implementation, explanations and report were prepared with AI assistance;
personal study and live rehearsal remain the student's responsibility.

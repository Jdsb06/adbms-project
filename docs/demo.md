# Eight to ten minute demonstration

## Preparation

Open the offline viewer and source before presenting. Keep
`evidence/join3.trace.txt`, `evidence/debugger/join3.txt`, and
`evidence/debugger/observations.json` accessible. Check the live GDB command
works on the presentation machine. Use the saved logs if local ptrace policy
prevents it; describe them honestly as recorded captures.

## Minute zero to one

State the research question: how does SQLite turn candidate access methods
into a bounded search over partial join plans, and what evidence shows its
pruning decisions? Show the pinned version and TPC-H provenance. Explain
that this demonstration studies planning, not query throughput.

## Minute one to three

Show the three-table SQL and logical graph. Predict region first because of
its filter and the available connecting indexes. Open the second search round.
Select Update `04`, read raw line 30, and explain its replacement of `02`.
The table order is unchanged; the nation access method improves. Explain
estimated cost 67 → 56 and estimated rows 49 → 26 as LogEst quantities.

## Minute three to five

Show `WhereLoop` and `WherePath`, then a live or recorded GDB stop in
`wherePathSolver`. Show `nLoop=3`, `mxChoice=12`, and the dependency mask.
Explain the two legality checks: prerequisites must already be visited, and
the table reference must not have been visited. Show the real replacement
stop with `newCost=56 oldCost=67`.

## Minute five to seven

Switch to Q8. Identify `n1` and `n2`. Show two solver passes and one generation
with 18 retained paths. Show final order beside EQP. Identify the Bloom-filter
and sorting annotations without counting them as table references. Explain
the interstage heuristic and sort-aware second pass.

## Minute seven to nine

Compare default Q8 and the disabled-star run. Show GDB N=18 versus N=12 and
the different New/Update/Skip counts. State the unchanged final order.
Explain that the switch affects costs and breadth together, and no runtime
improvement or global optimality has been established.

## Final minute

Connect SQLite's retained frontier to System-R subset optimization and
Volcano/Cascades memo/rule search. State what the observed trace omits.
Conclude with the contribution: a reproducible link from source decisions
to inspectable search evidence. Acknowledge AI assistance and describe which
parts you personally studied and reproduced.

## Backup and rehearsal

Screenshots live under `output/figures`; the HTML embeds all replay data.
The DOCX and PDF include the small trace, debugger evidence and experimental
results. Practice answering the questions in `docs/study_guide.md` without
switching to an AI chat. The presence of these artifacts is not a claim that
the student's rehearsal or independent study has already occurred.

// WhereLoop flags from the pinned SQLite 3.54.1 whereInt.h.
const loopFlags = {
  constraint: 0x000f,
  covering: 0x0040,
  rowid: 0x0100,
  indexed: 0x0200,
  automatic: 0x4000,
};

function aliasName(run, alias) {
  const table = run.graph.nodes.find(node => node.id === alias)?.table || alias;
  return table === alias ? table : `${table} (${alias})`;
}

function accessDescription(run, loop, short = false) {
  const table = short ? loop.alias : aliasName(run, loop.alias);
  const constrained = loop.flags & loopFlags.constraint;
  if (loop.flags & loopFlags.automatic) return `Automatic index on ${table}`;
  if (loop.flags & loopFlags.indexed) {
    const name = loop.access.slice(loop.alias.length + 1);
    if (short) return `${constrained ? "Index search" : "Index scan"} · ${name}`;
    const index = loop.flags & loopFlags.covering ? "covering index" : "index";
    const action = constrained ? "Search" : "Scan";
    return `${action} ${table} using ${index} ${name}`;
  }
  if ((loop.flags & loopFlags.rowid) && constrained) {
    return short ? "Primary-key lookup" : `Search ${table} by integer primary key`;
  }
  return `Scan ${table}`;
}

function aliasesInMask(pass, mask) {
  return [...new Set(Object.values(pass.loops)
    .filter(loop => loop.self_mask & mask)
    .map(loop => loop.alias))];
}

// Match the early continue checks in wherePathSolver. These decisions are
// inferred from the trace's loop flags, dependencies and parent snapshot.
function screenExtension(pass, prefix, loop, visited) {
  if (loop.disabled_by_interstage) return "SQLite disabled this access method between solver passes.";
  const missingMask = loop.prerequisite_mask & ~visited;
  if (missingMask) {
    const missing = aliasesInMask(pass, missingMask);
    return `This access needs ${missing.join(", ") || "another table"} earlier in the path.`;
  }
  if (loop.self_mask & visited) return "This table reference already appears in the starting path.";
  if ((loop.flags & loopFlags.automatic) && prefix.rows < 3) {
    return "SQLite screens out this automatic index because it expects too few uses to pay for setup.";
  }
  return null;
}

function startingPaths(pass, round) {
  if (round.depth > 1) return pass.rounds[round.depth - 2].retained;
  return [{path: "", rows: Math.min(pass.query_loop, 48)}];
}

function expansionBranches(pass, round, prefixes, includeUsed) {
  const eventsByPath = new Map();
  for (const event of round.events) {
    if (!eventsByPath.has(event.path)) eventsByPath.set(event.path, []);
    eventsByPath.get(event.path).push(event);
  }
  const retained = new Set(round.retained.map(path => path.path));
  const replacedBy = new Map(round.events
    .filter(event => event.kind === "Update" && event.comparison)
    .map(event => [event.comparison.path, event.path]));

  return prefixes.map(prefix => {
    const visited = [...prefix.path].reduce((mask, id) => mask | pass.loops[id].self_mask, 0);
    const orders = new Map();
    for (const loop of Object.values(pass.loops)) {
      const alreadyUsed = Boolean(loop.self_mask & visited);
      if (alreadyUsed && !includeUsed) continue;
      const path = prefix.path + loop.id;
      const logged = eventsByPath.get(path);
      const reason = logged ? null : screenExtension(pass, prefix, loop, visited);
      const candidates = logged || [{path, kind: reason ? "Ineligible" : "Unlogged",
        reason: reason || "The trace contains no matching decision for this extension."}];
      if (!orders.has(loop.alias)) orders.set(loop.alias, {alias: loop.alias, alreadyUsed, variants: []});
      for (const candidate of candidates) {
        const entered = candidate.kind === "New" || candidate.kind === "Update";
        const survived = retained.has(path) && entered;
        orders.get(loop.alias).variants.push({
          ...candidate, loop, prefix, survived,
          replacedBy: entered && !survived ? replacedBy.get(path) : undefined,
        });
      }
    }
    for (const order of orders.values()) {
      order.variants.sort((a, b) =>
        (a.source_line ?? Infinity) - (b.source_line ?? Infinity));
    }
    return {prefix, orders: [...orders.values()]};
  });
}

function decisionBadge(kind) {
  return dom("span", {class: "decision", "data-kind": kind}, kind);
}

function outcome(candidate) {
  if (candidate.survived) return "Retained";
  if (candidate.replacedBy) return `Replaced by ${candidate.replacedBy}`;
  if (candidate.kind === "New" || candidate.kind === "Update") return "Dropped before round end";
  return "";
}

function renderBranchInspector(run, pass, candidate) {
  const inspector = $("branch-inspector");
  inspector.replaceChildren();
  const title = dom("div", {class: "branch-root"});
  title.append(dom("code", {}, candidate.path),
    dom("strong", {}, labels(candidate.path, pass).map(alias => aliasName(run, alias)).join(" → ")),
    decisionBadge(candidate.kind));
  const result = outcome(candidate);
  if (result) title.append(dom("span", {class: "branch-outcome"}, result));
  inspector.append(title);

  const steps = dom("div", {class: "path-steps", "aria-label": "Access methods in execution order"});
  for (const id of candidate.path) {
    if (steps.childElementCount) steps.append(dom("span", {"aria-hidden": "true"}, "→"));
    const step = dom("span", {class: "path-step"});
    step.append(dom("code", {}, id), dom("span", {}, accessDescription(run, pass.loops[id])));
    steps.append(step);
  }
  inspector.append(steps);
  if (candidate.source_line) {
    const metrics = `Estimated cost ${candidate.cost} · estimated rows ${candidate.rows} (LogEst)`;
    const comparison = candidate.comparison;
    const decision = comparison
      ? `${comparison.relation === "was" ? "Replaces" : "Lost to"} ${comparison.path} (cost ${comparison.cost})`
      : candidate.reason;
    inspector.append(dom("p", {class: "note"}, comparison
      ? decision + ". Estimates below use LogEst."
      : `${metrics}. ${decision}`));
    if (comparison) {
      const choices = dom("div", {class: "cost-comparison", "aria-label": "Path estimates compared"});
      for (const [label, path] of [["Candidate", candidate], ["Competing path", comparison]]) {
        const choice = dom("div", {class: "cost-option"});
        choice.append(dom("span", {}, `${label} · ${path.path}`),
          dom("strong", {}, `Cost ${path.cost} · Rows ${path.rows}`));
        choices.append(choice);
      }
      inspector.append(choices);
    }
    inspector.append(dom("pre", {class: "raw"},
      `Line ${candidate.source_line}  ${run.trace.raw_lines[candidate.source_line - 1]}`));
    return;
  }
  inspector.append(dom("p", {class: "note"}, candidate.reason));
  if (candidate.kind === "Ineligible") {
    inspector.append(dom("p", {class: "source-ref"}, "Inferred from wherePathSolver and the inputs below."));
  }
  const loop = candidate.loop;
  const lines = [`Access method · line ${loop.source_line}  ${run.trace.raw_lines[loop.source_line - 1]}`];
  if (candidate.prefix.source_line) {
    const line = candidate.prefix.source_line;
    lines.unshift(`Starting path · line ${line}  ${run.trace.raw_lines[line - 1]}`);
  }
  inspector.append(dom("pre", {class: "raw"}, lines.join("\n")));
}

let branchEntries = [];
let selectRenderedBranch = () => {};

function renderBranches({run, pass, round}, prefixes, prefixFilter) {
  const visible = prefixFilter === "all" ? prefixes : prefixes.filter(prefix => prefix.path === prefixFilter);
  const branches = expansionBranches(pass, round, visible, $("include-used").checked);
  const graph = $("branch-graph");
  graph.replaceChildren();
  graph.scrollTop = 0;
  const distinctOrders = new Set();
  const buttons = [];
  let logged = 0;
  let ineligible = 0;
  let survived = 0;

  for (const {prefix, orders} of branches) {
    const card = dom("article", {class: "branch-prefix"});
    const heading = dom("h3", {class: "branch-root"});
    const path = prefix.path;
    heading.append(dom("code", {}, path || "∅"),
      dom("span", {}, path ? labels(path, pass).map(alias => aliasName(run, alias)).join(" → ") : "Empty starting path"));
    const tree = dom("ul", {class: "branch-tree"});

    for (const order of orders) {
      const orderedAliases = [...labels(path, pass), order.alias];
      if (!order.alreadyUsed) distinctOrders.add(orderedAliases.join(","));
      const group = dom("li", {class: "branch-order", "data-order": orderedAliases.join(",")});
      const orderHeading = dom("div", {class: "branch-order-title"});
      orderHeading.append(dom("strong", {}, orderedAliases.join(" → ")),
        dom("span", {class: "branch-count"}, order.alreadyUsed ? "Already used" :
          `${order.variants.length} access ${order.variants.length === 1 ? "option" : "options"}`));
      const leaves = dom("ul", {class: "branch-leaves"});

      for (const candidate of order.variants) {
        logged += Number(Boolean(candidate.source_line));
        ineligible += Number(candidate.kind === "Ineligible");
        survived += Number(candidate.survived);
        const leaf = dom("li", {class: "branch-leaf"});
        const button = dom("button", {type: "button", class: "branch-card",
          "data-path": candidate.path, "data-kind": candidate.kind, "aria-pressed": "false"});
        button.append(dom("code", {}, candidate.path), decisionBadge(candidate.kind));
        const status = outcome(candidate);
        if (status) button.append(dom("span", {
          class: candidate.survived ? "branch-outcome survived" : "branch-outcome",
        }, status));
        if (candidate.source_line) button.append(dom("span", {class: "branch-cost"}, `Cost ${candidate.cost}`));
        button.append(dom("span", {class: "branch-method"}, accessDescription(run, candidate.loop, true)));
        leaf.append(button);
        leaves.append(leaf);
        buttons.push({button, candidate});
      }
      group.append(orderHeading, leaves);
      tree.append(group);
    }
    card.append(heading, tree);
    graph.append(card);
  }

  const orderCount = distinctOrders.size;
  text($("expansion-summary"), `${orderCount} distinct table ${orderCount === 1 ? "order" : "orders"} shown · ` +
    `${logged} logged decisions · ${ineligible} inferred ineligible · ${survived} retained. ` +
    (round.depth === 1 ? "Each branch adds a first table." : "Each branch extends a path that survived the previous round."));
  function selectBranch(entry) {
    for (const {button} of buttons) button.setAttribute("aria-pressed", String(button === entry.button));
    renderBranchInspector(run, pass, entry.candidate);
  }
  branchEntries = buttons;
  selectRenderedBranch = (entry, reveal = false) => {
    selectBranch(entry);
    if (reveal) revealBranch(entry.button);
  };
  for (const entry of buttons) {
    entry.button.addEventListener("click", () => {
      if (replay.open) {
        const index = replay.entries.indexOf(entry);
        if (index >= 0) {
          stopPlayback();
          setReplayPosition(index);
          return;
        }
        toggleReplay(false);
      }
      selectBranch(entry);
    });
  }
  const first = buttons.find(entry => entry.candidate.survived) || buttons[0];
  if (first) selectBranch(first);
  else $("branch-inspector").replaceChildren();
  prepareReplay(buttons);
}

function revealBranch(button) {
  const graph = $("branch-graph");
  const bounds = graph.getBoundingClientRect();
  const target = button.getBoundingClientRect();
  if (target.top < bounds.top || target.bottom > bounds.bottom) {
    graph.scrollTop += target.top - bounds.top - 12;
  }
}

const replay = {open: false, index: 0, entries: [], timer: null};

function stopPlayback() {
  clearInterval(replay.timer);
  replay.timer = null;
  text($("replay-play"), "Play");
}

function prepareReplay(buttons) {
  stopPlayback();
  replay.entries = buttons.filter(entry => entry.candidate.source_line)
    .sort((a, b) => a.candidate.source_line - b.candidate.source_line);
  $("replay-toggle").disabled = !replay.entries.length;
  $("replay-play").disabled = replay.entries.length < 2;
  if (replay.open && replay.entries.length) setReplayPosition(0);
  else if (replay.open) toggleReplay(false);
}

function setReplayPosition(index) {
  replay.index = index;
  const entry = replay.entries[index];
  const count = replay.entries.length;
  $("replay-position").max = count;
  $("replay-position").value = index + 1;
  $("replay-back").disabled = index === 0;
  $("replay-next").disabled = index === count - 1;
  text($("replay-counter"), `Decision ${index + 1} of ${count} · ${entry.candidate.kind} ${entry.candidate.path}`);
  replay.entries.forEach(({button}, position) => button.toggleAttribute("data-upcoming", position > index));
  selectRenderedBranch(entry, true);
  if (index === count - 1) stopPlayback();
}

function toggleReplay(open) {
  stopPlayback();
  replay.open = open;
  $("trace-replay").hidden = !open;
  $("replay-toggle").setAttribute("aria-expanded", String(open));
  if (open) setReplayPosition(0);
  else replay.entries.forEach(({button}) => button.removeAttribute("data-upcoming"));
}

const lessonSteps = [
  {round: 0, path: "0", kind: "New", title: "Start with region",
    text: "SQLite can start with any of the three references. Path 0 scans region and applies the AMERICA filter."},
  {round: 1, path: "02", kind: "New", title: "Extend the region scan",
    text: "SQLite adds a nation scan to path 0. Read 02 from left to right as region scan, then nation scan."},
  {round: 1, path: "04", kind: "Update", title: "Keep the index search",
    text: "Path 04 replaces 02. Both visit region then nation. The index search uses the region key and lowers the estimated cost."},
  {round: 1, path: "20", kind: "Skip", title: "Compare a different order",
    text: "Path 20 scans nation first. SQLite compares it with 04 since both reach the same two references and keeps 04."},
  {round: 1, path: "03", kind: "Ineligible", title: "Check the prerequisite",
    text: "Loop 3 looks up nation by primary key using customer’s nation key. Prefix 0 has only region, so SQLite screens out this extension before costing."},
  {round: 2, path: "046", kind: "Update", title: "Finish with customer",
    text: "SQLite extends 04 with a covering-index search on customer. The final retained path 046 runs region, nation, and customer in that order."},
];
let lessonIndex = -1;

function hasLessonEvidence({run, pass}) {
  if (run.id !== "join3" || pass.rounds.length !== 3) return false;
  const second = pass.rounds[1];
  return pass.loops["0"]?.alias === "r"
    && pass.loops["3"]?.prerequisite_mask === pass.loops["6"]?.self_mask
    && pass.rounds[0].events.some(event => event.path === "0" && event.kind === "New")
    && second.events.some(event => event.path === "02" && event.kind === "New")
    && second.events.some(event => event.path === "04" && event.comparison?.path === "02" && event.kind === "Update")
    && second.events.some(event => event.path === "20" && event.comparison?.path === "04" && event.kind === "Skip")
    && !second.events.some(event => event.path === "03")
    && pass.rounds[2].retained.some(path => path.path === "046");
}

function renderLesson(context) {
  const supported = hasLessonEvidence(context);
  $("lesson").hidden = !supported;
  if (lessonIndex >= 0 && (!supported || lessonSteps[lessonIndex].round !== state.round)) lessonIndex = -1;
  const active = lessonIndex >= 0;
  for (const id of ["lesson-back", "lesson-next", "lesson-close"]) $(id).hidden = !active;
  $("lesson-start").hidden = active;
  $("lesson-back").disabled = lessonIndex <= 0;
  const step = lessonSteps[lessonIndex];
  text($("lesson-title"), step ? `${lessonIndex + 1} / ${lessonSteps.length} · ${step.title}` : "Walk through three tables");
  text($("lesson-text"), step?.text || "Follow a region scan through an index replacement, a rejected order, and the final join path.");
  text($("lesson-next"), lessonIndex === lessonSteps.length - 1 ? "Finish" : "Continue");
}

function goToLesson(index) {
  toggleReplay(false);
  lessonIndex = index;
  state.round = lessonSteps[index].round;
  state.selection = null;
  $("prefix-filter").value = "all";
  render();
  const step = lessonSteps[index];
  const entry = branchEntries.find(({candidate}) => candidate.path === step.path && candidate.kind === step.kind);
  if (entry) selectRenderedBranch(entry, true);
}

function endLesson() {
  lessonIndex = -1;
  renderLesson(current());
}

function renderAccessKey({run, pass}) {
  const body = $("access-key");
  body.replaceChildren();
  for (const loop of Object.values(pass.loops).sort((a, b) => a.source_line - b.source_line)) {
    const row = dom("tr");
    const code = dom("td");
    code.append(dom("code", {}, loop.id));
    const method = dom("td", {}, accessDescription(run, loop));
    if (loop.disabled_by_interstage) method.append(dom("span", {class: "branch-count"}, " · disabled between passes"));
    const dependencies = aliasesInMask(pass, loop.prerequisite_mask).join(", ");
    row.append(code, method, dom("td", {}, dependencies || "None"));
    body.append(row);
  }
  text($("access-example"), run.id === "join3"
    && pass.loops["0"] && pass.loops["2"]
    ? `Read 02 left to right. 0 = ${accessDescription(run, pass.loops["0"])}. 2 = ${accessDescription(run, pass.loops["2"])}.`
    : "Read a path from left to right, from the outermost loop to the innermost. Codes belong to the selected query.");
}

let lastExpansionRound;
function renderSearchView() {
  const context = current();
  const retainedView = $("search-view").value === "retained";
  $("expansion-view").hidden = retainedView;
  $("retained-view").hidden = !retainedView;
  renderAccessKey(context);
  if (retainedView) {
    toggleReplay(false);
    lessonIndex = -1;
    return;
  }
  renderLesson(context);

  const {run, pass, round} = context;
  const prefixes = startingPaths(pass, round);
  const filter = $("prefix-filter");
  if (round !== lastExpansionRound) {
    filter.replaceChildren(dom("option", {value: "all"}, "All starting paths"),
      ...prefixes.filter(prefix => prefix.path).map(prefix => dom("option", {value: prefix.path},
        `${prefix.path} · ${labels(prefix.path, pass).join(" → ")}`)));
    filter.disabled = prefixes.length === 1 && !prefixes[0].path;
    filter.value = run.graph.nodes.length > 4 && prefixes[0].path ? prefixes[0].path : "all";
    lastExpansionRound = round;
  }
  renderBranches(context, prefixes, filter.value);
}

$("search-view").addEventListener("change", renderSearchView);
$("prefix-filter").addEventListener("change", () => {
  endLesson();
  renderSearchView();
});
$("include-used").addEventListener("change", renderSearchView);
$("replay-toggle").addEventListener("click", () => {
  endLesson();
  toggleReplay(!replay.open);
});
$("replay-back").addEventListener("click", () => {
  stopPlayback();
  setReplayPosition(replay.index - 1);
});
$("replay-next").addEventListener("click", () => {
  stopPlayback();
  setReplayPosition(replay.index + 1);
});
$("replay-position").addEventListener("input", event => {
  stopPlayback();
  setReplayPosition(Number(event.target.value) - 1);
});
$("replay-play").addEventListener("click", () => {
  if (replay.timer !== null) {
    stopPlayback();
    return;
  }
  if (replay.entries.length < 2) return;
  if (replay.index === replay.entries.length - 1) setReplayPosition(0);
  text($("replay-play"), "Pause");
  replay.timer = setInterval(() => setReplayPosition(replay.index + 1), 1250);
});
$("lesson-start").addEventListener("click", () => {
  goToLesson(0);
  $("lesson-next").focus();
});
$("lesson-back").addEventListener("click", () => goToLesson(lessonIndex - 1));
$("lesson-next").addEventListener("click", () => {
  if (lessonIndex === lessonSteps.length - 1) {
    endLesson();
    $("lesson-start").focus();
  } else {
    goToLesson(lessonIndex + 1);
  }
});
$("lesson-close").addEventListener("click", () => {
  endLesson();
  $("lesson-start").focus();
});

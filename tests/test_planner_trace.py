"""Evidence-driven regression checks; run python3 -m unittest discover -s tests."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from capture_traces import capture, query_definitions
from planner_trace import TraceError, parse_trace, validate_trace


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads((ROOT / "evidence/project.json").read_text())
        cls.runs = {r["id"]: r for r in cls.bundle["runs"]}

    def test_three_table_hand_verified_rounds(self):
        block = self.runs["join3"]["trace"]["blocks"][0]
        rounds = block["passes"][0]["rounds"]
        self.assertEqual([[(p["path"], p["cost"], p["rows"]) for p in r["retained"]]
                         for r in rounds],
                         [[("0", 40, 3), ("2", 62, 46), ("5", 178, 172)],
                          [("04", 56, 26), ("26", 177, 171), ("05", 181, 175)],
                          [("046", 157, 151)]])
        update = next(e for e in rounds[1]["events"] if e["path"] == "04")
        self.assertEqual(update["kind"], "Update")
        self.assertEqual(update["comparison"]["path"], "02")
        self.assertEqual(update["comparison"]["cost"], 67)

    def test_q8_comparison_and_multiple_passes(self):
        baseline = self.runs["q8_default"]["trace"]["blocks"][0]
        disabled = self.runs["q8_starquery_disabled"]["trace"]["blocks"][0]
        self.assertEqual(baseline["path_limit"], 18)
        self.assertEqual(disabled["path_limit"], 12)
        self.assertEqual(len(baseline["passes"]), 2)
        self.assertEqual([r["depth"] for r in baseline["passes"][1]["rounds"]], list(range(1, 9)))
        self.assertEqual(self.runs["q8_default"]["trace"]["eqp"], self.runs["q8_starquery_disabled"]["trace"]["eqp"])
        self.assertNotEqual(baseline["event_counts"], disabled["event_counts"])
        self.assertNotEqual(baseline["passes"][0]["loops"], baseline["passes"][1]["loops"])
        self.assertFalse(any(l["disabled_by_interstage"] for l in baseline["passes"][0]["loops"].values()))
        self.assertTrue(any(l["disabled_by_interstage"] for l in baseline["passes"][1]["loops"].values()))

    def test_fresh_readonly_capture_matches_saved_evidence(self):
        for definition in query_definitions():
            with self.subTest(run=definition["id"]):
                run, raw, _ = capture(ROOT / "build/sqlite-debug/sqlite3d",
                                      ROOT / "data/tpch-sf1/tpch.db", definition, 30)
                self.assertEqual(run["trace"], self.runs[definition["id"]]["trace"])
                self.assertEqual(raw, (ROOT / "evidence" / f"{definition['id']}.trace.txt").read_text())

    def test_versions_and_truncation_fail_clearly(self):
        raw = (ROOT / "evidence/join3.trace.txt").read_text()
        for broken in [raw.replace("*** Optimizer Finished ***", ""),
                       raw.replace("---- after round 1 ----", "---- after round 9 ----"),
                       raw.replace("Update 04", "Update 04 BROKEN"),
                       raw.split("QUERY PLAN")[0]]:
            with self.subTest(input=broken[-80:]):
                with self.assertRaises(TraceError):
                    parse_trace(broken)
        with self.assertRaisesRegex(TraceError, "Unsupported SQLite version"):
            parse_trace(raw, "3.55.0")

    def test_corrupt_paths_dependencies_and_eqp_are_rejected(self):
        for mutation in ("repeat", "dependency", "disabled", "unknown", "eqp"):
            trace = copy.deepcopy(self.runs["join3"]["trace"])
            solver = trace["blocks"][0]["passes"][0]
            if mutation == "repeat":
                solver["loops"]["4"]["self_mask"] = 1
            elif mutation == "dependency":
                solver["loops"]["4"]["prerequisite_mask"] = 4
            elif mutation == "disabled":
                solver["loops"]["4"]["disabled_by_interstage"] = True
            elif mutation == "unknown":
                del solver["loops"]["4"]
            else:
                trace["eqp"][0] = "|--SCAN c"
            with self.subTest(mutation=mutation), self.assertRaises(TraceError):
                validate_trace(trace)

    def test_invocations_have_separate_id_scopes(self):
        raw = (ROOT / "evidence/join3.trace.txt").read_text()
        optimizer = raw.split("QUERY PLAN")[0]
        trace = parse_trace(optimizer + raw)
        self.assertEqual(len(trace["blocks"]), 2)
        self.assertIsNot(trace["blocks"][0]["loops"], trace["blocks"][1]["loops"])


if __name__ == "__main__":
    unittest.main()

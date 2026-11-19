#!/usr/bin/env python3
"""Build an evidence-populated Markdown and Word report.

Run with Python containing python-docx and Pillow. The Word report is then
rendered and checked with the Documents skill's bundled render_docx.py.
"""

import argparse
import json
import os
from pathlib import Path
import re
import textwrap

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]


def markdown_table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |",
                      "| " + " | ".join("---" for _ in headers) + " |",
                      *("| " + " | ".join(map(str, row)) + " |" for row in rows)])


def populate():
    bundle = json.loads((ROOT / "evidence/project.json").read_text())
    observations = json.loads((ROOT / "evidence/debugger/observations.json").read_text())
    runs = {run["id"]: run for run in bundle["runs"]}
    base = runs["q8_default"]["trace"]["blocks"][0]
    off = runs["q8_starquery_disabled"]["trace"]["blocks"][0]
    if base["event_counts"] != {"New": 199, "Update": 154, "Skip": 470} or off["event_counts"] != {"New": 161, "Update": 96, "Skip": 333}:
        raise ValueError("Evidence changed: review report interpretations and update the narrative before rebuilding")
    if not any("candidate=04 old=02 newCost=56 oldCost=67" in item
               for obs in observations for item in obs["replacement"]):
        raise ValueError("Missing genuine three-table debugger replacement evidence")
    meta = bundle["metadata"]
    small = runs["join3"]["trace"]["blocks"][0]
    loops = small["passes"][0]["loops"]
    replacements = {
        "SQLITE_VERSION": meta["sqlite_version"], "SOURCE_ID": meta["sqlite_source_id"],
        "DATABASE_BYTES": f"{meta['database']['bytes']:,}",
        "DATASET_TABLE": markdown_table(["Table", "Recorded rows"],
            [(name, f"{count:,}") for name, count in meta["dataset_summary"]["tables"].items()]),
        "LOOP_TABLE": markdown_table(["ID", "Access method", "Self", "Requires", "Run", "Output"],
            [(key, loop["access"], f"{loop['self_mask']:x}", f"{loop['prerequisite_mask']:x}",
              loop["run"], loop["rows"]) for key, loop in loops.items()]),
        "SMALL_ROUND_TABLE": markdown_table(["Depth", "Retained paths with cost and output LogEst"],
            [(r["depth"], "; ".join(f"{p['path']}: {p['cost']}, {p['rows']}" for p in r["retained"]))
             for r in small["passes"][0]["rounds"]]),
        "GDB_TABLE": markdown_table(["Setting", "Pass", "mxChoice", "nRowEst", "nOrderBy", "Star"],
            [("Default" if obs["run"] == "q8_default" else "Disabled", i + 1,
              stop["mxChoice"], stop["nRowEst"], stop["nOrderBy"], stop["star"])
             for obs in observations if obs["run"].startswith("q8_")
             for i, stop in enumerate(obs["solver_stops"])]),
        "Q8_ROUND_TABLE": markdown_table(["Depth", "Default pass 1", "Disabled pass 1", "Pass 2 both"],
            [(i+1, len(base["passes"][0]["rounds"][i]["retained"]),
              len(off["passes"][0]["rounds"][i]["retained"]),
              len(base["passes"][1]["rounds"][i]["retained"])) for i in range(8)]),
        "COMPARISON_TABLE": markdown_table(["Setting", "N", "New", "Update", "Skip", "Total"],
            [(label, b["path_limit"], b["event_counts"]["New"], b["event_counts"]["Update"],
              b["event_counts"]["Skip"], sum(b["event_counts"].values()))
             for label, b in [("Default", base), ("Star disabled", off)]]),
        "FRAMEWORK_TABLE": markdown_table(["Approach", "Main search representation", "How alternatives survive"], [
            ("NN", "One growing loop sequence", "One locally attractive prefix"),
            ("SQLite N3", "Bounded frontier of WherePaths", "Subset and ordering comparison plus N-slot capacity"),
            ("System R", "Subset plans and interesting orders", "Dynamic-programming access alternatives"),
            ("Cascades", "Memo groups and optimization tasks", "Rules, properties and cost-guided search")]),
    }
    source = (ROOT / "src/sqlite-src-3540100/src/where.c").read_text().splitlines()
    symbols = [("sqlite3WhereBegin", "Coordinates WHERE planning"),
               ("whereLoopAddAll", "Builds access alternatives"),
               ("whereLoopInsert", "Compares access-method candidates"),
               ("computeMxChoice", "Sets breadth and adjusts star costs"),
               ("wherePathSolver", "Extends and retains partial paths"),
               ("whereInterstageHeuristic", "Restricts loops between passes")]
    rows = []
    for name, role in symbols:
        number = next(i for i, line in enumerate(source, 1)
                      if re.match(r"^(?:static |SQLITE_NOINLINE |int |WhereInfo \*)+.*\b" + name + r"\(", line))
        rows.append((name, number, role))
    replacements["SOURCE_MAP"] = markdown_table(["Symbol in where.c", "Line", "Role"], rows)
    content = (ROOT / "docs/report.md").read_text()
    for token, value in replacements.items():
        content = content.replace("{{" + token + "}}", value)
    if re.search(r"\{\{\w+\}\}", content):
        raise ValueError("Unexpanded report token")
    return content


def inline(paragraph, content):
    for index, part in enumerate(re.split(r"(`[^`]+`)", content)):
        if not part:
            continue
        run = paragraph.add_run(part[1:-1] if part.startswith("`") else part)
        if part.startswith("`"):
            run.font.name = "DejaVu Sans Mono"
            run.font.size = Pt(9)


def set_cell_fill(cell, fill):
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def add_table(document, lines):
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in lines]
    headers, values = rows[0], rows[2:]
    table = document.add_table(rows=1, cols=len(headers))
    table.autofit = False
    # Deliberate widths: ID/number columns are narrower than explanation columns.
    if headers[0] == "ID":
        widths = [.35, 3.0, .5, .85, .6, .85]
    elif len(headers) == 2:
        widths = [1.65, 4.9] if headers[0] != "Depth" else [.7, 5.85]
    elif len(headers) == 3:
        widths = [1.6, 2.3, 2.65] if headers[0] == "Approach" else [2.15, .45, 3.95]
    elif len(headers) == 4:
        widths = [.65, 1.9, 2.0, 2.0]
    else:
        widths = [1.65, .55, 1.05, 1.1, 1.1, 1.1] if headers[0] == "Setting" and headers[-1] == "Star" else [1.75, .55, 1.0, 1.15, 1.0, 1.1]
    for col, width in zip(table.columns, widths):
        col.width = Inches(width)
    properties = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        item = OxmlElement("w:" + edge)
        for key, value in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
            item.set(qn("w:" + key), value)
        borders.append(item)
    properties.append(borders)
    repeat = OxmlElement("w:tblHeader")
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for i, row_values in enumerate([headers, *values]):
        cells = table.rows[0].cells if i == 0 else table.add_row().cells
        row = table.rows[i]
        cant_split = OxmlElement("w:cantSplit")
        row._tr.get_or_add_trPr().append(cant_split)
        for j, (cell, value) in enumerate(zip(cells, row_values)):
            cell.width = Inches(widths[j])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            margin = OxmlElement("w:tcMar")
            for side in ("top", "left", "bottom", "right"):
                edge = OxmlElement("w:" + side)
                edge.set(qn("w:w"), "85")
                edge.set(qn("w:type"), "dxa")
                margin.append(edge)
            cell._tc.get_or_add_tcPr().append(margin)
            set_cell_fill(cell, "19384B" if i == 0 else "F0F4F7" if i % 2 == 0 else "FFFFFF")
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1.05
            if (j > 0 and re.fullmatch(r"[0-9,]+", value)) or headers[j] in ("ID", "Depth", "Pass", "N", "Self", "Requires"):
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run(value)
            run.font.name = "Liberation Sans"
            run.font.size = Pt(9.3)
            run.bold = i == 0
            if i == 0:
                run.font.color.rgb = RGBColor.from_string("FFFFFF")
    document.add_paragraph().paragraph_format.space_after = Pt(2)


def build_docx(content, target):
    document = Document()
    # The bundled default template carries an ornamental blue Title border.
    # Remove inherited paragraph borders so this report has a plain title.
    for border in document.styles.element.xpath(".//w:pBdr"):
        border.getparent().remove(border)
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin, section.bottom_margin = Inches(.73), Inches(.7)
    section.left_margin, section.right_margin = Inches(.85), Inches(.85)
    normal = document.styles["Normal"]
    normal.font.name = "Liberation Serif"
    normal.font.size = Pt(11.5)
    normal.paragraph_format.line_spacing = 1.12
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.widow_control = True
    for name, size in (("Title", 24), ("Heading 1", 16), ("Heading 2", 12.5)):
        style = document.styles[name]
        style.font.name = "DejaVu Sans"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string("000000" if name == "Title" else "19384B")
        style.paragraph_format.space_before = Pt(7)
        style.paragraph_format.space_after = Pt(12)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    document.core_properties.title = "Query Optimization in SQLite"
    document.core_properties.author = "Jashandeep Singh Bedi"
    document.core_properties.subject = "Source investigation and observed join search"

    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line == "<!-- pagebreak -->":
            document.add_page_break()
            i += 1
            continue
        if line.startswith("# "):
            document.add_paragraph(line[2:], "Title")
            i += 1
            continue
        if line.startswith("## "):
            document.add_paragraph(line[3:], "Heading 1")
            i += 1
            continue
        if line.startswith("```"):
            i += 1
            block = []
            while i < len(lines) and not lines[i].startswith("```"):
                block.extend(textwrap.wrap(lines[i], width=85, replace_whitespace=False, drop_whitespace=False) or [""])
                i += 1
            para = document.add_paragraph()
            para.paragraph_format.space_before = Pt(3)
            para.paragraph_format.space_after = Pt(10)
            para.paragraph_format.line_spacing = 1.1
            run = para.add_run("\n".join(block))
            run.font.name = "DejaVu Sans Mono"
            run.font.size = Pt(8.4)
            i += 1
            continue
        if line.startswith("| "):
            table_lines = []
            while i < len(lines) and lines[i].startswith("| "):
                table_lines.append(lines[i])
                i += 1
            add_table(document, table_lines)
            continue
        image_match = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", line)
        if image_match:
            path = (ROOT / "docs" / image_match[2]).resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Missing report figure {path}; run the browser smoke test first")
            para = document.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.keep_with_next = True
            width = 4.8 if any(name in path.name for name in ("join_graph", "three_table_paths")) else 6.7
            picture = para.add_run().add_picture(str(path), width=Inches(width))
            picture._inline.docPr.set("descr", image_match[1])
            i += 1
            continue
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "```", "| ", "![", "<!--")):
            para_lines.append(lines[i])
            i += 1
        paragraph = document.add_paragraph()
        combined = para_lines[0].strip()
        for previous, part in zip(para_lines, para_lines[1:]):
            combined += ("\n" if previous.endswith("  ") else " ") + part.strip()
        inline(paragraph, combined)
        if line.startswith("Figure "):
            paragraph.paragraph_format.space_after = Pt(12)
            for run in paragraph.runs:
                run.italic = True
                run.font.size = Pt(10)
    document.save(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/report")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    content = populate()
    figure_prefix = os.path.relpath(ROOT / "output/figures", args.output.resolve())
    (args.output / "query_optimization_sqlite.md").write_text(
        content.replace("../output/figures/", figure_prefix + "/"))
    target = args.output / "query_optimization_sqlite.docx"
    build_docx(content, target)
    print("Wrote", target, "with", len(content.split()), "Markdown words")


if __name__ == "__main__":
    main()

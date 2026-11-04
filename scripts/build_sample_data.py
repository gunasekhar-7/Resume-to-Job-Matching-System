"""Build the synthetic sample corpus as real PDF/DOCX/TXT files.

Usage:
    python scripts/build_sample_data.py [--force]

Outputs (all synthetic, safe to commit):
    data/sample/resumes/*.pdf|docx|txt
    data/sample/jobs/jobs.json
    data/sample/jobs/jobs.csv
    data/sample/fixtures/{corrupt.pdf,empty.pdf,scanned.pdf}
    data/sample/manifest.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from docx import Document  # noqa: E402
from docx.shared import Pt  # noqa: E402
from fpdf import FPDF  # noqa: E402

from talentlens.sample_data.corpus import JOBS, RESUMES  # noqa: E402

SAMPLE_DIR = ROOT / "data" / "sample"
RESUME_DIR = SAMPLE_DIR / "resumes"
JOB_DIR = SAMPLE_DIR / "jobs"
FIXTURE_DIR = SAMPLE_DIR / "fixtures"


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def latin1(text: str) -> str:
    """fpdf core fonts are latin-1; replace unsupported glyphs deterministically."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def resume_sections(resume: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Flatten a corpus resume into ordered (heading, lines) blocks."""
    blocks: list[tuple[str, list[str]]] = []
    blocks.append(("PROFILE", [resume["headline"], *resume["summary"]]))
    skill_lines = [f"{group}: {', '.join(skills)}" for group, skills in resume["skills"].items()]
    blocks.append(("TECHNICAL SKILLS", skill_lines))
    experience_lines: list[str] = []
    for role in resume["experience"]:
        experience_lines.append(f"{role['title']} | {role['company']} | {role['start']} - {role['end']}")
        if role.get("location"):
            experience_lines.append(role["location"])
        experience_lines.extend(f"- {bullet}" for bullet in role["bullets"])
    blocks.append(("PROFESSIONAL EXPERIENCE", experience_lines))
    if resume.get("projects"):
        project_lines: list[str] = []
        for project in resume["projects"]:
            project_lines.append(project["name"])
            project_lines.extend(f"- {bullet}" for bullet in project["bullets"])
        blocks.append(("SELECTED PROJECTS", project_lines))
    education_lines = [
        f"{item['degree']} - {item['institution']} ({item['year']})" for item in resume["education"]
    ]
    blocks.append(("EDUCATION", education_lines))
    if resume.get("certifications"):
        blocks.append(("CERTIFICATIONS", list(resume["certifications"])))
    if resume.get("publications"):
        blocks.append(("PUBLICATIONS", list(resume["publications"])))
    return blocks


def contact_lines(resume: dict[str, Any]) -> list[str]:
    return [
        resume["name"],
        resume["headline"],
        resume["email"],
        resume["phone"],
        resume["location"],
        *resume.get("links", []),
    ]


# --------------------------------------------------------------------------- #
# PDF rendering
# --------------------------------------------------------------------------- #
class ResumePDF(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4", unit="mm")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(15, 15, 15)

    def footer(self) -> None:  # running footer to exercise header/footer noise removal
        self.set_y(-12)
        self.set_font("Helvetica", size=7)
        self.set_text_color(120)
        self.cell(0, 5, f"Confidential - TalentLens synthetic sample | Page {self.page_no()}", align="C")


def _write_block(pdf: ResumePDF, x: float, y: float, width: float, text: str, size: float, lh: float,
                 *, bold: bool = False, heading: bool = False) -> float:
    pdf.set_font("Helvetica", style="B" if bold or heading else "", size=size)
    if heading:
        pdf.set_text_color(20, 40, 90)
    else:
        pdf.set_text_color(30, 30, 30)
    pdf.set_xy(x, y)
    line_count = max(1, math.ceil(pdf.get_string_width(latin1(text)) / (width - 2)))
    if pdf.get_y() + line_count * lh > pdf.h - 20:
        pdf.add_page()
        y = pdf.get_y()
        pdf.set_xy(x, y)
    pdf.multi_cell(width, lh, latin1(text), new_x="LEFT", new_y="NEXT")
    return pdf.get_y() + (1.5 if not heading else 2.5)


def render_single_column(resume: dict[str, Any], path: Path) -> None:
    pdf = ResumePDF()
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=17)
    pdf.set_text_color(20, 40, 90)
    pdf.multi_cell(0, 8, latin1(resume["name"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(70)
    contact = " | ".join([resume["email"], resume["phone"], resume["location"]])
    pdf.multi_cell(0, 5, latin1(contact), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    y = pdf.get_y()
    for heading, lines in resume_sections(resume):
        y = _write_block(pdf, pdf.l_margin, y, pdf.epw, heading.upper(), 10.5, 5.5, heading=True)
        for line in lines:
            y = _write_block(pdf, pdf.l_margin, y, pdf.epw, line, 8.8, 4.6)
        y += 1.5
    pdf.output(str(path))


def render_two_column(resume: dict[str, Any], path: Path) -> None:
    """Left column: contact, skills, education. Right column: summary/experience/projects."""
    pdf = ResumePDF()
    pdf.add_page()
    margin = 12.0
    gutter = 7.0
    total = pdf.w - 2 * margin
    left_w = total * 0.34
    right_w = total - left_w - gutter
    right_x = margin + left_w + gutter

    # Left column
    left_y = margin
    left_y = _write_block(pdf, margin, left_y, left_w, resume["name"], 13, 6, bold=True)
    for line in [resume["headline"], resume["email"], resume["phone"], resume["location"], *resume.get("links", [])]:
        left_y = _write_block(pdf, margin, left_y, left_w, line, 7.6, 4.0)
    left_y += 2
    left_y = _write_block(pdf, margin, left_y, left_w, "SKILLS", 9.5, 5, heading=True)
    for group, skills in resume["skills"].items():
        left_y = _write_block(pdf, margin, left_y, left_w, group, 7.8, 4.2, bold=True)
        left_y = _write_block(pdf, margin, left_y, left_w, ", ".join(skills), 7.5, 4.0)
        left_y += 1
    left_y = _write_block(pdf, margin, left_y, left_w, "EDUCATION", 9.5, 5, heading=True)
    for item in resume["education"]:
        left_y = _write_block(
            pdf, margin, left_y, left_w, f"{item['degree']}\n{item['institution']} ({item['year']})", 7.5, 4.0
        )

    # Right column
    right_y = margin
    right_y = _write_block(pdf, right_x, right_y, right_w, "PROFESSIONAL SUMMARY", 10.5, 5.5, heading=True)
    for line in resume["summary"]:
        right_y = _write_block(pdf, right_x, right_y, right_w, line, 8.3, 4.4)
    right_y += 2
    right_y = _write_block(pdf, right_x, right_y, right_w, "EXPERIENCE", 10.5, 5.5, heading=True)
    for role in resume["experience"]:
        right_y = _write_block(
            pdf, right_x, right_y, right_w,
            f"{role['title']}, {role['company']}", 8.6, 4.6, bold=True,
        )
        right_y = _write_block(
            pdf, right_x, right_y, right_w, f"{role['start']} - {role['end']} | {role.get('location', '')}", 7.5, 4.0
        )
        for bullet in role["bullets"]:
            right_y = _write_block(pdf, right_x, right_y, right_w, f"- {bullet}", 8.1, 4.3)
        right_y += 1
    if resume.get("projects"):
        right_y = _write_block(pdf, right_x, right_y, right_w, "PROJECTS", 10.5, 5.5, heading=True)
        for project in resume["projects"]:
            right_y = _write_block(pdf, right_x, right_y, right_w, project["name"], 8.6, 4.6, bold=True)
            for bullet in project["bullets"]:
                right_y = _write_block(pdf, right_x, right_y, right_w, f"- {bullet}", 8.1, 4.3)
    pdf.output(str(path))


def render_table_layout(resume: dict[str, Any], path: Path) -> None:
    pdf = ResumePDF()
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.set_text_color(20, 40, 90)
    pdf.multi_cell(0, 8, latin1(resume["name"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=8.5)
    pdf.set_text_color(70)
    pdf.multi_cell(
        0, 5, latin1(" | ".join([resume["email"], resume["phone"], resume["location"]])),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(3)

    pdf.set_font("Helvetica", style="B", size=10)
    pdf.set_text_color(20, 40, 90)
    pdf.cell(0, 6, "CORE COMPETENCIES", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    pdf.set_draw_color(160)
    pdf.set_text_color(30)
    row_height = 7.0
    col_width = pdf.epw / 2
    for group, skills in resume["skills"].items():
        y_before = pdf.get_y()
        pdf.set_font("Helvetica", style="B", size=8.4)
        pdf.set_xy(pdf.l_margin, y_before)
        pdf.cell(col_width, row_height, latin1(group), border=1)
        pdf.set_font("Helvetica", size=8.0)
        pdf.cell(col_width, row_height, latin1(", ".join(skills)), border=1)
        pdf.ln(row_height)
    pdf.ln(4)

    y = pdf.get_y()
    for heading, lines in resume_sections(resume)[2:]:
        y = _write_block(pdf, pdf.l_margin, y, pdf.epw, heading.upper(), 10, 5.5, heading=True)
        for line in lines:
            y = _write_block(pdf, pdf.l_margin, y, pdf.epw, line, 8.6, 4.5)
        y += 1.5
    pdf.output(str(path))


# --------------------------------------------------------------------------- #
# DOCX rendering
# --------------------------------------------------------------------------- #
def render_docx(resume: dict[str, Any], path: Path) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    doc.add_heading(resume["name"], level=0)
    contact = " | ".join([resume["email"], resume["phone"], resume["location"], *resume.get("links", [])])
    doc.add_paragraph(contact)

    two_column = resume["layout"] == "two_column"
    if two_column:
        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        left, right = table.rows[0].cells

        def add_lines(cell, heading: str, lines: list[str]) -> None:
            cell.add_paragraph(heading).runs[0].bold = True
            for line in lines:
                cell.add_paragraph(line)

        add_lines(left, "SKILLS", [f"{g}: {', '.join(s)}" for g, s in resume["skills"].items()])
        add_lines(left, "EDUCATION", [f"{e['degree']} - {e['institution']} ({e['year']})" for e in resume["education"]])
        add_lines(right, "SUMMARY", [resume["headline"], *resume["summary"]])
        exp_lines: list[str] = []
        for role in resume["experience"]:
            exp_lines.append(f"{role['title']} | {role['company']} | {role['start']} - {role['end']}")
            exp_lines.extend(f"- {b}" for b in role["bullets"])
        add_lines(right, "EXPERIENCE", exp_lines)
        doc.save(str(path))
        return

    if resume["layout"] == "table_skills":
        doc.add_heading("Core Competencies", level=1)
        table = doc.add_table(rows=0, cols=2)
        table.style = "Light Grid Accent 1"
        for group, skills in resume["skills"].items():
            cells = table.add_row().cells
            cells[0].text = group
            cells[1].text = ", ".join(skills)

    for heading, lines in resume_sections(resume):
        if resume["layout"] == "table_skills" and heading == "TECHNICAL SKILLS":
            continue
        doc.add_heading(heading.title(), level=1)
        for line in lines:
            if line.startswith("- "):
                doc.add_paragraph(line[2:], style="List Bullet")
            else:
                doc.add_paragraph(line)
    doc.save(str(path))


def render_txt(resume: dict[str, Any], path: Path) -> None:
    lines = [resume["name"], resume["headline"], resume["email"], resume["phone"], resume["location"], ""]
    for heading, block in resume_sections(resume):
        lines.append(heading)
        lines.extend(block)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Fixtures and jobs
# --------------------------------------------------------------------------- #
def render_fixtures() -> dict[str, str]:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}

    corrupt = FIXTURE_DIR / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\nthis is not a valid pdf body\n%%EOF")
    results["corrupt.pdf"] = sha256(corrupt)

    empty = ResumePDF()
    empty.add_page()
    empty.output(str(FIXTURE_DIR / "empty.pdf"))
    results["empty.pdf"] = sha256(FIXTURE_DIR / "empty.pdf")

    scanned = ResumePDF()
    scanned.add_page()
    scanned.set_fill_color(235, 235, 235)
    scanned.rect(20, 20, 170, 250, style="F")
    scanned.set_draw_color(180)
    for offset in range(30, 250, 14):
        scanned.line(25, offset, 185, offset)
    scanned.output(str(FIXTURE_DIR / "scanned.pdf"))
    results["scanned.pdf"] = sha256(FIXTURE_DIR / "scanned.pdf")

    unsupported = FIXTURE_DIR / "not_a_resume.exe"
    unsupported.write_bytes(b"MZ\x90\x00fake executable")
    results["not_a_resume.exe"] = sha256(unsupported)
    return results


def build_jobs() -> tuple[str, str]:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    jobs_path = JOB_DIR / "jobs.json"
    jobs_path.write_text(json.dumps(JOBS, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_path = JOB_DIR / "jobs.csv"
    columns = [
        "id", "title", "company", "location", "seniority", "employment_type", "work_arrangement",
        "min_years_experience", "max_years_experience", "education_level", "posted_date", "source",
        "summary", "responsibilities", "required_skills", "preferred_skills", "certifications", "raw_text",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for job in JOBS:
            row = {key: job.get(key, "") for key in columns}
            for list_key in ("responsibilities", "required_skills", "preferred_skills", "certifications"):
                value = row.get(list_key)
                row[list_key] = " | ".join(value) if isinstance(value, list) else (value or "")
            writer.writerow(row)
    return sha256(jobs_path), sha256(csv_path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(force: bool = False) -> int:
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "corpus": "synthetic-talentlens-v1",
        "note": "All people, companies and contact details are fictional. Generated by scripts/build_sample_data.py.",
        "resumes": [],
        "jobs": {},
        "fixtures": {},
    }

    for resume in RESUMES:
        entry: dict[str, Any] = {
            "resume_id": resume["id"],
            "name": resume["name"],
            "layout": resume["layout"],
            "files": [],
        }
        for fmt in resume["formats"]:
            filename = f"{resume['id']}_{resume['name'].split()[0].lower()}_{resume['layout']}.{fmt}"
            path = RESUME_DIR / filename
            if force or not path.exists():
                if fmt == "pdf":
                    if resume["layout"] == "two_column":
                        render_two_column(resume, path)
                    elif resume["layout"] == "table_skills":
                        render_table_layout(resume, path)
                    else:
                        render_single_column(resume, path)
                elif fmt == "docx":
                    render_docx(resume, path)
                elif fmt == "txt":
                    render_txt(resume, path)
            entry["files"].append({"path": f"data/sample/resumes/{filename}", "sha256": sha256(path), "format": fmt})
        manifest["resumes"].append(entry)

    jobs_json_sha, jobs_csv_sha = build_jobs()
    manifest["jobs"] = {
        "json": {"path": "data/sample/jobs/jobs.json", "sha256": jobs_json_sha, "count": len(JOBS)},
        "csv": {"path": "data/sample/jobs/jobs.csv", "sha256": jobs_csv_sha},
    }
    manifest["fixtures"] = render_fixtures()

    (SAMPLE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (SAMPLE_DIR / "README.md").write_text(
        "# Synthetic sample data\n\n"
        "Every resume, person, company and job posting in this directory is fictional and was\n"
        "generated by `scripts/build_sample_data.py` for testing and demonstration. Contact\n"
        "details use reserved example domains. Do not treat these documents as real candidates.\n\n"
        "- `resumes/` - PDF, DOCX and TXT variants across single-column, two-column and table layouts.\n"
        "- `jobs/` - 23 synthetic job postings as JSON and CSV (one intentionally unstructured).\n"
        "- `fixtures/` - corrupt, empty and image-only PDFs plus an unsupported file type.\n"
        "- `manifest.json` - resume/job IDs with content hashes used by evaluation scripts.\n",
        encoding="utf-8",
    )

    total_files = sum(len(entry["files"]) for entry in manifest["resumes"])
    print(f"Resumes: {len(manifest['resumes'])} ({total_files} files)")
    print(f"Jobs: {len(JOBS)}")
    print(f"Fixtures: {len(manifest['fixtures'])}")
    print(f"Manifest: {SAMPLE_DIR / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build synthetic sample data")
    parser.add_argument("--force", action="store_true", help="Regenerate existing files")
    args = parser.parse_args()
    raise SystemExit(main(force=args.force))

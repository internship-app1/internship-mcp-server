"""Vendored deterministic compile core — pdflatex + template.tex.

PARITY RULE (non-negotiable): this module is a by-value copy of the
deterministic functions in internship-app/resume_tailor/tailor_resume.py
(compile_resume_json_to_pdf and its helpers). Local output MUST match the
backend /api/v1/resume/compile output: same pdflatex, same template.tex,
same font ladder and spacing presets. Do NOT substitute tectonic/XeTeX.
If you change anything here, change the backend copy and the parity test
in the same PR.

NO Claude calls. Widow FIXING is the agent's job — this module only reports
widows in diagnostics.
"""
import copy
import io
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import pdfplumber

from . import config

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent / "template.tex"

FONT_SIZES = [14, 12, 11, 10, 9, 8]
_ANCHOR_FONT = 11
UNDERFILL_RATIO = 0.85
WIDOW_THRESHOLD = 0.85
BACKSTOP_FLOOR = 0.70
_BULLET_GLYPH = "•"

_SPACING_PRESETS = {
    "tight": {
        "PARSKIP": "0pt", "SEC_BEFORE": "5pt", "SEC_AFTER": "2pt",
        "HEADER_SKIP": "2pt", "ITEMIZE_TOPSEP": "0pt", "ITEMIZE_ITEMSEP": "0pt",
    },
    "normal": {
        "PARSKIP": "2pt", "SEC_BEFORE": "8pt", "SEC_AFTER": "3pt",
        "HEADER_SKIP": "4pt", "ITEMIZE_TOPSEP": "2pt", "ITEMIZE_ITEMSEP": "2pt",
    },
    "relaxed": {
        "PARSKIP": "5pt", "SEC_BEFORE": "12pt", "SEC_AFTER": "5pt",
        "HEADER_SKIP": "6pt", "ITEMIZE_TOPSEP": "4pt", "ITEMIZE_ITEMSEP": "4pt",
    },
}


def _escape_latex(text: str) -> str:
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for char, escaped in replacements:
        text = text.replace(char, escaped)
    return text


def _href(url: str, display: str) -> str:
    return f"\\href{{{url}}}{{{display}}}"


def _latex_bullet(text: str) -> str:
    return f"  \\item {_escape_latex(text)}\n"


def inject_into_template(data: dict) -> str:
    """Fill template.tex placeholders with the structured JSON data.

    By-value copy of the backend's inject_into_template — keep identical.
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    exp_blocks = []
    for job in data.get("experience", []):
        company = _escape_latex(job.get("company", ""))
        location = _escape_latex(job.get("location", ""))
        title = _escape_latex(job.get("title", ""))
        dates = _escape_latex(job.get("dates", ""))
        header = f"\\textbf{{{company}}} \\hfill {dates} \\\\\n\\textit{{{title}}} \\hfill {location}"
        bullets = "".join(_latex_bullet(b) for b in job.get("bullets", []))
        exp_blocks.append(
            f"{header}\n"
            "\\begin{itemize}[leftmargin=*, topsep={{ITEMIZE_TOPSEP}}, itemsep={{ITEMIZE_ITEMSEP}}, parsep=0pt]\n"
            + bullets
            + "\\end{itemize}"
        )
    experience_latex = "\n\n".join(exp_blocks) if exp_blocks else "No experience listed."

    edu_blocks = []
    for edu in data.get("education", []):
        school = _escape_latex(edu.get("school", ""))
        location = _escape_latex(edu.get("location", ""))
        degree = _escape_latex(edu.get("degree", ""))
        dates = _escape_latex(edu.get("dates", ""))
        edu_blocks.append(
            f"\\textbf{{{school}}} \\hfill {location} \\\\\n"
            f"\\textit{{{degree}}} \\hfill {dates}"
        )
    education_latex = "\n\n".join(edu_blocks) if edu_blocks else "No education listed."

    skills_data = data.get("skills", {})
    if isinstance(skills_data, dict):
        lines = []
        items = list(skills_data.items())
        for i, (category, value) in enumerate(items):
            escaped_cat = _escape_latex(category)
            escaped_val = _escape_latex(value)
            ending = " \\\\" if i < len(items) - 1 else ""
            lines.append(f"\\textbf{{{escaped_cat}:}} {escaped_val}{ending}")
        skills_latex = "\n".join(lines)
    else:
        skills_latex = ", ".join(_escape_latex(s) for s in skills_data) if skills_data else "No skills listed."

    proj_blocks = []
    for proj in data.get("projects", []):
        name = _escape_latex(proj.get("name", ""))
        dates = _escape_latex(proj.get("dates", ""))
        bullets = "".join(_latex_bullet(b) for b in proj.get("bullets", []))
        proj_blocks.append(
            f"\\textbf{{{name}}} \\hfill {dates}\n"
            "\\begin{itemize}[leftmargin=*, topsep={{ITEMIZE_TOPSEP}}, itemsep={{ITEMIZE_ITEMSEP}}, parsep=0pt]\n"
            + bullets
            + "\\end{itemize}"
        )
    projects_latex = "\n\n".join(proj_blocks) if proj_blocks else ""

    email = data.get("email", "")
    email_latex = _href(f"mailto:{email}", _escape_latex(email)) if email else ""

    website = data.get("website", "")
    website_display = website.replace("https://", "").replace("http://", "").rstrip("/")
    website_latex = _href(website, _escape_latex(website_display)) if website else ""

    github = data.get("github", "")
    github_latex = _href(github, "github") if github else ""

    linkedin = data.get("linkedin", "")
    linkedin_latex = _href(linkedin, "linkedin") if linkedin else ""

    template = template.replace("{{NAME}}", _escape_latex(data.get("name", "Name")))
    template = template.replace("{{PHONE}}", _escape_latex(data.get("phone", "")))
    template = template.replace("{{EMAIL}}", email_latex)
    template = template.replace("{{WEBSITE}}", website_latex)
    template = template.replace("{{GITHUB}}", github_latex)
    template = template.replace("{{LINKEDIN}}", linkedin_latex)
    template = template.replace("{{EDUCATION}}", education_latex)
    template = template.replace("{{SKILLS}}", skills_latex)
    template = template.replace("{{EXPERIENCE_BULLETS}}", experience_latex)
    template = template.replace("{{PROJECTS}}", projects_latex)

    return template


def compile_latex_to_pdf(latex_source: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "resume.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex_source)

        cmd = ["pdflatex", "-interaction=nonstopmode", "-output-directory", tmpdir, tex_path]
        for _ in range(2):
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            log_snippet = result.stdout[-2000:] if result.stdout else result.stderr[-2000:]
            raise RuntimeError(f"pdflatex failed (exit {result.returncode}):\n{log_snippet}")

        pdf_path = os.path.join(tmpdir, "resume.pdf")
        if not os.path.exists(pdf_path):
            raise RuntimeError("pdflatex ran but produced no PDF file")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

    if not pdf_bytes.startswith(b"%PDF"):
        raise RuntimeError("Output file does not appear to be a valid PDF")
    return pdf_bytes


def _compile_at(latex_source: str, size: int, preset: str = "tight") -> bytes:
    spacing = _SPACING_PRESETS.get(preset, _SPACING_PRESETS["tight"])
    s = latex_source.replace("{{FONT_SIZE}}", str(size))
    for key, val in spacing.items():
        s = s.replace(f"{{{{{key}}}}}", val)
    return compile_latex_to_pdf(s)


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)


def _page1_fill_ratio(pdf_bytes: bytes) -> float:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        chars = page.chars
        if not chars:
            return 0.0
        margin = 36.0
        usable = page.height - 2 * margin
        if usable <= 0:
            return 1.0
        content_bottom = max(c["bottom"] for c in chars)
        return max(0.0, (content_bottom - margin) / usable)


class _PdftotextUnavailable(RuntimeError):
    pass


def _pdftotext_layout(pdf_bytes: bytes) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "doc.pdf")
        txt_path = os.path.join(tmpdir, "doc.txt")
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        try:
            subprocess.run(
                ["pdftotext", "-layout", pdf_path, txt_path],
                capture_output=True, check=True, timeout=30,
            )
        except FileNotFoundError:
            raise _PdftotextUnavailable("pdftotext binary not found — install poppler-utils")
        except subprocess.CalledProcessError as e:
            raise _PdftotextUnavailable(f"pdftotext failed (exit {e.returncode})")
        with open(txt_path, "r", encoding="utf-8") as f:
            return f.read()


def max_full_line_len(pdf_bytes: bytes) -> int:
    text = _pdftotext_layout(pdf_bytes)
    lines = text.splitlines()
    widths = []
    in_bullet = False
    for line in lines:
        stripped = line.lstrip(" ")
        if stripped.startswith(_BULLET_GLYPH):
            in_bullet = True
            widths.append(len(line.rstrip()))
        elif in_bullet and line and line[0] == " ":
            widths.append(len(line.rstrip()))
        else:
            in_bullet = False
    if not widths:
        widths = [len(line.rstrip()) for line in lines if line.strip()]
    return max(widths) if widths else 0


def measure_bullets(pdf_bytes: bytes):
    text = _pdftotext_layout(pdf_bytes)
    lines = text.splitlines()
    pairs = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.lstrip(" ")
        if stripped.startswith(_BULLET_GLYPH):
            first_width = len(line.rstrip())
            last_width = 0
            j = i + 1
            while j < n:
                nxt = lines[j]
                if not nxt.strip():
                    j += 1
                    continue
                nxt_stripped = nxt.lstrip(" ")
                lead = len(nxt) - len(nxt_stripped)
                if nxt_stripped.startswith(_BULLET_GLYPH):
                    break
                if lead == 0:
                    break
                last_width = len(nxt.rstrip())
                j += 1
            pairs.append((first_width, last_width))
            i = j
        else:
            i += 1
    return pairs


def _flatten_bullet_locations(data: dict):
    locations = []
    for section in ("experience", "projects"):
        for j, entry in enumerate(data.get(section, [])):
            for k in range(len(entry.get("bullets", []))):
                locations.append((section, j, k))
    return locations


def _trim_to_single_line(text: str, cap: int) -> str:
    target = max(20, int(cap * 0.92))
    if len(text) <= target:
        return text

    best_clause = ""
    words = text.split()
    out = ""
    for w in words:
        candidate = (out + " " + w).strip()
        if len(candidate) > target:
            break
        out = candidate
        if out and out[-1] in (",", ";", "("):
            best_clause = out.rstrip(",;( ").rstrip()

    if not out:
        return text[:target]
    if best_clause and len(best_clause) >= int(target * 0.60):
        return best_clause
    return out


def compile_resume_json_to_pdf(
    resume_json: dict, font_anchor: int = 11, spacing: str = "tight"
) -> Tuple[bytes, Dict]:
    """inject_into_template → font lock → _trim_to_single_line backstop →
    spacing stretch. NO Claude calls. Returns (pdf_bytes, diagnostics).

    Keep in lockstep with internship-app/resume_tailor/tailor_resume.py's
    compile_resume_json_to_pdf (parity test asserts equivalent output).
    """
    data = copy.deepcopy(resume_json)
    latex = inject_into_template(data)

    font = font_anchor if font_anchor in FONT_SIZES else _ANCHOR_FONT
    pdf = _compile_at(latex, font, spacing)
    if _count_pdf_pages(pdf) > 1:
        for size in [s for s in FONT_SIZES if s < font]:
            candidate = _compile_at(latex, size, spacing)
            font = size
            pdf = candidate
            if _count_pdf_pages(candidate) <= 1:
                break
    elif _page1_fill_ratio(pdf) < UNDERFILL_RATIO:
        for size in sorted([s for s in FONT_SIZES if s > font], reverse=True):
            candidate = _compile_at(latex, size, spacing)
            if _count_pdf_pages(candidate) <= 1:
                font = size
                pdf = candidate
                break

    preset = spacing if spacing in _SPACING_PRESETS else "tight"
    try:
        for _ in range(2):
            cap = max_full_line_len(pdf)
            if cap <= 0:
                break
            pairs = measure_bullets(pdf)
            locations = _flatten_bullet_locations(data)
            if len(locations) != len(pairs):
                break
            bad = [i for i, (_l1, l2) in enumerate(pairs) if l2 and (l2 / cap) < BACKSTOP_FLOOR]
            if not bad:
                break
            for i in bad:
                section, j, k = locations[i]
                data[section][j]["bullets"][k] = _trim_to_single_line(
                    data[section][j]["bullets"][k], cap
                )
            latex = inject_into_template(data)
            pdf = _compile_at(latex, font, preset)
    except _PdftotextUnavailable as exc:
        logger.warning("compile core: widow backstop disabled — %s", exc)

    if preset == "tight" and _count_pdf_pages(pdf) == 1 and _page1_fill_ratio(pdf) < UNDERFILL_RATIO:
        latex_for_stretch = inject_into_template(data)
        for try_preset in ("normal", "relaxed"):
            candidate = _compile_at(latex_for_stretch, font, try_preset)
            if _count_pdf_pages(candidate) > 1:
                break
            pdf = candidate
            preset = try_preset
            if _page1_fill_ratio(pdf) >= UNDERFILL_RATIO:
                break

    widows = []
    try:
        cap = max_full_line_len(pdf)
        pairs = measure_bullets(pdf)
        locations = _flatten_bullet_locations(data)
        if cap > 0 and len(locations) == len(pairs):
            for i, (_l1, l2) in enumerate(pairs):
                if l2 and (l2 / cap) < WIDOW_THRESHOLD:
                    section, j, k = locations[i]
                    widows.append({
                        "section": section, "entry": j, "bullet": k,
                        "last_line_chars": l2,
                    })
    except _PdftotextUnavailable:
        pass

    diagnostics = {
        "pages": _count_pdf_pages(pdf),
        "font_size": font,
        "spacing": preset,
        "fill_ratio": round(_page1_fill_ratio(pdf), 2),
        "widows": widows,
    }
    return pdf, diagnostics


def safe_pdf_filename(company: str, title: str) -> str:
    """`<company>_<role>.pdf`, filesystem-safe."""
    base = f"{company}_{title}".strip() or "resume"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")[:120]
    return f"{base}.pdf"


def write_pdf(pdf_bytes: bytes, company: str, title: str) -> str:
    out = config.resumes_dir() / safe_pdf_filename(company, title)
    out.write_bytes(pdf_bytes)
    return str(out)

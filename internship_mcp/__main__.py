"""FastMCP app — tool registrations for the Internship Apply Agent.

Every tool is dumb and deterministic. YOU (the host agent) supply all
reasoning: skill extraction, ranking, bullet rewriting, field mapping, and
answering questions. Tool descriptions encode the intended call-flow.

Transport: stdio only (agent-agnostic — works in Claude Code, Cursor, Codex,
Windsurf, Cline).
"""
import base64
import logging
import sys
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from . import client, compile_local, config, packet, profile_store, resume_local, tracker

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("internship-mcp")

mcp = FastMCP(
    "internship",
    instructions=(
        "Internship Apply Agent. YOU (the host agent) supply all reasoning; these "
        "tools are deterministic.\n\n"
        "FIRST INTERACTION RULE: before doing ANY job search or application work — "
        "and ideally as soon as the user engages you about internships — call "
        "profile_setup. Run the one-time setup in this order:\n"
        "1) COMPILE CHOICE (from compile_setup in the response): if pdflatex is not "
        "installed, ask the user to choose — install pdflatex locally for UNLIMITED "
        "resume compiles (recommended; give them the install command for their OS "
        "and re-check by calling profile_setup again), or use the remote service "
        "(limited to 15 compiles/week). Record their choice via profile_set as "
        "_meta.compile_choice='local'|'remote'.\n"
        "2) PROFILE INTERVIEW: collect missing_required, then offer the optional "
        "standard application questions (work authorization, visa, EEO demographics, "
        "logistics), making clear each optional one can be skipped ('prefer not to "
        "answer' keeps 'Decline to self-identify'). Save with profile_set including "
        "_meta.setup_interview_done=true. Never guess these values; never re-ask "
        "once done; the encrypted local profile is the source of truth until the "
        "user asks to change it.\n\n"
        "Core flow: profile_setup -> resume_parse (you extract skills) -> jobs_list "
        "-> jobs_prefilter -> you rank -> job_get -> you rewrite resume JSON (see "
        "resume://tailoring-guide) -> resume_compile (fix diagnostics.widows, "
        "recompile) -> packet_build -> prefill via the Playwright MCP -> STOP for "
        "the user to review and submit -> application_record. Never auto-answer "
        "subjective questions; ask the user and answer_save their words."
    ),
)


# ---------------------------------------------------------------------------
# Profile + answer bank (local, encrypted)
# ---------------------------------------------------------------------------

@mcp.tool()
def profile_setup() -> Dict:
    """START HERE on first run. Returns the applicant profile, a
    missing_required list, and (until the one-time setup interview is done) an
    optional_questions list covering the standard application questions —
    work authorization, visa status, and the EEO/demographic set (gender,
    race/ethnicity, Hispanic/Latino, veteran status, disability).

    Run ONE setup, in this order:
    1) COMPILE CHOICE — from compile_setup: if pdflatex_installed is false and
       _meta.compile_choice is unset, ask the user to pick: install pdflatex
       locally (UNLIMITED compiles — give them install_commands for their OS,
       then call profile_setup again to confirm pdflatex_installed flipped) or
       use the remote service (remote_quota limited). Record via profile_set
       as {"_meta": {"compile_choice": "local"|"remote"}}.
    2) INTERVIEW — ask the missing_required fields, then offer the
       optional_questions in a single batch, telling the user each optional one
       can be skipped ("prefer not to answer" keeps the default of 'Decline to
       self-identify' on applications). NEVER guess or infer these values. Save
       everything with profile_set, including {"_meta": {"setup_interview_done":
       true}} so the user is never re-asked — the encrypted profile is then the
       single source of truth for all future applications until the user asks
       to change it (profile_set works any time). Next: resume_parse."""
    profile = profile_store.load_profile()
    return {
        "profile": profile,
        "missing_required": profile_store.missing_required(profile),
        "optional_questions": profile_store.optional_interview_questions(profile),
        "compile_setup": {
            **config.compile_setup_info(),
            "compile_choice": profile.get("_meta", {}).get("compile_choice"),
        },
        "compile_mode": config.compile_mode(),
    }


@mcp.tool()
def profile_get() -> Dict:
    """Return the full decrypted applicant profile (stays in-process — never
    send EEO/PII fields to any backend; they go only into application forms)."""
    return profile_store.load_profile()


@mcp.tool()
def profile_set(fields: Dict) -> Dict:
    """Deep-merge updates into the encrypted local profile. Pass only the
    fields you collected, e.g. {"personal": {"full_name": "..."},
    "work_authorization": {"us_citizen": true}}. Returns the updated profile
    and the remaining missing_required list."""
    profile = profile_store.load_profile()
    profile = profile_store.set_fields(profile, fields)
    profile_store.save_profile(profile)
    return {
        "profile": profile,
        "missing_required": profile_store.missing_required(profile),
    }


@mcp.tool()
def answer_save(question: str, answer: str, tags: Optional[List[str]] = None) -> Dict:
    """Persist an application answer THE USER WROTE (in their own voice) so it
    can be reused across applications. Never save text you fabricated for a
    subjective question — always elicit it from the user first."""
    profile = profile_store.load_profile()
    profile = profile_store.answer_save(profile, question, answer, tags)
    profile_store.save_profile(profile)
    return {"ok": True}


@mcp.tool()
def answer_match(question: str) -> Dict:
    """Fuzzy-match a form question against the local answer bank. Returns
    {answer, score} on a hit (score >= 0.72) or {answer: null} — in which case
    ASK THE USER and then answer_save their reply. Never invent an answer."""
    profile = profile_store.load_profile()
    match = profile_store.answer_match(profile, question)
    if match is None:
        return {"answer": None, "score": 0.0}
    return {"answer": match[0], "score": round(match[1], 3)}


# ---------------------------------------------------------------------------
# Resume (local parse — YOU extract the skills)
# ---------------------------------------------------------------------------

@mcp.tool()
def resume_parse(path: str) -> Dict:
    """Extract raw text from a local resume PDF (OCR for images only inside
    Docker). No model is called — YOU read the text and extract the skills /
    experience yourself, then call jobs_prefilter with a small resume_profile:
    {skills, experience_level (student|entry_level|experienced),
    years_of_experience, location, willing_to_relocate, remote_ok}.
    The raw resume text NEVER goes to the backend."""
    return resume_local.extract_text(path)


# ---------------------------------------------------------------------------
# Jobs (backend, deterministic)
# ---------------------------------------------------------------------------

@mcp.tool()
def jobs_list(
    since_hours: Optional[int] = None,
    max_days_old: int = 30,
    location: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> Dict:
    """List active internship postings from the backend (deterministic DB
    query, no AI). Typical flow starts with since_hours=72 for fresh postings.
    Next: jobs_prefilter to score them against the candidate."""
    return client.jobs_list(since_hours, max_days_old, location, q, limit, offset).model_dump()


@mcp.tool()
def job_get(job_hash: str) -> Dict:
    """Fetch one job with its FULL untruncated description. Use this for your
    'think deeper' re-ranking and before rewriting the resume for the job."""
    return client.job_get(job_hash).model_dump()


@mcp.tool()
def jobs_prefilter(
    resume_profile: Dict,
    filters: Optional[Dict] = None,
    target_count: int = 40,
) -> Dict:
    """Deterministic keyword + metadata scoring of jobs against a small
    PII-free resume_profile (skills, experience_level, years_of_experience,
    location, willing_to_relocate, remote_ok). Returns scored candidates.
    Quick mode: trust combined_score. Think deeper: job_get the full JDs for
    your shortlist and re-rank them YOURSELF. The scoring here is mechanical —
    your judgment is the real ranker."""
    return client.jobs_prefilter(resume_profile, filters, target_count).model_dump()


# ---------------------------------------------------------------------------
# Compile (local pdflatex by default; remote fallback per COMPILE env)
# ---------------------------------------------------------------------------

@mcp.tool()
def resume_compile(resume_json: Dict, options: Optional[Dict] = None) -> Dict:
    """Compile tailored resume JSON (YOU write it — see the
    resume://tailoring-guide resource for the exact schema and density rules)
    into a single-page PDF via pdflatex. Returns {pdf_path, diagnostics}.
    Inspect diagnostics.widows: each entry is a bullet whose last line is
    nearly empty — rewrite that bullet (extend with REAL facts to fill two
    lines, or tighten to one) and recompile. Runs locally when pdflatex is
    available (COMPILE=local/auto), else falls back to the rate-limited
    backend endpoint. Pass options.company and options.role so the PDF is
    saved as <company>_<role>.pdf."""
    options = options or {}
    font_anchor = int(options.get("font_anchor", 11))
    spacing = options.get("spacing", "tight")
    mode = config.compile_mode()

    if mode == "local":
        pdf_bytes, diagnostics = compile_local.compile_resume_json_to_pdf(
            resume_json, font_anchor, spacing
        )
    else:
        result = client.resume_compile_remote(
            resume_json, {"font_anchor": font_anchor, "spacing": spacing}
        )
        pdf_bytes = base64.b64decode(result.pdf_base64)
        diagnostics = result.diagnostics

    pdf_path = compile_local.write_pdf(
        pdf_bytes,
        options.get("company") or resume_json.get("name", "resume"),
        options.get("role", "tailored"),
    )
    return {"pdf_path": pdf_path, "diagnostics": diagnostics, "compiled": mode}


# ---------------------------------------------------------------------------
# Packet + tracker (local)
# ---------------------------------------------------------------------------

@mcp.tool()
def packet_build(
    job_hash: str,
    field_labels: List[str],
    resume_pdf_path: str,
    answers: Optional[Dict] = None,
    force: bool = False,
) -> Dict:
    """Assemble the application packet for a job: fills each form field label
    (observed via the Playwright MCP) from the profile / answer bank, with
    source + confidence per field. Anything in needs_user_input is subjective
    or unknown — ASK THE USER for those in their own words, answer_save the
    replies, then rebuild. EEO fields with no stored value become 'Decline to
    self-identify' — NEVER invent them. Refuses already-submitted jobs unless
    force=true. Next: drive the Playwright MCP to prefill the form, then STOP
    and hand to the user to review + submit; record with
    application_record(status='prefilled')."""
    job = client.job_get(job_hash).model_dump()
    return packet.build_packet(job, field_labels, resume_pdf_path, answers, force)


@mcp.tool()
def application_record(
    job_hash: str,
    status: str,
    company: str = "",
    title: str = "",
    apply_link: str = "",
    ats_type: str = "",
    resume_pdf_path: str = "",
    answers: Optional[Dict] = None,
    notes: str = "",
) -> Dict:
    """Upsert the local application log. Statuses: matched | tailored |
    packet_ready | prefilled | submitted | failed | skipped. Log EVERY
    submission with the exact answers used."""
    return tracker.record(
        job_hash, status, company, title, apply_link, ats_type,
        resume_pdf_path, answers, notes,
    )


@mcp.tool()
def applications_list(status: Optional[str] = None) -> List[Dict]:
    """List tracked applications (optionally by status). Check this before
    building a packet to avoid duplicate applications."""
    return tracker.list_applications(status)


@mcp.tool()
def application_status(job_hash: str) -> Optional[Dict]:
    """Status of one tracked application, or null if never touched."""
    return tracker.get_status(job_hash)


# ---------------------------------------------------------------------------
# v2 — auto-submit planning (gated; the agent still drives Playwright)
# ---------------------------------------------------------------------------

@mcp.tool()
def autosubmit_plan(job_hash: str, packet_data: Dict, dry_run: bool = True) -> Dict:
    """V2, GATED. Produce an ordered fill plan from a packet for automated
    submission. HARD GATES (non-negotiable): dry_run defaults true; any
    confidence='low' field or non-empty needs_user_input BLOCKS submission;
    already-submitted jobs are refused; max 10 auto-submits per session;
    CONFIRM WITH THE USER before the first real submit; captchas/account walls
    → stop and hand off. You still drive the Playwright MCP yourself."""
    if tracker.is_submitted(job_hash):
        return {"ok": False, "blocked": "already_submitted"}

    blockers = []
    if packet_data.get("needs_user_input"):
        blockers.append("needs_user_input is not empty — collect those answers first")
    low = [f["label"] for f in packet_data.get("fields", []) if f.get("confidence") == "low"]
    if low:
        blockers.append(f"low-confidence fields block auto-submit: {low}")

    steps = [
        {"action": "open", "target": packet_data.get("apply_link")},
        *[
            {"action": "fill", "label": f["label"], "value": f["value"]}
            for f in packet_data.get("fields", [])
        ],
        {"action": "attach", "file": packet_data.get("resume_pdf_path")},
        {"action": "review", "note": "Verify every field against the packet"},
        {"action": "submit" if not dry_run and not blockers else "stop_for_user"},
    ]
    return {
        "ok": not blockers,
        "dry_run": dry_run,
        "blockers": blockers,
        "max_auto_submits": config.max_auto_submits(),
        "confirm_prompt": (
            "Confirm with the user before submitting: company, title, and every "
            "answer in the packet. Submission is irreversible."
        ),
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Prompts (user-invocable entry points — surfaced as commands by MCP hosts)
# ---------------------------------------------------------------------------

@mcp.prompt()
def get_started() -> str:
    """First-run onboarding: set up the applicant profile via the one-time interview."""
    return (
        "I want to set up my internship apply agent. Call profile_setup, then "
        "interview me for everything it reports missing — the required fields and "
        "the optional standard application questions (work authorization, visa, "
        "EEO demographics, logistics). Tell me clearly which questions are optional "
        "and let me skip any of them. Save my answers with profile_set, mark the "
        "interview done, and confirm what my profile now covers."
    )


@mcp.prompt()
def apply_to_internships(resume_path: str) -> str:
    """End-to-end assisted apply run: parse resume, find + rank jobs, tailor, prefill."""
    return (
        f"Run my internship application flow. 1) profile_setup — if anything is "
        f"missing, interview me first. 2) Parse my resume at {resume_path} and "
        f"extract my skills yourself. 3) Find postings from the last 3 days, "
        f"prefilter them, and rank your top 5 with reasoning from the full job "
        f"descriptions. 4) For my pick: tailor my resume truthfully, compile it, "
        f"and fix any widows the compiler reports. 5) Build the application packet, "
        f"ask me for anything subjective, prefill the form via Playwright, then "
        f"STOP so I can review and submit it myself."
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("resume://tailoring-guide")
def tailoring_guide() -> str:
    """The resume JSON contract + density rules the agent must follow when
    rewriting bullets for a job."""
    return """# Resume Tailoring Guide (for the agent)

YOU write the tailored resume JSON — there is no tool that does it. Rules:

## JSON contract (exact — resume_compile expects this shape)
{ "name":"","email":"","phone":"","website":"","github":"","linkedin":"",
  "experience":[{"company":"","location":"","title":"","dates":"","bullets":[""]}],
  "education":[{"school":"","location":"","degree":"","dates":""}],
  "skills":{"Category":"comma, separated, values"},
  "projects":[{"name":"Name (Tech1, Tech2)","dates":"","bullets":[""]}] }

## Truthfulness (non-negotiable)
- Every bullet must be grounded in facts explicitly present in the user's
  resume. Rephrasing with JD keywords is allowed; inventing work is not.
- Preserve all original metrics, counts, and parenthetical detail.
- Never rename tools (e.g. "Anthropic API" must not become something else).

## Density rules
- Zone B (>=215 chars, two full lines) is the DEFAULT target per bullet.
- Zone A (<=115 chars, one tight line) only when no more truthful facts exist.
- The 116-214 char dead zone is FORBIDDEN — it wraps to a near-empty orphan line.
- 3-4 bullets per experience role, 3 per project.
- No filler ("collaborated with cross-functional teams" etc.).

## Compile loop
1. resume_compile(resume_json) -> {pdf_path, diagnostics}
2. If diagnostics.widows is non-empty: each widow names a bullet whose last
   line is mostly empty. Rewrite THAT bullet — extend with real resume facts
   (preferred) or tighten to one line — and recompile.
3. Target diagnostics: pages == 1, fill_ratio >= 0.85, widows == [].
"""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

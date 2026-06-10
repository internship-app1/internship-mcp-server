"""Application-packet assembly — the authentic-answer guardrail lives here.

Fill order per field: exact profile field → answer_match (>= threshold) →
flag for the USER. Subjective questions are NEVER auto-answered; EEO values
with no stored answer become "Decline to self-identify", never invented.
"""
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

from . import profile_store, tracker

# Patterns that mark a question as subjective/authentic — these are always
# elicited from the user unless the answer bank has a high-confidence hit.
_SUBJECTIVE_PATTERNS = [
    r"\bwhy\b", r"proudest", r"passion", r"motivat", r"excite", r"tell us about",
    r"describe a time", r"biggest (challenge|achievement|failure)", r"what makes you",
    r"cover letter", r"anything else", r"fun fact", r"about yourself", r"interest in",
]

_EEO_LABELS = {
    "gender": ("demographics_eeo", "gender"),
    "pronouns": ("demographics_eeo", "pronouns"),
    "race": ("demographics_eeo", "race_ethnicity"),
    "ethnicity": ("demographics_eeo", "race_ethnicity"),
    "hispanic": ("demographics_eeo", "hispanic_or_latino"),
    "latino": ("demographics_eeo", "hispanic_or_latino"),
    "veteran": ("demographics_eeo", "veteran_status"),
    "disability": ("demographics_eeo", "disability_status"),
}

_DECLINE = "Decline to self-identify"


def detect_ats_type(apply_link: str) -> str:
    host = (urlparse(apply_link or "").netloc or "").lower()
    if "greenhouse" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq" in host:
        return "ashby"
    if "workday" in host or "myworkdayjobs" in host:
        return "workday"
    return "other"


def is_subjective(label: str) -> bool:
    lowered = label.lower()
    return any(re.search(p, lowered) for p in _SUBJECTIVE_PATTERNS)


def _eeo_value(profile: Dict, label: str) -> Optional[str]:
    lowered = label.lower()
    for key, (section, field) in _EEO_LABELS.items():
        if key in lowered:
            value = profile.get(section, {}).get(field)
            if isinstance(value, list):
                value = value[0] if value else "decline"
            if value in (None, "", "decline"):
                return _DECLINE
            return str(value)
    return None


def _standard_value(profile: Dict, label: str) -> Optional[tuple]:
    """Map common ATS labels to profile fields. Returns (value, source) or None."""
    p = profile.get("personal", {})
    wa = profile.get("work_authorization", {})
    lg = profile.get("logistics", {})
    lowered = label.lower()

    def yn(v):
        return None if v is None else ("Yes" if v else "No")

    full_name = p.get("full_name", "")
    candidates = [
        (("first name",), full_name.split(" ")[0] if full_name else None),
        (("last name", "family name", "surname"),
         full_name.split(" ")[-1] if full_name and " " in full_name else None),
        (("full name", "your name", "legal name"), full_name or None),
        (("email",), p.get("email") or None),
        (("phone",), p.get("phone") or None),
        (("linkedin",), p.get("links", {}).get("linkedin") or None),
        (("github",), p.get("links", {}).get("github") or None),
        (("portfolio", "website"),
         p.get("links", {}).get("portfolio") or p.get("links", {}).get("website") or None),
        (("city",), p.get("address", {}).get("city") or None),
        (("state",), p.get("address", {}).get("state") or None),
        (("zip", "postal"), p.get("address", {}).get("postal") or None),
        (("country",), p.get("address", {}).get("country") or None),
        (("address", "street"), p.get("address", {}).get("line1") or None),
        (("citizen",), yn(wa.get("us_citizen"))),
        (("authorized to work", "work authorization", "legally authorized"),
         yn(wa.get("work_authorized_in_us"))),
        (("sponsorship",), yn(wa.get("requires_sponsorship_now_or_future"))),
        (("visa status",), wa.get("visa_status") or None),
        (("security clearance",), yn(wa.get("security_clearance"))),
        (("relocat",), yn(lg.get("willing_to_relocate"))),
        (("start date", "available", "availability"), lg.get("earliest_start_date") or None),
        (("salary", "compensation"), lg.get("salary_expectation") or None),
        (("how did you hear",), lg.get("how_did_you_hear") or None),
    ]
    for needles, value in candidates:
        if value and any(n in lowered for n in needles):
            return value, "profile"
    return None


def build_packet(
    job: Dict,
    field_labels: List[str],
    resume_pdf_path: str,
    answers: Optional[Dict[str, str]] = None,
    force: bool = False,
) -> Dict:
    """Assemble the application packet (PRD §8.4).

    `field_labels` are the form-field labels the host agent observed on the
    application page (via the Playwright MCP). `answers` are explicit values
    the agent already collected from the user for this application.
    """
    job_hash = job.get("job_hash", "")
    if not force and tracker.is_submitted(job_hash):
        raise RuntimeError(
            f"Job {job_hash[:12]}… is already SUBMITTED. Pass force=true to rebuild anyway."
        )

    profile = profile_store.load_profile()
    answers = answers or {}
    fields: List[Dict] = []
    needs_user_input: List[Dict] = []

    for label in field_labels:
        # 0. Explicit answer the agent already collected from the user
        if label in answers:
            fields.append({
                "label": label, "value": answers[label],
                "source": "answer_bank", "confidence": "high",
            })
            continue

        # 1. EEO: stored value or "Decline to self-identify" — never invented
        eeo = _eeo_value(profile, label)
        if eeo is not None:
            fields.append({
                "label": label, "value": eeo,
                "source": "profile_eeo", "confidence": "high",
            })
            continue

        # 2. Exact profile field
        std = _standard_value(profile, label)
        if std is not None:
            value, source = std
            fields.append({
                "label": label, "value": value,
                "source": source, "confidence": "high",
            })
            continue

        # 3. Answer bank fuzzy match
        match = profile_store.answer_match(profile, label)
        if match is not None and not (is_subjective(label) and match[1] < 0.90):
            answer, score = match
            fields.append({
                "label": label, "value": answer,
                "source": "answer_bank",
                "confidence": "high" if score >= 0.90 else "medium",
            })
            continue

        # 4. Unknown → the AGENT asks the USER (authentic-answer guardrail)
        needs_user_input.append({
            "label": label,
            "reason": "subjective/authentic" if is_subjective(label) else "no stored value",
            "prompt_user": True,
        })

    packet = {
        "job_hash": job_hash,
        "company": job.get("company", ""),
        "title": job.get("title", ""),
        "apply_link": job.get("apply_link", ""),
        "ats_type": detect_ats_type(job.get("apply_link", "")),
        "resume_pdf_path": resume_pdf_path,
        "fields": fields,
        "needs_user_input": needs_user_input,
        "attachments": [resume_pdf_path],
    }
    return packet

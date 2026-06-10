"""Local SQLite application log (PRD §8.2) with dedup.

Dedup rule: a job with status 'submitted' is refused by packet_build /
autosubmit_plan unless force=true. application_record is an upsert on job_hash.
"""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import config

VALID_STATUSES = (
    "matched", "tailored", "packet_ready", "prefilled", "submitted", "failed", "skipped",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    job_hash        TEXT PRIMARY KEY,
    company         TEXT,
    title           TEXT,
    apply_link      TEXT,
    ats_type        TEXT,
    status          TEXT NOT NULL,
    resume_pdf_path TEXT,
    answers_json    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    submitted_at    TEXT,
    notes           TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.tracker_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(
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
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}; must be one of {VALID_STATUSES}")
    now = _now()
    submitted_at = now if status == "submitted" else None
    with _connect() as conn:
        existing = conn.execute(
            "SELECT job_hash, created_at, submitted_at FROM applications WHERE job_hash=?",
            (job_hash,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE applications SET status=?, updated_at=?,
                       company=COALESCE(NULLIF(?, ''), company),
                       title=COALESCE(NULLIF(?, ''), title),
                       apply_link=COALESCE(NULLIF(?, ''), apply_link),
                       ats_type=COALESCE(NULLIF(?, ''), ats_type),
                       resume_pdf_path=COALESCE(NULLIF(?, ''), resume_pdf_path),
                       answers_json=COALESCE(?, answers_json),
                       submitted_at=COALESCE(?, submitted_at),
                       notes=COALESCE(NULLIF(?, ''), notes)
                   WHERE job_hash=?""",
                (status, now, company, title, apply_link, ats_type, resume_pdf_path,
                 json.dumps(answers) if answers is not None else None,
                 submitted_at, notes, job_hash),
            )
        else:
            conn.execute(
                """INSERT INTO applications
                   (job_hash, company, title, apply_link, ats_type, status,
                    resume_pdf_path, answers_json, created_at, updated_at,
                    submitted_at, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_hash, company, title, apply_link, ats_type, status,
                 resume_pdf_path, json.dumps(answers) if answers is not None else None,
                 now, now, submitted_at, notes),
            )
    return {"ok": True, "job_hash": job_hash, "status": status}


def get_status(job_hash: str) -> Optional[Dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE job_hash=?", (job_hash,)
        ).fetchone()
    return dict(row) if row else None


def list_applications(status: Optional[str] = None) -> List[Dict]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM applications WHERE status=? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM applications ORDER BY updated_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def is_submitted(job_hash: str) -> bool:
    row = get_status(job_hash)
    return bool(row and row["status"] == "submitted")

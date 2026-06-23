"""Pydantic IO models — mirror the /api/v1 OpenAPI contract.

Response models here MUST stay in lockstep with the backend's mcp_api.py
schemas; the contract test (tests/test_contract.py) validates them against
the published OpenAPI spec.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class JobSummary(BaseModel):
    job_hash: str
    company: str
    title: str
    location: str
    apply_link: str
    source: Optional[str] = None
    required_skills: List[str] = []
    days_since_posted: Optional[int] = None
    date_posted: Optional[str] = None
    description_preview: str = ""


class JobsResponse(BaseModel):
    jobs: List[JobSummary]
    total: int
    limit: int
    offset: int


class JobDetail(BaseModel):
    job_hash: str
    company: str
    title: str
    location: str
    apply_link: str
    source: Optional[str] = None
    required_skills: List[str] = []
    description: Optional[str] = None
    job_requirements: Optional[str] = None


class ResumeProfile(BaseModel):
    """Small PII-free profile — the ONLY resume-derived data sent to the backend."""
    skills: List[str]
    experience_level: str = Field(pattern="^(student|entry_level|experienced)$")
    years_of_experience: int = 0
    location: Optional[str] = None
    willing_to_relocate: bool = False
    remote_ok: bool = False


class PrefilterCandidate(BaseModel):
    job_hash: str
    company: str
    title: str
    location: str
    apply_link: str
    keyword_score: int
    metadata_score: int
    combined_score: int
    embedding_score: Optional[int] = None
    skill_matches: List[str]
    skill_gaps: List[str]
    hard_filter_passed: bool
    description_preview: str


class PrefilterResponse(BaseModel):
    candidates: List[PrefilterCandidate]
    evaluated: int
    returned: int


class CompileResponse(BaseModel):
    pdf_base64: str
    diagnostics: Dict


class PacketField(BaseModel):
    label: str
    value: str
    source: str           # profile | profile_eeo | answer_bank
    confidence: str       # high | medium | low


class NeedsUserInput(BaseModel):
    label: str
    reason: str
    prompt_user: bool = True


class Packet(BaseModel):
    job_hash: str
    company: str
    title: str
    apply_link: str
    ats_type: str
    resume_pdf_path: str
    fields: List[PacketField]
    needs_user_input: List[NeedsUserInput]
    attachments: List[str]

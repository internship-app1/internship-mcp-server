"""Shared fixtures. Every test gets an isolated INTERNSHIP_HOME and a fixed
profile key so no test ever touches the user's real keyring or profile."""
import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERNSHIP_HOME", str(tmp_path / "agent-home"))
    monkeypatch.setenv("INTERNSHIP_PROFILE_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("INTERNSHIP_API_KEY", "im_live_" + "t" * 32)
    # Keep tests off the OS keyring entirely
    import internship_mcp.profile_store as ps

    def _env_only_key():
        return os.environ["INTERNSHIP_PROFILE_KEY"].encode()

    monkeypatch.setattr(ps, "_resolve_key", _env_only_key)
    yield


@pytest.fixture()
def sample_resume_json() -> dict:
    return {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-123-4567",
        "website": "https://janedoe.dev",
        "github": "https://github.com/janedoe",
        "linkedin": "https://linkedin.com/in/janedoe",
        "experience": [
            {
                "company": "Acme Corp",
                "location": "San Francisco, CA",
                "title": "Software Engineering Intern",
                "dates": "Jun 2025 – Aug 2025",
                "bullets": [
                    "Built React and Python internal tools for non-technical ops "
                    "stakeholders: Intercom ticketing (5+ min saved per request, 50+ "
                    "customers), ERP sales order interface, and AWS S3 attachment "
                    "store for 250+ files",
                ],
            }
        ],
        "education": [
            {"school": "SJSU", "location": "San Jose, CA",
             "degree": "BS Computer Science", "dates": "2023–2027"}
        ],
        "skills": {"Languages": "Python, TypeScript", "Frameworks": "React, FastAPI"},
        "projects": [
            {
                "name": "Matcher (Python, React)",
                "dates": "2025",
                "bullets": [
                    "Shipped production multi-channel B2B AI order agent (webhooks, "
                    "WhatsApp, email, phone) using Claude Sonnet with RAG vector "
                    "stores, owning full-stack features from conception through "
                    "deployment across 7 enterprise clients processing 1,000+ orders",
                ],
            }
        ],
    }

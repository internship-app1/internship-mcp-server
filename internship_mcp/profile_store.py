"""Encrypted local applicant profile + answer bank (Fernet).

PII NEVER leaves this machine. Never log decrypted fields or the key.

Key resolution order:
  1. OS keyring (service "internship-agent")
  2. INTERNSHIP_PROFILE_KEY env var
  3. First run: generate a key, cache it in the keyring (or instruct the user
     to set the env var if no keyring backend exists).
"""
import difflib
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

from . import config

SCHEMA_VERSION = 1
_KEYRING_SERVICE = "internship-agent"
_KEYRING_USER = "profile-key"

ANSWER_MATCH_THRESHOLD = 0.72

# Required for most applications — drives the first-run interview.
REQUIRED_FIELDS = [
    ("personal.full_name", "Full name"),
    ("personal.email", "Email"),
    ("personal.phone", "Phone"),
    ("personal.address.city", "City"),
    ("personal.address.state", "State"),
    ("personal.links.linkedin|personal.links.github", "LinkedIn or GitHub URL"),
    ("work_authorization.us_citizen", "US citizen?"),
    ("work_authorization.requires_sponsorship_now_or_future", "Requires sponsorship now or in the future?"),
    ("logistics.willing_to_relocate", "Willing to relocate?"),
    ("logistics.earliest_start_date", "Earliest start date"),
]


def default_profile() -> Dict:
    """PRD §8.1 schema. EEO fields default 'decline' and are NEVER required."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "personal": {
            "full_name": "", "email": "", "phone": "",
            "address": {"line1": "", "city": "", "state": "", "postal": "", "country": "US"},
            "links": {"linkedin": "", "github": "", "portfolio": "", "website": ""},
        },
        "work_authorization": {
            "us_citizen": None, "work_authorized_in_us": None,
            "requires_sponsorship_now_or_future": None,
            "visa_status": "", "security_clearance": None,
        },
        "demographics_eeo": {
            "gender": "decline", "pronouns": "", "race_ethnicity": ["decline"],
            "hispanic_or_latino": "decline", "veteran_status": "decline",
            "disability_status": "decline",
        },
        "logistics": {
            "willing_to_relocate": None, "desired_locations": [], "work_mode": [],
            "earliest_start_date": "", "salary_expectation": "", "how_did_you_hear": "",
        },
        "education": [],
        "answer_bank": [],
        "_meta": {"created_at": now, "updated_at": now, "schema_version": SCHEMA_VERSION},
    }


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------

def _resolve_key() -> bytes:
    # 1. OS keyring
    try:
        import keyring
        stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
        if stored:
            return stored.encode()
    except Exception:
        keyring = None  # backend unavailable — fall through

    # 2. Env var
    env_key = os.getenv("INTERNSHIP_PROFILE_KEY", "").strip()
    if env_key:
        return env_key.encode()

    # 3. First run: generate and persist
    new_key = Fernet.generate_key()
    try:
        import keyring as _kr
        _kr.set_password(_KEYRING_SERVICE, _KEYRING_USER, new_key.decode())
        return new_key
    except Exception:
        raise RuntimeError(
            "No OS keyring available and INTERNSHIP_PROFILE_KEY is not set. "
            f"Set INTERNSHIP_PROFILE_KEY={new_key.decode()} in your MCP client "
            "config env to persist your encrypted profile (keep it secret)."
        )


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_profile() -> Dict:
    path = config.profile_path()
    if not path.exists():
        return default_profile()
    fernet = Fernet(_resolve_key())
    try:
        plaintext = fernet.decrypt(path.read_bytes())
    except InvalidToken:
        raise RuntimeError(
            "Could not decrypt profile.enc — the encryption key has changed. "
            "Restore the original INTERNSHIP_PROFILE_KEY/keyring entry, or delete "
            f"{path} to start over (you will re-enter your profile)."
        )
    profile = json.loads(plaintext)
    return _migrate(profile)


def save_profile(profile: Dict) -> None:
    profile["_meta"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    profile["_meta"]["schema_version"] = SCHEMA_VERSION
    fernet = Fernet(_resolve_key())
    ciphertext = fernet.encrypt(json.dumps(profile).encode("utf-8"))
    path = config.profile_path()
    # Atomic write: temp file in same dir, chmod 600, rename over.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".profile-", suffix=".tmp")
    try:
        os.write(fd, ciphertext)
        os.close(fd)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 600
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _migrate(profile: Dict) -> Dict:
    """Forward-fill any keys added since the profile was written."""
    base = default_profile()
    for section, value in base.items():
        if section not in profile:
            profile[section] = value
        elif isinstance(value, dict):
            for k, v in value.items():
                profile[section].setdefault(k, v)
    return profile


# ---------------------------------------------------------------------------
# Field access / interview support
# ---------------------------------------------------------------------------

def _get_path(profile: Dict, dotted: str):
    cur = profile
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_filled(value) -> bool:
    return value is not None and value != "" and value != []


def missing_required(profile: Dict) -> List[str]:
    """Human-readable list of required fields the interview still needs."""
    missing = []
    for path, label in REQUIRED_FIELDS:
        if "|" in path:
            if not any(_is_filled(_get_path(profile, p)) for p in path.split("|")):
                missing.append(label)
        elif not _is_filled(_get_path(profile, path)):
            missing.append(label)
    return missing


def set_fields(profile: Dict, fields: Dict) -> Dict:
    """Deep-merge a partial update into the profile (dicts merge, scalars replace)."""
    def merge(dst: Dict, src: Dict):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                merge(dst[k], v)
            else:
                dst[k] = v
    merge(profile, fields)
    return profile


# ---------------------------------------------------------------------------
# Answer bank
# ---------------------------------------------------------------------------

def answer_save(profile: Dict, question: str, answer: str, tags: Optional[List[str]] = None) -> Dict:
    now = datetime.now(timezone.utc).isoformat()
    bank = profile.setdefault("answer_bank", [])
    for entry in bank:
        if entry["question"].strip().lower() == question.strip().lower():
            entry["answer"] = answer
            entry["tags"] = tags or entry.get("tags", [])
            entry["updated_at"] = now
            return profile
    bank.append({"question": question, "answer": answer, "tags": tags or [], "updated_at": now})
    return profile


def answer_match(profile: Dict, question: str) -> Optional[Tuple[str, float]]:
    """Best fuzzy match from the answer bank, or None below the threshold —
    in which case the AGENT must ask the USER, never invent."""
    bank = profile.get("answer_bank", [])
    if not bank:
        return None
    q = question.strip().lower()
    best: Optional[Tuple[str, float]] = None
    for entry in bank:
        score = difflib.SequenceMatcher(None, q, entry["question"].strip().lower()).ratio()
        if best is None or score > best[1]:
            best = (entry["answer"], score)
    if best and best[1] >= ANSWER_MATCH_THRESHOLD:
        return best
    return None

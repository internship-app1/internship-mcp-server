"""Environment parsing, filesystem paths, and COMPILE mode resolution."""
import os
import shutil
from pathlib import Path

DEFAULT_API_URL = "https://internship-app-production.up.railway.app"


def api_url() -> str:
    return os.getenv("INTERNSHIP_API_URL", DEFAULT_API_URL).rstrip("/")


def api_key() -> str:
    key = os.getenv("INTERNSHIP_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "INTERNSHIP_API_KEY is not set. Generate one at "
            f"{api_url()}/developer and add it to your MCP client config."
        )
    return key


def home() -> Path:
    p = Path(os.getenv("INTERNSHIP_HOME", "~/.internship-agent")).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def resumes_dir() -> Path:
    p = home() / "resumes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def profile_path() -> Path:
    return home() / "profile.enc"


def tracker_path() -> Path:
    return home() / "applications.db"


def pdflatex_available() -> bool:
    return shutil.which("pdflatex") is not None


def compile_mode() -> str:
    """Resolve COMPILE env: local | remote | auto (auto = local if pdflatex present)."""
    mode = os.getenv("COMPILE", "auto").strip().lower()
    if mode == "local":
        return "local"
    if mode == "remote":
        return "remote"
    return "local" if pdflatex_available() else "remote"


def max_auto_submits() -> int:
    try:
        return int(os.getenv("MAX_AUTO_SUBMITS", "10"))
    except ValueError:
        return 10

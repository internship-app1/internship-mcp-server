"""Compile-engine parity: the vendored compile_local core must produce
byte-similar output to the backend's compile_resume_json_to_pdf for shared
fixtures (same pdflatex, same template.tex, same ladder).

Run with: pytest -m parity
Requires pdflatex + a sibling checkout of the backend repo (set
INTERNSHIP_APP_DIR, default ../Internship-App or ../internship-app).
"""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

from internship_mcp import compile_local

pytestmark = pytest.mark.parity

needs_pdflatex = pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex not installed"
)


def _load_backend_compile():
    candidates = [os.getenv("INTERNSHIP_APP_DIR", "")] if os.getenv("INTERNSHIP_APP_DIR") else []
    here = Path(__file__).resolve().parent.parent
    candidates += [str(here.parent / "Internship-App"), str(here.parent / "internship-app")]
    for cand in candidates:
        path = Path(cand) / "resume_tailor" / "tailor_resume.py"
        if path.exists():
            # Load WITHOUT importing the backend package machinery (and without
            # needing its venv): stub out the anthropic import it does not use
            # on the deterministic path.
            import types
            sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))
            spec = importlib.util.spec_from_file_location("backend_tailor", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    pytest.skip("backend checkout not found — set INTERNSHIP_APP_DIR")


@needs_pdflatex
class TestCompileParity:
    def test_template_files_identical(self):
        backend = _load_backend_compile()
        backend_template = (
            Path(backend.__file__).parent / "template.tex"
        ).read_text()
        local_template = compile_local._TEMPLATE_PATH.read_text()
        assert backend_template == local_template, (
            "template.tex drifted between repos — sync them and this test in one PR"
        )

    def test_same_pdf_output(self, sample_resume_json):
        backend = _load_backend_compile()
        local_pdf, local_diag = compile_local.compile_resume_json_to_pdf(sample_resume_json)
        backend_pdf, backend_diag = backend.compile_resume_json_to_pdf(sample_resume_json)

        assert local_diag["font_size"] == backend_diag["font_size"]
        assert local_diag["spacing"] == backend_diag["spacing"]
        assert local_diag["pages"] == backend_diag["pages"]
        assert abs(local_diag["fill_ratio"] - backend_diag["fill_ratio"]) < 0.02

        # Byte-similar: pdflatex embeds timestamps, so exact equality is not
        # expected — but size must agree within a small tolerance and the text
        # layers must match exactly.
        assert abs(len(local_pdf) - len(backend_pdf)) < 2048
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(local_pdf)) as a, \
                pdfplumber.open(io.BytesIO(backend_pdf)) as b:
            text_a = "\n".join(p.extract_text() or "" for p in a.pages)
            text_b = "\n".join(p.extract_text() or "" for p in b.pages)
        assert text_a == text_b

# internship-mcp — primary distribution image.
# Bakes pinned pdflatex (TeX Live) + poppler-utils (pdftotext for widow
# measurement) + tesseract (OCR) so local compile works identically on every
# OS/agent. Run with:
#   docker run -i --rm -e INTERNSHIP_API_KEY \
#     -v internship-home:/root/.internship-agent internship-mcp
FROM python:3.12-slim-bookworm

# TeX Live subset: latex + extras covering extarticle (extsizes), enumitem,
# titlesec, parskip, microtype, hyperref + recommended fonts. Pinned by the
# bookworm release; rebuilds stay reproducible within the tag.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        poppler-utils \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY internship_mcp ./internship_mcp
RUN pip install --no-cache-dir ".[ocr]"

# Local compile is the default inside the image (TeX is present).
ENV COMPILE=local
ENV INTERNSHIP_HOME=/root/.internship-agent

# stdio transport — the MCP host attaches to stdin/stdout.
ENTRYPOINT ["internship-mcp"]

# internship-mcp

A vendor-neutral [MCP](https://modelcontextprotocol.io) server that turns any MCP-capable
agent (Claude Code, Cursor, Codex, Windsurf, Cline) into an **internship apply agent**:
pull fresh internship postings, deterministically prefilter them against your skills,
tailor your resume per job (your agent writes the bullets, pdflatex compiles the PDF
locally), assemble a fully-filled application packet, and prefill ATS forms via the
Playwright MCP — while **you** review and hit submit.

**Design principles**

- **Your agent is the brain.** This server never calls a model. Skill extraction,
  ranking, bullet rewriting, and answers are your agent's own reasoning over
  deterministic data.
- **Your PII stays on your machine.** Citizenship, visa, EEO, and demographic answers
  live in a Fernet-encrypted local file and flow only into the application forms you
  approve — never to our backend.
- **Compile is local by default.** The Docker image bakes pdflatex; the backend compile
  endpoint is a rate-limited fallback for the no-Docker quick start.

## Quick start

1. Sign in at the Internship Matcher web app and generate an API key on the
   `/developer` page.
2. Add the server to your MCP client config:

**Docker (recommended — local compile, OCR, fully reproducible)**

```json
{
  "mcpServers": {
    "internship": {
      "command": "docker",
      "args": ["run", "-i", "--rm",
               "-v", "internship-home:/root/.internship-agent",
               "-e", "INTERNSHIP_API_KEY",
               "ghcr.io/internship-app1/internship-mcp:latest"],
      "env": { "INTERNSHIP_API_KEY": "im_live_..." }
    },
    "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] }
  }
}
```

**uvx (quick start — no system deps, compile falls back to the backend)**

```json
{
  "mcpServers": {
    "internship": {
      "command": "uvx",
      "args": ["internship-mcp"],
      "env": { "INTERNSHIP_API_KEY": "im_live_...", "COMPILE": "remote" }
    },
    "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] }
  }
}
```

Config file locations: Claude Code `.mcp.json` · Cursor `~/.cursor/mcp.json` ·
Codex `~/.codex/config.toml` · Windsurf `~/.codeium/windsurf/mcp_config.json` ·
Cline `cline_mcp_settings.json`.

3. Ask your agent something like: *"Set up my internship profile, then find new
   postings from the last 3 days that fit my resume at ~/resume.pdf, tailor my resume
   for the top 5, and prefill the applications for my review."*

## Environment

| Var | Default | Meaning |
|---|---|---|
| `INTERNSHIP_API_KEY` | (required) | per-user key from `/developer` |
| `INTERNSHIP_API_URL` | production URL | backend base URL |
| `INTERNSHIP_HOME` | `~/.internship-agent` | encrypted profile, tracker DB, PDFs |
| `COMPILE` | `auto` | `local` / `remote` / `auto` (local if pdflatex present) |
| `INTERNSHIP_PROFILE_KEY` | — | fallback Fernet key when no OS keyring exists |
| `MAX_AUTO_SUBMITS` | `10` | v2 per-session auto-submit cap |

## Development

```bash
pip install -e ".[dev]"
pytest                 # unit tests
pytest -m parity       # compile parity vs the backend core (needs pdflatex)
npx @modelcontextprotocol/inspector uvx --from . internship-mcp
docker build -t internship-mcp .
```

## Safety & terms

v1 is **assisted**: the agent prefills, **you** review and submit. Auto-submit (v2) is
opt-in, dry-run by default, capped per session, and blocked by any low-confidence field.
Subjective questions ("why us?", "proudest achievement") are always asked **to you** and
saved in your local answer bank — never fabricated. EEO questions default to "Decline to
self-identify" unless you set them. You are responsible for the accuracy of every
application and for complying with each job board's terms of service. Every submission
is logged locally with the exact answers used.

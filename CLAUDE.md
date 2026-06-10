# internship-mcp — Claude Context

## What this repo is
The thin, public, user-run MCP client for the Internship Apply Agent. Any MCP host
(Claude Code, Cursor, Codex, Windsurf, Cline) connects over stdio. It gives the agent
deterministic tools — fetch jobs, prefilter, compile a tailored resume, store/answer profile
questions, build an application packet, track applications — while THE AGENT does all
reasoning (skill extraction, ranking, bullet rewriting, answering questions).

This file owns MCP-internal depth. For cross-repo law read the workspace CLAUDE.md one level
up. For backend internals read internship-app/CLAUDE.md. Full design: the PRD.

## Cardinal rules for this repo
1. Import ZERO modules from internship-app. Thin client; talk HTTP to /api/v1. Contract = the
   published OpenAPI spec (validated in CI).
2. No model calls, ever. No Anthropic SDK here. If a task needs intelligence, expose the data
   and let the host agent reason. Tools are dumb and deterministic by design.
3. PII never leaves the machine. Profile + raw resume live encrypted under INTERNSHIP_HOME.
   Only a small resume-profile object and (remote-compile fallback only) tailored resume JSON
   may go to the backend.
4. Agent-agnostic. stdio only. No Claude-Code-only features. Identical in Cursor/Codex/etc.

## Project structure
internship_mcp/
  __main__.py        # FastMCP app; registers tools + the resume://tailoring-guide resource
  client.py          # httpx -> backend /api/v1; injects X-API-Key; structured errors
  profile_store.py   # encrypted profile + answer bank (Fernet); key resolution
  tracker.py         # local SQLite application log; dedup
  resume_local.py    # pdfplumber text extraction (+ optional pytesseract OCR)
  compile_local.py   # vendored compile_resume_json_to_pdf (pdflatex) — parity with backend
  packet.py          # application-packet assembly; confidence + needs_user_input guardrail
  schemas.py         # pydantic IO models (shared by tools + OpenAPI client validation)
  config.py          # env parsing, paths, COMPILE mode resolution
Dockerfile           # bakes TeX Live + tesseract + fonts; local compile works OOTB
pyproject.toml       # PyPI package "internship-mcp"; entry -> python -m internship_mcp

## Tool surface (authoritative contracts)
Registered in __main__.py via FastMCP. Plane = where the work happens.
| Tool | Inputs | Returns | Side effects | Plane |
|---|---|---|---|---|
| profile_setup | — | {profile, missing_required[], optional_questions[]} | reads profile.enc | local |
| profile_get | — | full profile (decrypted in-process) | — | local |
| profile_set | fields | updated profile | writes profile.enc (atomic) | local |
| answer_save | question, answer, tags? | {ok} | appends to answer_bank | local |
| answer_match | question | {answer, score} or null | — | local |
| resume_parse | path | {text, warnings} | reads local file | local |
| jobs_list | since_hours?,max_days_old?,location?,q?,limit? | {jobs[],total,...} | HTTP GET | backend |
| job_get | job_hash | full job + untruncated JD | HTTP GET | backend |
| jobs_prefilter | resume_profile,filters?,target_count? | {candidates[],...} | HTTP POST | backend |
| resume_compile | resume_json,options? | {pdf_path,diagnostics} | writes PDF under INTERNSHIP_HOME/resumes | local or backend per COMPILE |
| packet_build | job_hash,field_labels,resume_pdf_path,answers?,force? | packet | reads profile + answer bank | local |
| application_record | job_hash,status,... | {ok} | upsert applications.db | local |
| applications_list | status? | applications[] | — | local |
| application_status | job_hash | status or null | — | local |
| autosubmit_plan (v2) | job_hash,packet,dry_run | fill plan + confirm prompt | — | local |

Tool DESCRIPTIONS matter — they teach the host agent the flow. Each must state: what it does,
that the AGENT (not the tool) supplies reasoning, and the next tool in the sequence.

## Intended agent call-flow (encode in tool descriptions)
profile_setup -> (if missing) interview the user -> profile_set ->
resume_parse(path) -> agent extracts skills itself ->
jobs_list(since_hours=72) -> jobs_prefilter(resume_profile) ->
agent ranks (quick=trust combined_score / deep=job_get full JDs + agent re-ranks) ->
per job: job_get -> agent rewrites resume_json for the JD -> resume_compile ->
agent inspects diagnostics.widows, fixes bullets, recompiles if needed ->
packet_build (fills from profile + answer_match; subjective/unknown -> ask the USER ->
answer_save) -> host drives Playwright MCP to prefill the form -> user submits ->
application_record(status="prefilled"). Dedup via applications_list/application_status.

## Local stores
### profile_store.py
- File INTERNSHIP_HOME/profile.enc, Fernet-encrypted, atomic write, chmod 600.
- Schema: PRD 8.1. EEO fields default "decline" and are NEVER required. The setup
  interview OFFERS them once (optional_interview_questions; gated by
  _meta.setup_interview_done) so packet_build can fill real values — skipping keeps
  "decline"; the agent must never infer them.
  _meta.schema_version gates migrations.
- Key resolution: OS keyring (service "internship-agent") -> INTERNSHIP_PROFILE_KEY env ->
  first-run passphrase (agent prompts user; cache derived key in keyring). Never log key/PII.
- missing_required drives the interview: full_name, email, phone, city/state, linkedin|github,
  us_citizen, requires_sponsorship, willing_to_relocate, earliest_start_date.
- answer_bank inside the profile blob: [{question, answer, tags[], updated_at}]. answer_match =
  difflib ratio over questions; return best with score; threshold ~0.72, below which return
  null so the agent asks the user.
### tracker.py
- File INTERNSHIP_HOME/applications.db (SQLite). Schema: PRD 8.2.
- Dedup: packet_build/autosubmit_plan refuse a job already submitted unless force=true.
  application_record is an upsert keyed on job_hash.
### resume_local.py
- pdfplumber for text; pytesseract OCR ONLY if tesseract binary present (Docker). Degrade to
  PDF-only — never hard-fail on missing OCR. base_json is best-effort; the AGENT builds the
  real tailored resume_json.
### compile_local.py
- Vendors the backend's deterministic compile core + template.tex. PARITY mandatory: local
  output must match /v1/compile (same pdflatex, same template). CI asserts byte-similar. Change
  the template/ladder -> update the backend copy and the parity test in the same PR. Writes
  PDFs to INTERNSHIP_HOME/resumes/<company>_<role>.pdf; returns path + diagnostics.

## client.py
- Base URL INTERNSHIP_API_URL (default prod); header X-API-Key: $INTERNSHIP_API_KEY.
- 401 -> "invalid/revoked API key — regenerate at /developer". 429 -> surface Retry-After
  (compile concurrency cap). Network errors -> retry backoff 2/4/8s, then legible failure.
- Validate responses against OpenAPI-generated models in schemas.py; contract drift fails CI.

## packet.py (the guardrail lives here)
- Fill order per field: exact profile field -> answer_match (>= threshold) -> flag for user.
- Each field carries source in {profile, profile_eeo, answer_bank} and confidence in
  {high, medium, low}.
- needs_user_input = anything subjective/authentic that isn't a high-confidence answer-bank
  hit. Agent asks the USER and answer_saves it — never fabricate. EEO with no stored value ->
  "Decline to self-identify", never invented.
- Detect ats_type from apply_link host (greenhouse/lever/ashby/workday/other) so the host +
  Playwright MCP pick the right fill strategy.

## Config / env
| Var | Default | Meaning |
|---|---|---|
| INTERNSHIP_API_KEY | (required) | per-user key from /developer; sent as X-API-Key |
| INTERNSHIP_API_URL | prod URL | backend base |
| INTERNSHIP_HOME | ~/.internship-agent | profile.enc, applications.db, resumes/ |
| COMPILE | auto | local / remote / auto (local if pdflatex present) |
| INTERNSHIP_PROFILE_KEY | — | fallback Fernet key if keyring unavailable |
| MAX_AUTO_SUBMITS | 10 | v2 per-session submit cap |

## Distribution
- Docker (primary): bakes pinned TeX Live + tesseract + fonts -> COMPILE=local OOTB; mount a
  named volume at INTERNSHIP_HOME. Reproducible, cross-agent default.
- uvx (quick-start): uvx internship-mcp; no system deps (pdfplumber only, OCR off,
  COMPILE=auto). Playwright MCP is a SEPARATE server the host orchestrates — not bundled.

## Dev commands
INTERNSHIP_API_KEY=im_live_... uvx --from . internship-mcp
docker build -t internship-mcp . && docker run -i --rm -e INTERNSHIP_API_KEY -v internship-home:/root/.internship-agent internship-mcp
npx @modelcontextprotocol/inspector uvx --from . internship-mcp
pytest ; pytest -m parity

## Testing
- Unit: profile encrypt/decrypt round-trip; EEO "decline" defaults; answer_match thresholds;
  tracker dedup; ats_type detection; packet needs_user_input routing.
- Contract: mock backend from OpenAPI; assert client models match.
- Parity: compile_local output ~ backend /v1/compile for shared fixtures.
- Cross-client smoke: Inspector + at least one non-Claude host (Cursor) per release.
- Fixtures: saved Greenhouse/Lever/Ashby form HTML for Phase-1 packet->field tests.

## Footguns
- Importing internship-app -> breaks the thin-client boundary. Use HTTP.
- Swapping pdflatex for tectonic/XeTeX -> diverges from backend; parity test fails. Don't.
- Hard pytesseract dependency -> breaks uvx path. Keep OCR optional.
- Logging decrypted PII or the Fernet key -> privacy violation. Never.
- Auto-answering subjective questions or inventing EEO values -> violates the guardrail.
- Forgetting to bump _meta.schema_version on profile shape change -> silent corruption.
- experience_level enum is exactly student | entry_level | experienced. No recent_graduate.

## Self-Learning
Append MCP-internal decisions here, newest-last: branch/PR, what changed, and the constraint
that drove it. Cross-repo decisions go in the workspace CLAUDE.md instead.

### Initial publish (Jun 2026)
- Published at github.com/internship-app1/**internship-mcp-server** — repo and GHCR image
  are named `internship-mcp-server`; the PyPI package / Python dir stays `internship-mcp`.
  Keep Docker snippets pointing at `ghcr.io/internship-app1/internship-mcp-server`.
- History is one-commit-per-module by design; keep that granularity for future features.

### Remote-compile weekly quota (backend PR #27, Jun 2026)
- The backend caps remote compiles at **15/week per account** plus
  3-concurrent admission. 429s from /resume/compile now come in two flavors: capacity ("retry
  shortly") and weekly quota ("resets <date>; compile locally for unlimited") — surface
  the detail string to the agent verbatim; the quota one should steer users to
  COMPILE=local, not to retries. Cache-hit compiles are free server-side.

### Distribution rethink: hosted discovery + uvx full agent (Jun 2026)
- Internship-App now has a hosted `/mcp` discovery tier: only `jobs_list`, `job_get`,
  `jobs_prefilter`, and a resource pointing users here. It is the zero-install funnel,
  not the apply agent. Do not add vault/profile/resume/packet/compile tools to hosted.
- This repo remains the full apply agent. `uvx internship-mcp` is the headline install
  path; Docker is advanced/reproducible only. Snippets should omit `COMPILE` so
  `COMPILE=auto` chooses local pdflatex when present and remote fallback otherwise.
- Onboarding should ask the compile choice first: install TeX locally for unlimited
  compiles, or use the remote fallback capped at 15/week. PII vault remains local.

### Setup interview covers optional EEO/work-auth questions (Jun 2026)
- Product decision: profile_setup now also returns optional_questions (work auth,
  visa, gender, race/ethnicity, Hispanic/Latino, veteran, disability, logistics) so
  the FIRST-RUN interview collects real values for application autofill. Constraints
  kept: every question optional (skip -> 'decline'), asked exactly once
  (_meta.setup_interview_done flag — set it via profile_set when the interview ends),
  changeable any time via profile_set, never inferred, never sent to our backend.

### Streamable-HTTP dev harness (Jun 2026)
- For remote testing (claude.ai custom connectors, Inspector over a tunnel) the same
  FastMCP app can run `mcp.run(transport="streamable-http")` with
  `settings.stateless_http=True`. DEV ONLY — the product transport is stdio (cardinal
  rule 4). Two gotchas: the SDK's DNS-rebinding protection rejects foreign Host headers
  (rewrite Host to 127.0.0.1:<port> at the proxy/tunnel), and a public endpoint shares
  ONE INTERNSHIP_API_KEY + vault with every caller — use a scratch INTERNSHIP_HOME and a
  disposable key, never a real profile.

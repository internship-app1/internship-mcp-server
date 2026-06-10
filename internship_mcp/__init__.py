"""internship-mcp — thin, public, user-run MCP client for the Internship Apply Agent.

Cardinal rules (see CLAUDE.md):
1. Zero imports from internship-app — HTTP to /api/v1 only.
2. No model calls, ever. The host agent supplies all reasoning.
3. PII never leaves the machine (encrypted under INTERNSHIP_HOME).
4. Agent-agnostic: stdio transport, no Claude-Code-only features.
"""

__version__ = "0.1.0"

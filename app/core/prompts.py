"""
Feature prompt templates for Agent Harness Template

Each function returns a self-contained prompt that instructs the Agent 
to produce a well-structured markdown result.
"""

_MERMAID_INSTRUCTION = """

## MANDATORY: Diagram(s)

You MUST include one or more diagrams at the END of your response.

**Diagram format rules (follow strictly):**
- DEFAULT: use Mermaid (`mermaid` fenced code block). Follow every rule in the
  /mermaid-expert skill for chart-type selection, valid syntax, and styling.
- ONLY use the /drawio skill (`.drawio` XML) if the user explicitly asked for
  a draw.io diagram — otherwise always produce Mermaid.

Replace placeholder values with actual data. Generate as many diagrams as needed.
"""

def playground(prompt: str, generate_diagram: bool = False) -> str:
    """Return the base prompt for the generic Agent Playground."""
    diagram_section = _MERMAID_INSTRUCTION if generate_diagram else ""
    return f"""You are a generalized AI assistant.

The user wants to execute a task: "{prompt}"

## Your Task

Analyze the user's request and act on it using your available tools.

You have access to a secure, isolated shell environment.
Use your shell tool to execute commands, interact with APIs, read local files,
and perform any operations necessary to complete the task.

## Rules

- Show your work: if you run a command, explain briefly what you are doing.
- Handle errors gracefully: if a command fails, read the error and try a different approach.
- Produce clear, structured markdown output.

**GitHub interactions — MANDATORY rule:**
ALWAYS use the `gh` CLI (GitHub CLI) for ALL GitHub operations.
NEVER call the GitHub REST API directly (no `curl https://api.github.com/...`, no `web_fetch` against github.com/api, no MCP `github_*` HTTP tools).
If `gh` is not authenticated or returns an error, report that error — do NOT fall back to the API.

Examples:
- List repos: `gh repo list <org> --limit 10 --json name,updatedAt,url`
- View issues: `gh issue list --repo <org/repo>`
- PRs: `gh pr list --repo <org/repo>`
- Clone / create: `gh repo clone ...` / `gh repo create ...`

{diagram_section}
"""

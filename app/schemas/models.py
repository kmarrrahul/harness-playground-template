"""Request / response models for Agent Harness Template"""
from pydantic import BaseModel

class RunRequest(BaseModel):
    # ── Provider selection ────────────────────────────────────────────────
    # "copilot" (default for backward compat) | "antigravity" | "cursor" | "claude_code"
    provider: str = "copilot"
    feature: str                        # "playground"
    params: dict[str, str]              # query, prompt, etc.
    model: str = "claude-sonnet-4.6"
    generate_diagram: bool = False
    # Optional per-session gh CLI token supplied from the UI.
    gh_cli_token: str = ""
    gh_cli_hostname: str = "github.com"
    # Reasoning effort: "" | "low" | "medium" | "high" | "xhigh"
    reasoning_effort: str = ""
    claude_auth_method: str = "anthropic"
    claude_bedrock_region: str = "us-east-1"
    claude_vertex_project: str = ""
    claude_vertex_region: str = "us-central1"
    claude_base_url: str = ""
    copilot_byok_type: str = ""
    copilot_byok_base_url: str = ""
    copilot_byok_wire_api: str = ""
    copilot_byok_api_key: str = ""
    codex_api_key: str = ""
    codex_auth_method: str = "openai"
    codex_bedrock_region: str = "us-east-1"
    codex_ollama_base_url: str = "http://localhost:11434/v1"
    enabled_skills: list[str] = []
    session_id: str | None = None
    inherit_github_env: bool = True


class FollowupRequest(BaseModel):
    # ── Provider selection ────────────────────────────────────────────────
    provider: str = "copilot"
    session_id: str
    query: str
    model: str = "claude-sonnet-4.6"
    gh_cli_token: str = ""
    gh_cli_hostname: str = "github.com"
    # Reasoning effort: "" | "low" | "medium" | "high" | "xhigh"
    reasoning_effort: str = ""
    claude_auth_method: str = "anthropic"
    claude_bedrock_region: str = "us-east-1"
    claude_vertex_project: str = ""
    claude_vertex_region: str = "us-central1"
    claude_base_url: str = ""
    copilot_byok_type: str = ""
    copilot_byok_base_url: str = ""
    copilot_byok_wire_api: str = ""
    copilot_byok_api_key: str = ""
    codex_api_key: str = ""
    codex_auth_method: str = "openai"
    codex_bedrock_region: str = "us-east-1"
    codex_ollama_base_url: str = "http://localhost:11434/v1"
    enabled_skills: list[str] = []
    inherit_github_env: bool = True

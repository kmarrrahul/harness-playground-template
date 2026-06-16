"""
Antigravity service layer — manages per-user Agent lifecycles,
session streaming, and SSE event translation.

Uses Google's Antigravity SDK (google-antigravity) with the Gemini model family.
Authentication is via GEMINI_API_KEY (per-user or server-side).

Adapted from copilot_service.py to match the common SSE event contract.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import sys
import time
from collections.abc import AsyncGenerator

from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.types import (
    CapabilitiesConfig,
    BuiltinTools,
    GeminiConfig,
    ModelConfig,
    ModelEntry,
    GenerationConfig,
    ThinkingLevel,
    Text,
    Thought,
    ToolCall,
    ToolResult,
    McpStdioServer,
)
from google.antigravity.hooks import policy

from ..core.mcp_config import cleanup_creds_dir, get_base_mcp_config
from ..github_auth import build_gh_env

logger = logging.getLogger(__name__)

# ── Thinking level mapping ────────────────────────────────────────────────
_THINKING_MAP: dict[str, ThinkingLevel] = {
    "low": ThinkingLevel.LOW,
    "medium": ThinkingLevel.MEDIUM,
    "high": ThinkingLevel.HIGH,
    "minimal": ThinkingLevel.MINIMAL,
    # Copilot uses "xhigh" — map to HIGH for Antigravity
    "xhigh": ThinkingLevel.HIGH,
}

# ── Default Antigravity model ─────────────────────────────────────────────
DEFAULT_MODEL = "gemini-3.5-flash"

# ── Active session pool (Agent + conversation_id) ─────────────────────────
# Key = session_id (conversation_id from the SDK)
# Value = (Agent instance, feature_id, last_accessed_ts)
_active_sessions: dict[str, tuple[Agent, str, float]] = {}
_active_sessions_lock = asyncio.Lock()
_SESSION_IDLE_TTL = 1800  # 30 minutes

# Lock to safely inject os.environ around subprocess spawns
_os_env_lock = asyncio.Lock()


def _token_key(token: str) -> str:
    """Derive a short cache key from a token."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _build_agent_config(
    api_key: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = "",
    system_instructions: str = "",
    feature_id: str = "",
    session_key: str = "",
    conversation_id: str | None = None,
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True,
) -> tuple[LocalAgentConfig, dict[str, str]]:
    """Build a LocalAgentConfig and isolated env_vars for a new Antigravity agent session."""
    # Determine thinking level
    thinking_level = _THINKING_MAP.get(reasoning_effort.lower()) if reasoning_effort else ThinkingLevel.LOW

    # Determine which tools to enable based on feature
    if feature_id in ("playground", "iac_generator"):
        # Full tool access for playground and IaC generator
        capabilities = CapabilitiesConfig(
            enabled_tools=BuiltinTools.all_tools(),
        )
    elif feature_id in ("aws_governance", "k8s_ops"):
        # Read tools + run_command for AWS/k8s operations
        capabilities = CapabilitiesConfig(
            enabled_tools=[
                BuiltinTools.LIST_DIR,
                BuiltinTools.SEARCH_DIR,
                BuiltinTools.FIND_FILE,
                BuiltinTools.VIEW_FILE,
                BuiltinTools.RUN_COMMAND,
                BuiltinTools.FINISH,
            ],
        )
    else:
        # Default: read-only + run_command
        capabilities = CapabilitiesConfig(
            enabled_tools=[
                *BuiltinTools.read_only(),
                BuiltinTools.RUN_COMMAND,
            ],
        )

    # Build MCP servers list for infrastructure tools
    mcp_servers = []
    # On Windows npx is a .cmd script — find the real executable path
    def _npx_cmd() -> str | None:
        """Return path to npx executable, handling Windows .cmd wrapper."""
        if sys.platform == "win32":
            # Try npx.cmd first (Windows npm installs use .cmd wrappers)
            npx_cmd = shutil.which("npx.cmd") or shutil.which("npx")
        else:
            npx_cmd = shutil.which("npx")
        return npx_cmd

    npx_path = _npx_cmd()

    if npx_path and feature_id in ("iac_generator", "playground"):
        pass # terraform MCP server package does not exist on npm

    if npx_path and feature_id in ("iac_generator", "playground"):
        import tempfile
        workspace = os.path.join(tempfile.gettempdir(), f"infra-agent-workspace-{session_key}")
        os.makedirs(workspace, exist_ok=True)
        mcp_servers.append(
            McpStdioServer(
                name="filesystem",
                command=npx_path,
                args=["-y", "@modelcontextprotocol/server-filesystem", workspace],
            )
        )

    if not npx_path and feature_id in ("iac_generator", "playground"):
        logger.warning("npx not found — skipping MCP servers (terraform, filesystem). Install Node.js to enable them.")

    # Workspaces
    import tempfile
    workspace_dir = os.path.join(tempfile.gettempdir(), f"infra-agent-workspace-{session_key}")
    os.makedirs(workspace_dir, exist_ok=True)
    workspaces_list = [workspace_dir]
    if active_skills_dir:
        workspaces_list.append(active_skills_dir)

    # Environment variables
    gh_env = {}
    if gh_cli_token.strip():
        default_host = os.environ.get("GH_CLI_HOSTNAME", "github.com") if inherit_github_env else "github.com"
        ghhost = gh_cli_hostname.strip() if gh_cli_hostname.strip() else default_host
        gh_env = build_gh_env(gh_cli_token.strip(), ghhost, session_key)

    env_vars = dict(os.environ)
    if not inherit_github_env:
        for k in list(env_vars.keys()):
            if k.startswith("GH_") or k.startswith("GITHUB_") or k.startswith("COPILOT_GH"):
                env_vars.pop(k, None)
                
    env_vars.update(gh_env)

    config_kwargs: dict = {
        "policies": [policy.allow_all()],
        "capabilities": capabilities,
        "workspaces": workspaces_list,
        "gemini_config": GeminiConfig(
            api_key=api_key,
            models=ModelConfig(
                default=ModelEntry(
                    name=model or DEFAULT_MODEL,
                    generation=GenerationConfig(
                        thinking_level=thinking_level,
                    ),
                ),
            ),
        ),
    }

    if system_instructions:
        config_kwargs["system_instructions"] = system_instructions

    if mcp_servers:
        config_kwargs["mcp_servers"] = mcp_servers

    if conversation_id:
        config_kwargs["conversation_id"] = conversation_id

    if active_skills_dir:
        skills_dir = os.path.join(active_skills_dir, "skills")
        if os.path.exists(skills_dir):
            paths = []
            for d in os.listdir(skills_dir):
                d_path = os.path.join(skills_dir, d)
                if os.path.isdir(d_path):
                    paths.append(d_path)
            if paths:
                config_kwargs["skills_paths"] = paths

    return LocalAgentConfig(**config_kwargs), env_vars


async def _evict_stale_sessions() -> None:
    """Remove sessions idle longer than _SESSION_IDLE_TTL."""
    now = time.monotonic()
    to_evict: list[tuple[str, Agent]] = []
    async with _active_sessions_lock:
        to_evict = [
            (sid, agent) for sid, (agent, _fid, ts) in _active_sessions.items()
            if now - ts > _SESSION_IDLE_TTL
        ]
        for sid, _ in to_evict:
            del _active_sessions[sid]
    for sid, agent in to_evict:
        try:
            await agent.__aexit__(None, None, None)
        except Exception:
            pass
        cleanup_creds_dir(sid[:16])
    if to_evict:
        logger.info("Evicted %d stale Antigravity sessions", len(to_evict))


async def _stream_agent_response(
    agent: Agent,
    prompt: str,
    feature_id: str = "",
) -> AsyncGenerator[dict, None]:
    """Send prompt to agent, translate SDK chunks into SSE event dicts."""
    try:
        response = await agent.chat(prompt)

        async for chunk in response.chunks:
            if isinstance(chunk, Text):
                if chunk.text:
                    yield {"type": "delta", "content": chunk.text}
            elif isinstance(chunk, Thought):
                if chunk.text:
                    yield {"type": "reasoning_delta", "content": chunk.text}
            elif isinstance(chunk, ToolCall):
                tool_name = chunk.name if isinstance(chunk.name, str) else getattr(chunk.name, 'value', str(chunk.name))
                tool_id = getattr(chunk, 'id', '') or tool_name
                yield {"type": "tool_start", "name": tool_name, "tool_id": tool_id}
            elif isinstance(chunk, ToolResult):
                tool_name = chunk.name if isinstance(chunk.name, str) else getattr(chunk.name, 'value', str(chunk.name))
                tool_id = getattr(chunk, 'id', '') or tool_name
                yield {"type": "tool_end", "name": tool_name, "tool_id": tool_id}

        # Session completed successfully
        conversation_id = agent.conversation_id or ""
        yield {"type": "done", "session_id": conversation_id}

    except Exception as exc:
        logger.exception("Antigravity agent error")
        yield {"type": "error", "message": str(exc)}


async def run_feature(
    api_key: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    feature_id: str = "",
    reasoning_effort: str = "",
    system_instructions: str = "",
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True
) -> AsyncGenerator[dict, None]:
    """Create a fresh Antigravity agent, run prompt, and stream events."""
    await _evict_stale_sessions()

    session_key = _token_key(api_key + feature_id)

    config, env_vars = _build_agent_config(
        api_key=api_key,
        model=model,
        reasoning_effort=reasoning_effort,
        system_instructions=system_instructions,
        feature_id=feature_id,
        session_key=session_key,
        gh_cli_token=gh_cli_token,
        gh_cli_hostname=gh_cli_hostname,
        active_skills_dir=active_skills_dir,
        inherit_github_env=inherit_github_env
    )

    agent = Agent(config)
    completed_ok = False
    try:
        # Safely inject environment variables down to the Go daemon.
        # Since LocalAgentConfig doesn't support env_vars natively, we swap os.environ
        # exactly during the subprocess spawn (__aenter__).
        async with _os_env_lock:
            old_env = dict(os.environ)
            os.environ.clear()
            os.environ.update(env_vars)
            try:
                await agent.__aenter__()
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        logger.info(
            "Antigravity agent started: model=%s feature=%s thinking=%s",
            model, feature_id, reasoning_effort or "low",
        )

        async for event in _stream_agent_response(agent, prompt, feature_id):
            yield event
            if event.get("type") == "done":
                completed_ok = True

    except Exception as exc:
        logger.exception("Antigravity run_feature error")
        yield {"type": "error", "message": str(exc)}
    finally:
        if completed_ok:
            # Store agent in active sessions for follow-up
            conv_id = agent.conversation_id or ""
            if conv_id:
                async with _active_sessions_lock:
                    _active_sessions[conv_id] = (agent, feature_id, time.monotonic())
                logger.debug("Antigravity session %s stored for follow-up", conv_id)
            else:
                # No conversation_id — clean up
                try:
                    await agent.__aexit__(None, None, None)
                except Exception:
                    pass
        else:
            try:
                await agent.__aexit__(None, None, None)
            except Exception:
                pass


async def run_followup(
    api_key: str,
    session_id: str,
    query: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = "",
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True
) -> AsyncGenerator[dict, None]:
    """Continue a conversation on an existing Antigravity agent session."""
    agent = None
    feature_id = ""

    async with _active_sessions_lock:
        entry = _active_sessions.pop(session_id, None)
        if entry:
            agent, feature_id, _ = entry
            logger.info("Reusing Antigravity session %s for follow-up", session_id)

    if agent is None:
        # Session expired — create new agent with conversation_id to try resuming
        logger.warning("Antigravity session %s not in pool; creating fresh agent", session_id)
        config = _build_agent_config(
            api_key=api_key,
            model=model,
            reasoning_effort=reasoning_effort,
            feature_id=feature_id,
            session_key=_token_key(api_key),
            gh_cli_token=gh_cli_token,
            gh_cli_hostname=gh_cli_hostname,
            active_skills_dir=active_skills_dir,
            conversation_id=session_id,
            inherit_github_env=inherit_github_env
        )
        agent = Agent(config)
        try:
            await agent.__aenter__()
        except Exception as exc:
            yield {"type": "error", "message": f"Failed to resume session: {exc}"}
            return

    completed_ok = False
    try:
        async for event in _stream_agent_response(agent, query, feature_id):
            yield event
            if event.get("type") == "done":
                completed_ok = True
    except Exception as exc:
        logger.exception("Antigravity followup error")
        yield {"type": "error", "message": str(exc)}
    finally:
        if completed_ok:
            conv_id = agent.conversation_id or session_id
            async with _active_sessions_lock:
                _active_sessions[conv_id] = (agent, feature_id, time.monotonic())
            logger.debug("Antigravity session %s re-stored for follow-up", conv_id)
        else:
            try:
                await agent.__aexit__(None, None, None)
            except Exception:
                pass


async def list_models(api_key: str) -> list[dict]:
    """Return available Gemini models from the live google-genai API.

    Fetches the real model list from Google's API using the user's key,
    then filters to generative models and annotates them with reasoning metadata.
    """
    if not api_key or not api_key.strip():
        return []

    try:
        from google import genai

        client = genai.Client(api_key=api_key.strip())
        loop = asyncio.get_running_loop()
        raw_models = await loop.run_in_executor(
            None, lambda: list(client.models.list())
        )

        result: list[dict] = []
        seen_ids: set[str] = set()

        for m in raw_models:
            # m.name is like "models/gemini-2.5-flash"
            raw_name: str = m.name or ""
            model_id = raw_name.removeprefix("models/")

            if not model_id:
                continue

            # Skip embedding, vision-only, TTS, and experimental/deprecated models
            lower = model_id.lower()
            skip_patterns = (
                "embed", "aqa", "image", "vision-only", "tts", "gemma",
                "learnlm", "-001", "-002", "-003", "-004", "-005",
                "-exp-", "flash-8b",
            )
            if any(p in lower for p in skip_patterns):
                continue

            # Deduplicate (API sometimes returns both versioned and alias)
            if model_id in seen_ids:
                continue
            seen_ids.add(model_id)

            # Build a human-readable display name
            display = model_id.replace("-", " ").title()
            # Clean up known prefixes
            display = display.replace("Gemini ", "Gemini ").replace("Models/", "")

            # Determine if the model supports thinking/reasoning
            supports_reasoning = any(
                kw in lower for kw in ("flash-thinking", "thinking", "2.5", "3.0", "3.5")
            )

            # Supported reasoning efforts (all thinking-capable models use these)
            if supports_reasoning:
                if "flash" in lower:
                    efforts = ["minimal", "low", "medium", "high"]
                    default_effort = "low"
                else:
                    efforts = ["low", "medium", "high"]
                    default_effort = "medium"
            else:
                efforts = []
                default_effort = ""

            result.append({
                "id": model_id,
                "name": display,
                "supportsReasoning": supports_reasoning,
                "supportedReasoningEfforts": efforts,
                "defaultReasoningEffort": default_effort,
            })

        # Sort: flash models first (cheaper/faster), then pro
        def sort_key(m: dict) -> tuple:
            name = m["id"].lower()
            # Higher version = comes first (sort descending by version fragment)
            version = 0.0
            for fragment in name.split("-"):
                try:
                    version = float(fragment)
                    break
                except ValueError:
                    pass
            is_flash = "flash" in name
            return (-version, 0 if is_flash else 1)

        result.sort(key=sort_key)

        logger.info("Fetched %d Gemini models from API", len(result))
        return result

    except Exception as exc:
        logger.warning("list_models failed: %s", exc)
        # Return empty — UI will show empty dropdown rather than stale statics
        return []



async def validate_api_key(api_key: str) -> dict:
    """Validate a Gemini API key by making a lightweight API call.

    Uses the google-genai SDK (dependency of Antigravity) to list models.
    """
    if not api_key or not api_key.strip():
        return {"valid": False, "error": "No API key provided"}

    try:
        from google import genai
        client = genai.Client(api_key=api_key.strip())
        # Make a lightweight call to validate the key
        loop = asyncio.get_running_loop()
        models = await loop.run_in_executor(
            None, lambda: list(client.models.list())
        )
        model_names = [m.name for m in models[:5]] if models else []
        return {
            "valid": True,
            "user": f"Antigravity ({len(models)} models available)",
            "models": model_names,
        }
    except Exception as exc:
        error_msg = str(exc)
        if "API_KEY_INVALID" in error_msg or "401" in error_msg:
            return {"valid": False, "error": "Invalid API key"}
        if "403" in error_msg:
            return {"valid": False, "error": "API key lacks permissions"}
        return {"valid": False, "error": f"Validation failed: {error_msg[:200]}"}

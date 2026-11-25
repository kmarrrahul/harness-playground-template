"""
Copilot service layer — manages per-user CopilotClient lifecycles,
session streaming, and Infrastructure MCP server orchestration.

Adapted from AtlassianAI/copilot_service.py for AWS/Terraform/Filesystem tools.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time
from collections.abc import AsyncGenerator

from copilot import CopilotClient, ChildProcessRuntimeConnection
from copilot.session import PermissionHandler

from ..core.mcp_config import cleanup_creds_dir, get_base_mcp_config
from ..github_auth import build_gh_env

logger = logging.getLogger(__name__)

# ── Feature → tool restriction mapping ────────────────────────────────────
# None means "all tools" (["*"]).  A list restricts the session to those tools.
_FEATURE_TOOLS: dict[str, list[str] | None] = {
    "aws_governance": None,   # AWS CLI via shell + filesystem tools
    "iac_generator":  None,   # AWS CLI + Terraform + filesystem tools
    "k8s_ops":        None,   # kubectl via shell tool with per-user KUBECONFIG
    "playground":     None,   # all tools
}

# ── Per-user client pool (keyed by SHA-256(token)[:16]) ───────────────────
_pool: dict[str, tuple[CopilotClient, float]] = {}
_pool_lock = asyncio.Lock()
_CLIENT_TTL = 300  # 5 minutes

# ── Active session pool for follow-up conversations ──────────────────────
_active_sessions: dict[str, tuple[object, str, float]] = {}
_active_sessions_lock = asyncio.Lock()
_SESSION_IDLE_TTL = 1800  # 30 minutes

# ── Background stderr reader tasks ───────────────────────────────────────
_stderr_tasks: set[asyncio.Task] = set()

# ── GitHub Enterprise CLI hostname (for gh auth login) ───────────────────
_GH_CLI_HOSTNAME = os.environ.get("GH_CLI_HOSTNAME", "github.com")


def _token_key(token: str) -> str:
    """Derive a short cache key from a token (never log the raw token)."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]



async def _evict_stale_active_sessions() -> None:
    """Disconnect and remove sessions idle longer than _SESSION_IDLE_TTL."""
    now = time.monotonic()
    to_evict: list[tuple[str, object]] = []
    async with _active_sessions_lock:
        to_evict = [
            (sid, sess) for sid, (sess, _fid, ts) in _active_sessions.items()
            if now - ts > _SESSION_IDLE_TTL
        ]
        for sid, _ in to_evict:
            del _active_sessions[sid]
    for sid, sess in to_evict:
        try:
            await sess.disconnect()
        except Exception:
            pass
        # Clean up any temp credentials files for this session
        cleanup_creds_dir(sid[:16])
    if to_evict:
        logger.info("Evicted %d stale active sessions", len(to_evict))


async def _pipe_stderr_to_log(process, key: str) -> None:
    """Pump CLI subprocess stderr line-by-line into the Python logger."""
    loop = asyncio.get_running_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, process.stderr.readline)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.debug("[CLI %s] %s", key, text)
    except Exception as exc:
        logger.debug("[CLI %s] stderr reader stopped: %s", key, exc)


def _find_copilot_cli() -> tuple[str, list[str]]:
    """Locate the Copilot CLI entry point.

    Prefer the runtime bundled with the SDK to keep its RPC protocol aligned.
    Fall back to the system or npm-installed CLI when the SDK omits it.
    """
    import re
    import sys

    import copilot
    sdk_binary_name = "copilot.exe" if sys.platform == "win32" else "copilot"
    sdk_binary_path = os.path.join(os.path.dirname(copilot.__file__), "bin", sdk_binary_name)
    if os.path.isfile(sdk_binary_path):
        logger.info("Using SDK-bundled Copilot CLI: %s", sdk_binary_path)
        return sdk_binary_path, []

    if sys.platform == "win32":
        vscode_dir = os.path.normcase(
            os.path.join(
                os.environ.get("APPDATA", ""),
                "Code", "User", "globalStorage",
                "github.copilot-chat", "copilotCli",
            )
        )
        for dir_ in os.environ.get("PATH", "").split(os.pathsep):
            dir_ = dir_.strip('"').strip()
            if not dir_ or os.path.normcase(dir_) == vscode_dir:
                continue
            cmd_file = os.path.join(dir_, "copilot.cmd")
            if not os.path.isfile(cmd_file):
                continue
            content = open(cmd_file, encoding="utf-8", errors="ignore").read()
            if re.search(r'node_modules[/\\]@github[/\\]copilot[/\\]npm-loader\.js', content):
                js_path = os.path.join(
                    dir_, "node_modules", "@github", "copilot", "npm-loader.js"
                )
                if os.path.isfile(js_path):
                    logger.info("Using npm Copilot CLI JS: %s", js_path)
                    return js_path, []

        bat_path = os.path.join(
            os.environ.get("APPDATA", ""),
            "Code", "User", "globalStorage",
            "github.copilot-chat", "copilotCli", "copilot.bat",
        )
        if not os.path.isfile(bat_path):
            bat_path = bat_path[:-4] + ".BAT"
        if os.path.isfile(bat_path):
            cmd_exe = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
            logger.info("Using VS Code Copilot CLI bat via cmd.exe: %s", bat_path)
            return cmd_exe, ["/c", bat_path]

        raise RuntimeError(
            "Copilot CLI not found on Windows. "
            "Install @github/copilot via npm or the GitHub Copilot Chat VS Code extension."
        )

    # Linux / macOS
    system_path = shutil.which("copilot")
    candidates = [
        "/root/.local/bin/copilot",
        os.path.expanduser("~/.local/bin/copilot"),
        "/usr/local/bin/copilot",
        "/usr/bin/copilot",
    ]
    if system_path:
        return system_path, []
    for path in candidates:
        if os.path.isfile(path):
            return path, []
    raise RuntimeError(
        "Copilot CLI binary not found. "
        "The github-copilot-sdk package should have bundled it."
    )


async def _get_or_create_client(
    token: str,
    gh_env: dict[str, str],
    inherit_github_env: bool = True,
) -> CopilotClient:
    """Return a live CopilotClient for this token+credentials, creating one if needed.

    so shell commands (aws/kubectl/gh) AND MCP subprocesses use the correct per-user
    credentials.  The pool key includes hashes of all env dicts so each unique
    (token, AWS creds, k8s cluster, GH auth) tuple gets its own isolated CLI process.
    """
    import json as _json

    gh_env_str = _json.dumps(sorted((gh_env or {}).items()), separators=(",", ":"))
    key = _token_key(token + gh_env_str)

    async with _pool_lock:
        # Evict stale clients
        stale_keys = [k for k, (_, ts) in _pool.items()
                      if time.monotonic() - ts > _CLIENT_TTL]
        for k in stale_keys:
            client, _ = _pool.pop(k)
            try:
                await client.stop()
            except Exception:
                pass
            cleanup_creds_dir(k)

        # Reuse existing healthy client
        if key in _pool:
            client, _ = _pool[key]
            _pool[key] = (client, time.monotonic())
            return client

        # Create new client for this token + credentials
        cli_path, cli_args_prefix = _find_copilot_cli()

        subprocess_env = dict(os.environ)
        if not inherit_github_env:
            for k in list(subprocess_env.keys()):
                if k.startswith("GH_") or k.startswith("GITHUB_") or k.startswith("COPILOT_GH"):
                    subprocess_env.pop(k, None)
        subprocess_env["COPILOT_GITHUB_TOKEN"] = token
        # Force Copilot CLI to use its intended API host so it doesn't accidentally 
        # inherit GH_HOST (which is meant exclusively for the `gh` shell tool).
        subprocess_env["COPILOT_GH_HOST"] = subprocess_env.get("COPILOT_GH_HOST", "github.com")

        # Inject GitHub credentials into the Copilot CLI process environment.
        # This ensures shell commands (gh) use the correct per-user credentials
        # — critical for concurrent multi-user isolation.
        if gh_env:
            subprocess_env.update(gh_env)

        if subprocess_env.get("NODE_EXTRA_CA_CERTS"):
            logger.info("NODE_EXTRA_CA_CERTS (system) → %s", subprocess_env["NODE_EXTRA_CA_CERTS"])
        else:
            logger.debug("NODE_EXTRA_CA_CERTS not set; Node.js will use built-in CA store")

        # Disable the GitHub built-in MCP server — we use the `gh` CLI for all
        # GitHub interactions (GHES-compatible) rather than the github-mcp-server.
        # --disable-builtin-mcps disables: github-mcp-server, playwright, fetch, time.
        base_cli_args = list(cli_args_prefix) if cli_args_prefix else []
        base_cli_args.append("--disable-builtin-mcps")

        # Set the Copilot CLI working directory to a temp workspace so that any
        # files the model creates (Python scripts, etc.) land there instead of
        # the project root — prevents uvicorn --reload from restarting on them.
        import tempfile as _tempfile
        _workspace = os.path.join(_tempfile.gettempdir(), f"infra-agent-workspace-{key}")
        os.makedirs(_workspace, exist_ok=True)

        conn = ChildProcessRuntimeConnection(path=cli_path, args=base_cli_args)
        client = CopilotClient(
            connection=conn,
            env=subprocess_env,
            github_token=token,
            working_directory=_workspace,
            use_logged_in_user=False,
            log_level="debug"
        )
        await client.start()

        proc = getattr(client, "_process", None)
        if proc and getattr(proc, "stderr", None):
            task = asyncio.create_task(_pipe_stderr_to_log(proc, key))
            _stderr_tasks.add(task)
            task.add_done_callback(_stderr_tasks.discard)

        _pool[key] = (client, time.monotonic())
        logger.info(
            "Created new CopilotClient for token key %s", key,
        )
        return client


def _build_session_config(
    model: str = "claude-sonnet-4.6",
    feature_id: str = "",
    session_key: str = "",
    reasoning_effort: str = "",
    byok: dict | None = None,
    active_skills_dir: str | None = None,
) -> dict:
    """Build session config with MCP, model, per-feature tool restrictions, and BYOK."""
    cfg: dict = {
        "on_permission_request": PermissionHandler.approve_all,
        "streaming": True,
        "mcp_servers": get_base_mcp_config(session_key=session_key),
    }
    if model:
        if model.startswith("models/"):
            model = model[7:]
        cfg["model"] = model
    if reasoning_effort and reasoning_effort in ("low", "medium", "high", "xhigh"):
        cfg["reasoning_effort"] = reasoning_effort
        
    if byok and byok.get("type"):
        cfg["provider"] = {
            "type": byok["type"],
            "base_url": byok.get("base_url", ""),
            "api_key": byok.get("api_key", ""),
            "wire_api": byok.get("wire_api", "responses")
        }
        
    if active_skills_dir:
        cfg["skill_directories"] = [active_skills_dir]
        cfg["instruction_directories"] = [active_skills_dir]
        cfg["enable_skills"] = True
        
    return cfg


async def _stream_session(
    session,
    prompt: str,
    feature_id: str = "",
) -> AsyncGenerator[dict, None]:
    """Send prompt, convert SDK events into SSE dicts, and yield them."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    session_id: str = session.session_id
    _feature_id_ref: list[str] = [feature_id]

    def on_event(event) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    unsubscribe = session.on(on_event)
    await session.send(prompt)

    completed_ok = False
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=180.0)
            except asyncio.TimeoutError:
                yield {"type": "error", "message": "Request timed out after 3 minutes."}
                break

            etype = event.type.value

            if etype == "assistant.message_delta":
                content = getattr(event.data, "delta_content", "") or ""
                if content:
                    yield {"type": "delta", "content": content}

            elif etype == "assistant.message":
                content = getattr(event.data, "content", "") or ""
                yield {"type": "message", "content": content}

            elif etype == "assistant.reasoning":
                content = getattr(event.data, "content", "") or ""
                if content:
                    yield {"type": "reasoning", "content": content}

            elif etype == "assistant.reasoning_delta":
                content = getattr(event.data, "delta_content", "") or ""
                if content:
                    yield {"type": "reasoning_delta", "content": content}

            elif etype == "tool.execution_start":
                name = (
                    getattr(event.data, "tool_name", None)
                    or getattr(event.data, "name", "tool")
                )
                tool_id = str(getattr(event.data, "tool_call_id", "") or id(event))
                yield {"type": "tool_start", "name": str(name), "tool_id": tool_id}

            elif etype == "tool.execution_complete":
                name = (
                    getattr(event.data, "tool_name", None)
                    or getattr(event.data, "name", "tool")
                )
                tool_id = str(getattr(event.data, "tool_call_id", "") or "")
                yield {"type": "tool_end", "name": str(name), "tool_id": tool_id}

            elif etype == "session.idle":
                yield {"type": "done", "session_id": session_id}
                completed_ok = True
                break

            elif etype == "session.error":
                msg = getattr(event.data, "message", None) or str(event.data)
                logger.warning("Copilot CLI session error (session %s): %s", session_id, msg)
                yield {"type": "error", "message": str(msg)}
                break

    finally:
        unsubscribe()
        if completed_ok:
            await _evict_stale_active_sessions()
            async with _active_sessions_lock:
                _active_sessions[session_id] = (session, _feature_id_ref[0], time.monotonic())
            logger.debug("Session %s stored in active pool for follow-up", session_id)
        else:
            try:
                await session.disconnect()
            except Exception as exc:
                logger.warning("session.disconnect failed: %s", exc)


async def run_feature(
    token: str,
    prompt: str,
    model: str = "claude-sonnet-4.6",
    feature_id: str = "",
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    reasoning_effort: str = "",
    byok: dict | None = None,
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True
) -> AsyncGenerator[dict, None]:
    """Create a fresh Copilot session, run prompt, and stream events."""
    # Build credential envs (needed for both pool key and subprocess env)
    tmp_key = _token_key(token)  # temporary key for writing creds files
    
    gh_env = {}
    if gh_cli_token.strip():
        default_host = _GH_CLI_HOSTNAME if inherit_github_env else "github.com"
        ghhost = gh_cli_hostname.strip() if gh_cli_hostname.strip() else default_host
        gh_env = build_gh_env(gh_cli_token.strip(), ghhost, tmp_key)

    # Expired: create new Client.
    client = await _get_or_create_client(
        token, gh_env, inherit_github_env
    )
    # Derive stable session_key from the actual pool key for creds file consistency
    import json as _json
    gh_env_str = _json.dumps(sorted(gh_env.items()), separators=(",", ":"))
    session_key = _token_key(token + gh_env_str)
    
    session = await client.create_session(
        **_build_session_config(model, feature_id, session_key, reasoning_effort, byok, active_skills_dir)
    )
    async for event in _stream_session(session, prompt, feature_id):
        yield event


async def run_followup(
    token: str,
    session_id: str,
    query: str,
    model: str = "claude-sonnet-4.6",
    reasoning_effort: str = "",
    gh_cli_token: str = "",
    gh_cli_hostname: str = "",
    byok: dict | None = None,
    active_skills_dir: str | None = None,
    inherit_github_env: bool = True
) -> AsyncGenerator[dict, None]:
    """Continue a conversation on an in-memory session."""
    session = None
    feature_id = ""
    async with _active_sessions_lock:
        entry = _active_sessions.pop(session_id, None)
        if entry:
            session, feature_id, _ = entry
            logger.info("Reusing in-memory session %s for follow-up", session_id)

    if session is None:
        logger.warning(
            "Session %s not in active pool; starting fresh", session_id,
        )
        import json as _json
        tmp_key = _token_key(token)
        gh_env = {}
        if gh_cli_token.strip():
            default_host = _GH_CLI_HOSTNAME if inherit_github_env else "github.com"
            ghhost = gh_cli_hostname.strip() if gh_cli_hostname.strip() else default_host
            gh_env = build_gh_env(gh_cli_token.strip(), ghhost, tmp_key)
        client = await _get_or_create_client(token, gh_env, inherit_github_env)
        gh_env_str = _json.dumps(sorted(gh_env.items()), separators=(",", ":"))
        session_key = _token_key(token + gh_env_str)
        session = await client.create_session(
            **_build_session_config(model, feature_id, session_key, reasoning_effort, byok)
        )

    async for event in _stream_session(session, query, feature_id):
        yield event


async def list_models(token: str) -> list[dict]:
    """Return available Copilot models with their capabilities."""
    client = await _get_or_create_client(token, gh_env={})

    try:
        models = await client.list_models()
        result = []
        for m in models:
            try:
                if m.id.lower() == "auto":
                    continue
                policy_state = m.policy.state if m.policy else "enabled"
                if policy_state not in ("enabled", "unconfigured"):
                    continue
                result.append({
                    "id": m.id,
                    "name": m.name,
                    "supportsReasoning": bool(m.supported_reasoning_efforts) or bool(
                        m.capabilities and m.capabilities.supports
                        and m.capabilities.supports.reasoning_effort
                    ),
                    "supportedReasoningEfforts": m.supported_reasoning_efforts or [],
                    "defaultReasoningEffort": m.default_reasoning_effort or "",
                })
            except Exception as exc:
                logger.debug("list_models: entry error for %s: %s", getattr(m, "id", "?"), exc)
        return result

    except Exception as exc:
        logger.warning("list_models failed: %s", exc)
        return []

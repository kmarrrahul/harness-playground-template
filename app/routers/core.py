from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import os
import shutil
import json
import urllib.request
import urllib.error
import ssl
import asyncio
from ..dependencies import _get_json_body, _extract_token, logger

router = APIRouter()

@router.get("/api/health")
async def health():
    return JSONResponse({"status": "ok", "service": "infra-agent"})

@router.get("/api/server-config")
async def server_config():
    """Return which server-side tokens/credentials are already configured."""
    return JSONResponse({
        "aws_configured":     bool(
            os.environ.get("AWS_ACCESS_KEY_ID")
            or os.environ.get("AWS_ROLE_ARN")
            or os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
        ),
        "gh_cli_configured":  bool(os.environ.get("GH_TOKEN_CLI")),
        "kubectl_available":  bool(shutil.which("kubectl")),
        "kubeconfig_present": bool(
            os.environ.get("KUBECONFIG")
            or os.path.isfile(os.path.expanduser("~/.kube/config"))
        ),
    })

@router.get("/api/version")
async def get_version():
    """Report Copilot CLI and SDK versions installed in this container/environment."""
    import importlib.metadata
    import subprocess
    import re

    def get_pkg_version(name):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return "unknown"

    copilot_sdk = get_pkg_version("github-copilot-sdk")
    antigravity_sdk = get_pkg_version("google-antigravity")
    cursor_sdk = get_pkg_version("cursor-sdk")
    claude_sdk = get_pkg_version("claude-agent-sdk")
    codex_sdk = get_pkg_version("openai-codex")

    cli_path = "unknown"
    cli_version = "unknown"
    try:
        from ..providers.copilot_service import _find_copilot_cli
        resolved_path, args_prefix = _find_copilot_cli()
        cli_path = resolved_path
        if args_prefix:
            cmd = [resolved_path] + args_prefix + ["--version"]
        elif resolved_path.endswith(".js"):
            cmd = ["node", resolved_path, "--version"]
        else:
            cmd = [resolved_path, "--version"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        raw = (result.stdout or result.stderr or "").strip()
        if raw:
            m = re.search(r'\d+\.\d+\.\d+', raw)
            cli_version = m.group(0) if m else raw.splitlines()[0]
    except Exception as exc:
        cli_version = f"error: {exc}"

    return JSONResponse({
        "copilot": {"sdk": {"installed": copilot_sdk}, "cli": {"installed": cli_version, "path": cli_path}},
        "antigravity": {"sdk": {"installed": antigravity_sdk}},
        "cursor": {"sdk": {"installed": cursor_sdk}},
        "claude": {"sdk": {"installed": claude_sdk}},
        "codex": {"sdk": {"installed": codex_sdk}}
    })

@router.post("/api/gist")
async def create_gist(request: Request):
    """Create a GitHub Gist from generated diagrams or code."""
    body = await _get_json_body(request)
    token = body.get("__auth_token") if "__auth_token" in body else _extract_token(request)
    
    if not token:
        return JSONResponse({"error": "Missing Authorization header"}, status_code=401)

    title = body.get("title", "Harness Playground Session").strip() or "Harness Playground Session"
    content = body.get("content", "").strip()
    public = bool(body.get("public", False))

    if not content:
        return JSONResponse({"error": "No content provided"}, status_code=400)

    import re as _re
    safe_name = _re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '-') or "agent-playground-session"
    filename = f"{safe_name}.md"

    gist_payload = {
        "description": title,
        "public": public,
        "files": {filename: {"content": content}},
    }

    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE

    loop = asyncio.get_running_loop()

    def _post_gist():
        data = json.dumps(gist_payload).encode()
        req = urllib.request.Request(
            "https://api.github.com/gists",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )
        handler = urllib.request.HTTPSHandler(context=_ssl_ctx)
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=15) as resp:
            return json.loads(resp.read())

    try:
        result = await loop.run_in_executor(None, _post_gist)
        return JSONResponse({
            "url": result.get("html_url", ""),
            "id": result.get("id", ""),
        })
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(errors="replace")
        logger.warning("Gist creation failed: HTTP %d — %s", exc.code, err_body[:200])
        return JSONResponse({"error": f"GitHub API returned {exc.code}: {err_body[:200]}"}, status_code=exc.code)
    except Exception as exc:
        logger.warning("Gist creation error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

@router.get("/api/debug/providers")
async def debug_providers():
    """Return the list of supported AI providers."""
    return JSONResponse({
        "providers": [
            {
                "id": "copilot",
                "name": "GitHub Copilot",
                "auth": "github_oauth_or_pat",
                "status": "active",
            },
            {
                "id": "antigravity",
                "name": "Google Antigravity",
                "auth": "gemini_api_key",
                "status": "active",
            },
            {
                "id": "cursor",
                "name": "Cursor",
                "auth": "cursor_api_key",
                "status": "active",
            },
            {
                "id": "claude_code",
                "name": "Claude Agent",
                "auth": "anthropic_api_key",
                "status": "planned",
            },
        ]
    })

@router.get("/api/debug/sessions")
async def debug_sessions():
    """Return active session counts per provider (for debugging)."""
    from ..dependencies import copilot_service, antigravity_service, cursor_service, claude_service
    return JSONResponse({
        "copilot": {"active_sessions": len(getattr(copilot_service, '_active_sessions', {}))},
        "antigravity": {"active_sessions": len(getattr(antigravity_service, '_active_sessions', {})) if antigravity_service else 0},
        "cursor": {"active_sessions": len(getattr(cursor_service, '_active_sessions', {})) if cursor_service else 0},
        "claude": {"active_sessions": len(getattr(claude_service, '_active_sessions', {})) if claude_service else 0},
    })

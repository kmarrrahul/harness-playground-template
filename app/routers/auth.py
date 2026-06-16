import os
import json
import asyncio
import ssl
import urllib.request
import urllib.error
import configparser
import html as html_mod
import shutil
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse

from .. import oauth
from ..dependencies import _get_json_body, logger

router = APIRouter()

@router.post("/api/validate-token")
async def validate_token(request: Request):
    """Test a user-supplied token or AWS credentials.

    Body: {"type": "github"|"gh_cli"|"aws", "token": "...", "aws": {...}}
    """
    body = await _get_json_body(request)
    token_type: str = body.get("type", "")
    token: str = body.get("token", "").strip()
    logger.debug("validate-token called: type=%s", token_type)

    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE

    def _get_json(api_url: str, bearer: str) -> dict:
        req = urllib.request.Request(
            api_url,
            headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
        )
        handler = urllib.request.HTTPSHandler(context=_ssl_ctx)
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=10) as resp:
            return json.loads(resp.read())

    loop = asyncio.get_running_loop()
    try:
        if token_type == "github":
            if not token:
                return JSONResponse({"valid": False, "error": "No token provided"})
            data = await loop.run_in_executor(
                None, lambda: _get_json("https://api.github.com/user", token)
            )
            return JSONResponse({"valid": True, "user": data.get("login")})

        elif token_type == "gh_cli":
            if not token:
                return JSONResponse({"valid": False, "error": "No token provided"})
            hostname = body.get("hostname", "").strip()
            if not hostname:
                inherit_github_env = body.get("inherit_github_env", True)
                hostname = os.environ.get("GH_CLI_HOSTNAME", "github.com") if inherit_github_env else "github.com"
            if hostname == "github.com":
                api_url = "https://api.github.com/user"
            else:
                api_url = f"https://{hostname}/api/v3/user"
            data = await loop.run_in_executor(
                None, lambda: _get_json(api_url, token)
            )
            return JSONResponse({"valid": True, "user": data.get("login")})

        elif token_type == "aws":
            aws_data = body.get("aws", {})
            auth_method = aws_data.get("auth_method", "")
            access_key = aws_data.get("access_key", "").strip()
            secret_key = aws_data.get("secret_key", "").strip()
            session_token = aws_data.get("session_token", "").strip()
            region = aws_data.get("region", "us-east-1").strip() or "us-east-1"
            creds_file_content = aws_data.get("creds_file_content", "").strip()
            
            if auth_method == "creds_file":
                if not creds_file_content:
                    return JSONResponse({"valid": False, "error": "Credentials file content is empty"})
                parser = configparser.RawConfigParser()
                parser.read_string(creds_file_content)
                defaults = dict(parser.defaults())
                if defaults.get("aws_access_key_id"):
                    access_key = defaults.get("aws_access_key_id", "").strip()
                    secret_key = defaults.get("aws_secret_access_key", "").strip()
                    session_token = defaults.get("aws_session_token", "").strip()
                    if not region or region == "us-east-1":
                        region = defaults.get("region", "us-east-1").strip() or "us-east-1"
                else:
                    sections = parser.sections()
                    if not sections:
                        return JSONResponse({"valid": False, "error": "No [default] or named sections found in credentials file"})
                    section = sections[0]
                    access_key = parser.get(section, "aws_access_key_id", fallback="").strip()
                    secret_key = parser.get(section, "aws_secret_access_key", fallback="").strip()
                    session_token = parser.get(section, "aws_session_token", fallback="").strip()
                    if not region or region == "us-east-1":
                        region = parser.get(section, "region", fallback="us-east-1").strip() or "us-east-1"

            if not access_key or not secret_key:
                return JSONResponse({"valid": False, "error": "Could not find AWS Access Key ID and Secret Access Key"})

            aws_bin = shutil.which("aws") or "aws"
            env = dict(os.environ)
            env["AWS_ACCESS_KEY_ID"] = access_key
            env["AWS_SECRET_ACCESS_KEY"] = secret_key
            if session_token:
                env["AWS_SESSION_TOKEN"] = session_token
            else:
                env.pop("AWS_SESSION_TOKEN", None)
            env["AWS_DEFAULT_REGION"] = region
            env["AWS_REGION"] = region
            for _k in ("AWS_SHARED_CREDENTIALS_FILE", "AWS_ROLE_ARN", "AWS_PROFILE"):
                env.pop(_k, None)

            import subprocess as _subprocess

            def _run_sts() -> _subprocess.CompletedProcess:
                return _subprocess.run(
                    [aws_bin, "sts", "get-caller-identity", "--output", "json"],
                    env=env,
                    capture_output=True,
                    timeout=15,
                )

            try:
                result = await loop.run_in_executor(None, _run_sts)
            except _subprocess.TimeoutExpired:
                return JSONResponse({"valid": False, "error": "STS call timed out (15s) — check network/proxy"})
            except Exception as sub_exc:
                return JSONResponse({"valid": False, "error": f"Could not run aws CLI ({type(sub_exc).__name__}): {sub_exc}"})

            stdout_text = result.stdout.decode(errors="replace").strip()
            stderr_text = result.stderr.decode(errors="replace").strip()
            
            if result.returncode == 0:
                try:
                    sts_data = json.loads(stdout_text)
                    return JSONResponse({
                        "valid": True,
                        "user": sts_data.get("Arn", ""),
                        "account": sts_data.get("Account", ""),
                    })
                except json.JSONDecodeError:
                    return JSONResponse({"valid": True, "user": stdout_text[:80]})
            else:
                err_msg = stderr_text
                if not err_msg and stdout_text:
                    try:
                        err_json = json.loads(stdout_text)
                        err_msg = err_json.get("message") or err_json.get("Message") or stdout_text
                    except json.JSONDecodeError:
                        err_msg = stdout_text
                return JSONResponse({
                    "valid": False,
                    "error": err_msg or "STS GetCallerIdentity failed (check credentials and region)",
                })

        elif token_type == "kubernetes":
            kube_data = body.get("kube", {})
            kubeconfig_content = kube_data.get("kubeconfig_content", "").strip()
            context = kube_data.get("context", "").strip()
            if not kubeconfig_content:
                return JSONResponse({"valid": False, "error": "Kubeconfig content is empty"})

            import tempfile as _tmpfile, subprocess as _subprocess
            tmp_kube = _tmpfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
            try:
                tmp_kube.write(kubeconfig_content)
                tmp_kube.flush()
                tmp_kube.close()
                os.chmod(tmp_kube.name, 0o600)
                kubectl_bin = shutil.which("kubectl") or "kubectl"
                cmd = [kubectl_bin, "config", "get-contexts", "--kubeconfig", tmp_kube.name]
                if context:
                    cmd += ["--context", context]
                result = await loop.run_in_executor(None, lambda: _subprocess.run(cmd, capture_output=True, timeout=10))
                stdout_text = result.stdout.decode(errors="replace").strip()
                stderr_text = result.stderr.decode(errors="replace").strip()
                
                if result.returncode == 0:
                    lines = [l.strip() for l in stdout_text.splitlines() if l.strip() and not l.startswith("CURRENT")]
                    ctx_names = [l.split()[1] if len(l.split()) > 1 else l.split()[0] for l in lines]
                    ctx_display = context or (ctx_names[0] if ctx_names else "default")
                    return JSONResponse({"valid": True, "user": f"context: {ctx_display}", "contexts": ctx_names})
                else:
                    err = stderr_text or stdout_text or "kubectl config get-contexts failed"
                    return JSONResponse({"valid": False, "error": err[:300]})
            finally:
                try:
                    os.unlink(tmp_kube.name)
                except OSError:
                    pass

        else:
            return JSONResponse({"valid": False, "error": f"Unknown token type: {token_type}"})

    except urllib.error.HTTPError as exc:
        return JSONResponse({"valid": False, "error": f"HTTP {exc.code}"})
    except Exception as exc:
        return JSONResponse({"valid": False, "error": str(exc)})


def _oauth_redirect_uri(request: Request) -> str:
    explicit = os.environ.get("GITHUB_OAUTH_REDIRECT_URI")
    if explicit:
        return explicit
    return str(request.base_url).rstrip("/") + "/api/oauth/callback"

@router.get("/api/oauth/config")
async def oauth_config():
    return JSONResponse({"available": oauth.is_oauth_configured()})

@router.get("/api/oauth/login")
async def oauth_login(request: Request):
    if not oauth.is_oauth_configured():
        return JSONResponse({"error": "OAuth not configured"}, status_code=503)
    state = oauth.generate_state()
    url = oauth.build_authorize_url(_oauth_redirect_uri(request), state)
    return RedirectResponse(url=url, status_code=302)

@router.get("/api/oauth/callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse(_oauth_result_page(error=f"GitHub denied access: {error}"))
    if not code or not state:
        return HTMLResponse(_oauth_result_page(error="Missing code or state parameter"))
    if not oauth.validate_state(state):
        return HTMLResponse(_oauth_result_page(error="Invalid or expired state — please try again"))

    result = await oauth.exchange_code_for_token(code, _oauth_redirect_uri(request))
    if "error" in result:
        desc = result.get("error_description", result.get("error", "Unknown error"))
        return HTMLResponse(_oauth_result_page(error=f"Token exchange failed: {desc}"))

    access_token = result.get("access_token", "")
    if not access_token:
        return HTMLResponse(_oauth_result_page(error="No access token in response"))

    user_info = {}
    user = await oauth.fetch_github_user(access_token)
    if user:
        user_info = {"login": user.get("login", ""), "name": user.get("name", ""), "avatar_url": user.get("avatar_url", "")}

    return HTMLResponse(_oauth_result_page(token=access_token, user=user_info))

def _oauth_result_page(token: str = "", user: dict | None = None, error: str = "") -> str:
    _style = (
        "body{font-family:system-ui,sans-serif;background:#0f1629;color:#f1f5f9;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
        ".box{background:#1a2744;border:1px solid #334155;border-radius:12px;"
        "padding:2rem;max-width:420px;text-align:center}"
        "button{background:#2563eb;color:white;border:none;padding:8px 20px;"
        "border-radius:8px;cursor:pointer;font-size:14px}button:hover{background:#1d4ed8}"
    )
    if error:
        safe = html_mod.escape(error)
        return (
            f'<!DOCTYPE html><html><head><title>OAuth Error</title>'
            f'<style>{_style}.err{{color:#f87171;margin-bottom:1rem}}</style></head>'
            f'<body><div class="box"><p class="err">⚠️ {safe}</p>'
            f'<p><button onclick="window.close()">Close</button></p></div></body></html>'
        )
    token_js = json.dumps(token).replace("</", r"<\/")
    user_js = json.dumps(user or {}).replace("</", r"<\/")
    return (
        f'<!DOCTYPE html><html><head><title>OAuth — Completing login…</title>'
        f'<style>{_style}.ok{{color:#34d399}}.sub{{color:#94a3b8;font-size:0.85rem}}</style></head>'
        f'<body><div class="box" id="msg">'
        f'<p class="ok">✓ Authenticated with GitHub</p>'
        f'<p class="sub">This window will close automatically…</p></div>'
        f'<script>'
        f'if(window.opener){{'
        f'window.opener.postMessage({{type:"github-oauth-callback",'
        f'access_token:{token_js},user:{user_js}}},window.location.origin);'
        f'setTimeout(function(){{window.close()}},600)'
        f'}}else{{'
        f'document.getElementById("msg").innerHTML='
        f'"<p style=\\"color:#f87171\\">Could not communicate with the main window. '
        f'Please close this window and try again.</p>"'
        f'}}'
        f'</script></body></html>'
    )

@router.post("/api/auth/antigravity/validate")
async def validate_antigravity_key(request: Request):
    """Validate a Gemini API key for Antigravity provider."""
    from ..dependencies import antigravity_service
    if not antigravity_service:
        return JSONResponse({"valid": False, "error": "Antigravity SDK is not installed."}, status_code=501)
    body = await _get_json_body(request)
    api_key = body.get("api_key", "").strip()
    if not api_key:
        return JSONResponse({"valid": False, "error": "No API key provided"})
    result = await antigravity_service.validate_api_key(api_key)
    return JSONResponse(result)

@router.post("/api/auth/cursor/validate")
async def validate_cursor_key(request: Request):
    """Validate a Cursor API key."""
    from ..dependencies import cursor_service
    if not cursor_service:
        return JSONResponse({"valid": False, "error": "Cursor SDK is not installed."}, status_code=501)
    body = await _get_json_body(request)
    api_key = body.get("api_key", "").strip()
    if not api_key:
        return JSONResponse({"valid": False, "error": "No API key provided"})
    result = await cursor_service.validate_api_key(api_key)
    return JSONResponse(result)

@router.post("/api/auth/claude/validate")
async def validate_claude_key(request: Request):
    """Validate credentials for Claude (Anthropic, Bedrock, Vertex)."""
    from ..dependencies import claude_service
    if not claude_service:
        return JSONResponse({"valid": False, "error": "Claude Agent SDK is not installed."}, status_code=501)
    body = await _get_json_body(request)
    api_key = body.get("api_key", "").strip()
    auth_method = body.get("auth_method", "anthropic").strip()
    bedrock_region = body.get("bedrock_region", "us-east-1")
    
    if not api_key:
        return JSONResponse({"valid": False, "error": "No API key provided"})
        
    result = await claude_service.validate_api_key(api_key, auth_method, bedrock_region)
    return JSONResponse(result)

@router.post("/api/auth/codex/validate")
async def validate_codex_key(request: Request):
    """Validate a Codex API key."""
    from ..dependencies import codex_service
    if not codex_service:
        return JSONResponse({"valid": False, "error": "Codex SDK is not installed."}, status_code=501)
    body = await _get_json_body(request)
    api_key = body.get("api_key", "").strip()
    auth_method = body.get("auth_method", "openai").strip()
    bedrock_region = body.get("bedrock_region", "us-east-1").strip()
    ollama_base_url = body.get("ollama_base_url", "http://localhost:11434/v1").strip()
    
    if not api_key and auth_method != "ollama":
        return JSONResponse({"valid": False, "error": "No API key provided"})
        
    result = await codex_service.validate_api_key(
        api_key, auth_method=auth_method, bedrock_region=bedrock_region, ollama_base_url=ollama_base_url
    )
    return JSONResponse(result)

